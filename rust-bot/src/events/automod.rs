//! Auto-moderation (portage de `cogs/automod.py`).
//!
//! Ce cog n'etait pas charge par `main.py` cote Python ; il est ici branche
//! dans le dispatcher d'evenements.

use std::time::Instant;

use chrono::{Duration as ChronoDuration, Utc};
use once_cell::sync::Lazy;
use poise::serenity_prelude as serenity;
use regex::Regex;
use serenity::all::{CreateEmbed, CreateEmbedFooter, CreateMessage, GuildId, Message};

use crate::config::{COLOR_ERROR, COLOR_WARNING};
use crate::data::{Data, Error};
use crate::db::{self, AutomodConfig};
use crate::helpers;
use crate::util::format_duration;

static INVITE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"discord\.gg/[a-zA-Z0-9]+|discord\.com/invite/[a-zA-Z0-9]+|discordapp\.com/invite/[a-zA-Z0-9]+",
    )
    .unwrap()
});

/// Portage de `self.spam_words`.
const SPAM_WORDS: &[&str] = &[
    "spam",
    "scam",
    "free nitro",
    "free money",
    "click here",
    "nitro gratuit",
];

/// Point d'entree, equivalent de `AutoMod.on_message`.
pub async fn on_message(
    ctx: &serenity::Context,
    data: &Data,
    message: &Message,
) -> Result<(), Error> {
    let Some(guild_id) = message.guild_id else {
        return Ok(());
    };
    if message.author.bot {
        return Ok(());
    }

    // `message.author.guild_permissions.manage_messages` — les moderateurs
    // sont exemptes de tous les filtres.
    let Ok(member) = guild_id.member(ctx, message.author.id).await else {
        return Ok(());
    };
    if helpers::member_permissions(ctx, &member).manage_messages() {
        return Ok(());
    }

    let cfg = db::get_automod_config(&data.db, guild_id.get() as i64).await?;

    // Comme cote Python, les sept controles s'executent a la suite : un message
    // peut declencher plusieurs violations.
    check_spam(ctx, data, message, &cfg).await?;
    check_mention_spam(ctx, data, message, &cfg).await?;
    check_discord_invites(ctx, data, message).await?;
    check_suspicious_content(ctx, data, message).await?;
    check_blacklist(ctx, data, message).await?;
    check_caps(ctx, data, message, &cfg).await?;
    check_file_flood(ctx, data, message, &cfg).await?;

    Ok(())
}

// ── Filtres ──────────────────────────────────────────────────────────────────

async fn check_spam(
    ctx: &serenity::Context,
    data: &Data,
    message: &Message,
    cfg: &AutomodConfig,
) -> Result<(), Error> {
    let uid = message.author.id.get();
    let now = Instant::now();

    let count = Data::push_window(&data.spam_tracker, uid, now, cfg.spam_interval, 1);

    if count as i64 >= cfg.spam_threshold {
        Data::clear_window(&data.spam_tracker, uid);
        delete_message(ctx, message).await;
        apply_violation(ctx, data, message, "Spam de messages", 2).await?;
        return Ok(());
    }

    let repeated = data
        .last_messages
        .get(&uid)
        .map(|prev| *prev == message.content)
        .unwrap_or(false);

    if repeated && message.content.chars().count() > 10 {
        delete_message(ctx, message).await;
        apply_violation(ctx, data, message, "Messages répétés identiques", 2).await?;
    }

    data.last_messages.insert(uid, message.content.clone());
    Ok(())
}

async fn check_mention_spam(
    ctx: &serenity::Context,
    data: &Data,
    message: &Message,
    cfg: &AutomodConfig,
) -> Result<(), Error> {
    let count = message.mentions.len() + message.mention_roles.len();
    if count as i64 >= cfg.max_mentions {
        delete_message(ctx, message).await;
        apply_violation(
            ctx,
            data,
            message,
            &format!("Spam de mentions ({count} mentions)"),
            3,
        )
        .await?;
    }
    Ok(())
}

async fn check_discord_invites(
    ctx: &serenity::Context,
    data: &Data,
    message: &Message,
) -> Result<(), Error> {
    if INVITE_RE.is_match(&message.content) {
        delete_message(ctx, message).await;
        apply_violation(
            ctx,
            data,
            message,
            "Lien d'invitation Discord non autorisé",
            1,
        )
        .await?;
    }
    Ok(())
}

async fn check_suspicious_content(
    ctx: &serenity::Context,
    data: &Data,
    message: &Message,
) -> Result<(), Error> {
    let lower = message.content.to_lowercase();
    for word in SPAM_WORDS {
        if lower.contains(word) {
            delete_message(ctx, message).await;
            apply_violation(ctx, data, message, &format!("Contenu suspect : « {word} »"), 3)
                .await?;
            return Ok(());
        }
    }
    Ok(())
}

async fn check_blacklist(
    ctx: &serenity::Context,
    data: &Data,
    message: &Message,
) -> Result<(), Error> {
    let Some(guild_id) = message.guild_id else {
        return Ok(());
    };
    let words = data.blacklist(guild_id.get()).await;
    let lower = message.content.to_lowercase();
    for word in words {
        if lower.contains(&word) {
            delete_message(ctx, message).await;
            apply_violation(ctx, data, message, &format!("Mot interdit : « {word} »"), 2).await?;
            return Ok(());
        }
    }
    Ok(())
}

async fn check_caps(
    ctx: &serenity::Context,
    data: &Data,
    message: &Message,
    cfg: &AutomodConfig,
) -> Result<(), Error> {
    if !cfg.caps_detection {
        return Ok(());
    }
    let letters: Vec<char> = message.content.chars().filter(|c| c.is_alphabetic()).collect();
    if (letters.len() as i64) < cfg.caps_min_length {
        return Ok(());
    }
    let upper = letters.iter().filter(|c| c.is_uppercase()).count();
    let ratio = upper as f64 / letters.len() as f64 * 100.0;

    if ratio >= cfg.caps_percent as f64 {
        delete_message(ctx, message).await;
        apply_violation(
            ctx,
            data,
            message,
            &format!("Abus de majuscules ({}%)", ratio as i64),
            1,
        )
        .await?;
    }
    Ok(())
}

async fn check_file_flood(
    ctx: &serenity::Context,
    data: &Data,
    message: &Message,
    cfg: &AutomodConfig,
) -> Result<(), Error> {
    if message.attachments.is_empty() {
        return Ok(());
    }
    let uid = message.author.id.get();
    let count = Data::push_window(
        &data.file_tracker,
        uid,
        Instant::now(),
        cfg.file_flood_interval,
        message.attachments.len(),
    );

    if count as i64 >= cfg.file_flood_limit {
        Data::clear_window(&data.file_tracker, uid);
        delete_message(ctx, message).await;
        apply_violation(
            ctx,
            data,
            message,
            &format!("Flood de fichiers ({} fichiers)", message.attachments.len()),
            2,
        )
        .await?;
    }
    Ok(())
}

// ── Escalade par points ──────────────────────────────────────────────────────

/// Portage de `_apply_violation` : accumule les points puis choisit l'action.
async fn apply_violation(
    ctx: &serenity::Context,
    data: &Data,
    message: &Message,
    reason: &str,
    points: i64,
) -> Result<(), Error> {
    let Some(guild_id) = message.guild_id else {
        return Ok(());
    };
    let gid = guild_id.get() as i64;
    let uid = message.author.id.get() as i64;
    let cfg = db::get_automod_config(&data.db, gid).await?;

    let total = db::add_violation_points(&data.db, gid, uid, points).await?;

    if total >= cfg.pts_ban {
        action_tempban(ctx, data, message, reason, cfg.pts_ban_duration, total).await?;
    } else if total >= cfg.pts_kick {
        action_kick(ctx, data, message, reason, total).await?;
    } else if total >= cfg.pts_mute {
        action_mute(ctx, data, message, reason, cfg.pts_mute_duration, total).await?;
    } else if total >= cfg.pts_warn {
        action_warn(ctx, data, message, reason, total).await?;
    } else {
        notify(ctx, message, reason, points, total).await?;
    }

    Ok(())
}

/// Portage de `_notify` : simple rappel, supprime au bout de 12 s.
async fn notify(
    ctx: &serenity::Context,
    message: &Message,
    reason: &str,
    points: i64,
    total: i64,
) -> Result<(), Error> {
    let embed = CreateEmbed::new()
        .title("⚠️ Avertissement Auto-Mod")
        .description(format!(
            "<@{}>, respectez les règles du serveur !",
            message.author.id
        ))
        .color(COLOR_WARNING)
        .field("Violation", reason, true)
        .field("Points", format!("+{points} → **{total}** pts"), true)
        .footer(CreateEmbedFooter::new("Système d'auto-modération"));

    send_temp(ctx, message, embed, 12).await;
    Ok(())
}

async fn action_warn(
    ctx: &serenity::Context,
    data: &Data,
    message: &Message,
    reason: &str,
    total: i64,
) -> Result<(), Error> {
    let guild_id = message.guild_id.unwrap();
    let gid = guild_id.get() as i64;
    let uid = message.author.id.get() as i64;
    let bot_id = ctx.cache.current_user().id.get() as i64;
    let tagged = format!("[Auto-Mod] {reason}");

    db::add_warning(&data.db, gid, uid, bot_id, &tagged).await?;
    db::add_sanction(&data.db, gid, uid, bot_id, "warn", Some(&tagged), None).await?;
    let count = db::get_warnings(&data.db, gid, uid).await?.len();
    let max_warnings = data.config.max_warnings;

    let embed = CreateEmbed::new()
        .title("🤖 Auto-Mod — Avertissement")
        .description(format!(
            "<@{}> a reçu un avertissement automatique.",
            message.author.id
        ))
        .color(COLOR_WARNING)
        .field("Raison", reason, true)
        .field("Points accumulés", format!("**{total}** pts"), true)
        .field("Avertissements", format!("{count}/{max_warnings}"), true)
        .footer(CreateEmbedFooter::new("Système d'auto-modération"));

    send_temp(ctx, message, embed, 15).await;

    let guild_name = guild_name(ctx, guild_id);
    helpers::send_dm(
        ctx,
        message.author.id,
        CreateEmbed::new()
            .title("Avertissement automatique reçu")
            .description(format!(
                "Vous avez reçu un avertissement dans **{guild_name}**."
            ))
            .color(COLOR_WARNING)
            .field("Raison", reason, false)
            .field("Points accumulés", format!("{total} pts"), false),
    )
    .await;

    Ok(())
}

async fn action_mute(
    ctx: &serenity::Context,
    data: &Data,
    message: &Message,
    reason: &str,
    duration: i64,
    total: i64,
) -> Result<(), Error> {
    let guild_id = message.guild_id.unwrap();
    let mute_role =
        helpers::ensure_mute_role(ctx, guild_id, &data.config.mute_role_name).await?;

    let Ok(member) = guild_id.member(ctx, message.author.id).await else {
        return Ok(());
    };
    if member.roles.contains(&mute_role) {
        return Ok(());
    }

    if helpers::add_role_reason(
        &ctx.http,
        guild_id,
        message.author.id,
        mute_role,
        &format!("Auto-Mod : {reason}"),
    )
    .await
    .is_err()
    {
        return Ok(()); // `except discord.Forbidden: pass`
    }

    let gid = guild_id.get() as i64;
    let uid = message.author.id.get() as i64;
    let bot_id = ctx.cache.current_user().id.get() as i64;
    let tagged = format!("[Auto-Mod] {reason}");
    let unmute_at = Utc::now() + ChronoDuration::seconds(duration);
    let human = format_duration(duration);

    db::add_mute(&data.db, gid, uid, bot_id, &tagged, Some(unmute_at.naive_utc())).await?;
    db::add_sanction(&data.db, gid, uid, bot_id, "mute", Some(&tagged), Some(&human)).await?;
    db::reset_violation_points(&data.db, gid, uid).await?;

    let embed = CreateEmbed::new()
        .title("🤖 Auto-Mod — Mute Temporaire")
        .description(format!(
            "<@{}> a été rendu muet automatiquement.",
            message.author.id
        ))
        .color(COLOR_WARNING)
        .field("Raison", reason, true)
        .field("Durée", &human, true)
        .field("Points accumulés", format!("**{total}** pts", ), true)
        .footer(CreateEmbedFooter::new(
            "Système d'auto-modération • Points réinitialisés",
        ));

    send_temp(ctx, message, embed, 15).await;

    // `bot.loop.create_task(_unmute())`
    let http = ctx.http.clone();
    let pool = data.db.clone();
    let target = message.author.id;
    tokio::spawn(async move {
        tokio::time::sleep(std::time::Duration::from_secs(duration.max(0) as u64)).await;
        if let Ok(m) = guild_id.member(&http, target).await {
            if m.roles.contains(&mute_role) {
                let _ = helpers::remove_role_reason(
                    &http,
                    guild_id,
                    target,
                    mute_role,
                    "Auto-unmute expiré",
                )
                .await;
            }
        }
        let _ = db::remove_mute(&pool, guild_id.get() as i64, target.get() as i64).await;
    });

    Ok(())
}

async fn action_kick(
    ctx: &serenity::Context,
    data: &Data,
    message: &Message,
    reason: &str,
    total: i64,
) -> Result<(), Error> {
    let guild_id = message.guild_id.unwrap();
    let guild_name = guild_name(ctx, guild_id);

    helpers::send_dm(
        ctx,
        message.author.id,
        CreateEmbed::new()
            .title("Vous avez été expulsé automatiquement")
            .description(format!(
                "Vous avez été expulsé de **{guild_name}** par le système d'auto-modération."
            ))
            .color(COLOR_ERROR)
            .field("Raison", reason, false),
    )
    .await;

    let Ok(member) = guild_id.member(ctx, message.author.id).await else {
        return Ok(());
    };
    if member
        .kick_with_reason(ctx, &format!("Auto-Mod : {reason} ({total} pts)"))
        .await
        .is_err()
    {
        return Ok(());
    }

    let gid = guild_id.get() as i64;
    let uid = message.author.id.get() as i64;
    let bot_id = ctx.cache.current_user().id.get() as i64;
    db::add_sanction(
        &data.db,
        gid,
        uid,
        bot_id,
        "kick",
        Some(&format!("[Auto-Mod] {reason}")),
        None,
    )
    .await?;
    db::reset_violation_points(&data.db, gid, uid).await?;

    let embed = CreateEmbed::new()
        .title("🤖 Auto-Mod — Expulsion")
        .description(format!(
            "**{}** a été expulsé automatiquement.",
            message.author.name
        ))
        .color(COLOR_ERROR)
        .field("Raison", reason, true)
        .field("Points accumulés", format!("**{total}** pts"), true)
        .footer(CreateEmbedFooter::new(
            "Système d'auto-modération • Points réinitialisés",
        ));

    send_temp(ctx, message, embed, 15).await;
    Ok(())
}

async fn action_tempban(
    ctx: &serenity::Context,
    data: &Data,
    message: &Message,
    reason: &str,
    duration: i64,
    total: i64,
) -> Result<(), Error> {
    let guild_id = message.guild_id.unwrap();
    let guild_name = guild_name(ctx, guild_id);
    let human = format_duration(duration);

    helpers::send_dm(
        ctx,
        message.author.id,
        CreateEmbed::new()
            .title("Vous avez été banni temporairement")
            .description(format!(
                "Vous avez été banni de **{guild_name}** par le système d'auto-modération."
            ))
            .color(COLOR_ERROR)
            .field("Raison", reason, false)
            .field("Durée", &human, false),
    )
    .await;

    let Ok(member) = guild_id.member(ctx, message.author.id).await else {
        return Ok(());
    };
    if member
        .ban_with_reason(&ctx.http, 0, format!("Auto-Mod : {reason} ({total} pts)"))
        .await
        .is_err()
    {
        return Ok(());
    }

    let gid = guild_id.get() as i64;
    let uid = message.author.id.get() as i64;
    let bot_id = ctx.cache.current_user().id.get() as i64;
    let tagged = format!("[Auto-Mod] {reason}");
    let unban_at = Utc::now() + ChronoDuration::seconds(duration);

    db::add_tempban(&data.db, gid, uid, bot_id, &tagged, unban_at.naive_utc()).await?;
    db::add_sanction(
        &data.db,
        gid,
        uid,
        bot_id,
        "tempban",
        Some(&tagged),
        Some(&human),
    )
    .await?;
    db::reset_violation_points(&data.db, gid, uid).await?;

    let embed = CreateEmbed::new()
        .title("🤖 Auto-Mod — Bannissement Temporaire")
        .description(format!(
            "**{}** a été banni temporairement.",
            message.author.name
        ))
        .color(COLOR_ERROR)
        .field("Raison", reason, true)
        .field("Durée", &human, true)
        .field("Points accumulés", format!("**{total}** pts"), true)
        .footer(CreateEmbedFooter::new(
            "Système d'auto-modération • Points réinitialisés",
        ));

    send_temp(ctx, message, embed, 15).await;
    Ok(())
}

// ── Utilitaires ──────────────────────────────────────────────────────────────

/// `_delete_message` : ignore Forbidden / NotFound.
async fn delete_message(ctx: &serenity::Context, message: &Message) {
    let _ = message.delete(ctx).await;
}

/// `await msg.delete(delay=N)` : envoi puis suppression differee.
async fn send_temp(ctx: &serenity::Context, message: &Message, embed: CreateEmbed, delay: u64) {
    let Ok(sent) = message
        .channel_id
        .send_message(&ctx.http, CreateMessage::new().embed(embed))
        .await
    else {
        return;
    };
    let http = ctx.http.clone();
    tokio::spawn(async move {
        tokio::time::sleep(std::time::Duration::from_secs(delay)).await;
        let _ = sent.delete(&http).await;
    });
}

fn guild_name(ctx: &serenity::Context, guild_id: GuildId) -> String {
    ctx.cache
        .guild(guild_id)
        .map(|g| g.name.to_string())
        .unwrap_or_default()
}
