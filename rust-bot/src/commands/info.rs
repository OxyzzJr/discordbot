//! Commandes d'information et de consultation
//! (portage de `cogs/moderation.py`, partie infos / cases / regles).

use anyhow::anyhow;
use poise::serenity_prelude as serenity;
use serenity::all::{CreateEmbed, CreateEmbedFooter, Member};

use crate::commands::moderation::{deny, guild_ctx};
use crate::config::{COLOR_INFO, COLOR_SUCCESS, COLOR_WARNING};
use crate::data::{Context, Error};
use crate::db;
use crate::helpers;
use crate::util::{ts_date, truncate};

/// Portage de `ACTION_EMOJIS`.
pub fn action_emoji(action: &str) -> &'static str {
    match action {
        "kick" => "👢",
        "ban" => "🔨",
        "tempban" => "⏱️",
        "mute" => "🔇",
        "unmute" => "🔊",
        "warn" => "⚠️",
        "unban" => "✅",
        _ => "🔹",
    }
}

/// `action.capitalize()` cote Python.
fn capitalize(s: &str) -> String {
    let mut chars = s.chars();
    match chars.next() {
        Some(first) => first.to_uppercase().collect::<String>() + &chars.as_str().to_lowercase(),
        None => String::new(),
    }
}

// ── /userinfo ────────────────────────────────────────────────────────────────

/// Informations complètes sur un membre
#[poise::command(slash_command, guild_only)]
pub async fn userinfo(
    ctx: Context<'_>,
    #[description = "Le membre à inspecter (défaut : vous-même)"] member: Option<Member>,
) -> Result<(), Error> {
    let guild_id = ctx.guild_id().ok_or_else(|| anyhow!("hors guilde"))?;
    let member = match member {
        Some(m) => m,
        None => ctx
            .author_member()
            .await
            .ok_or_else(|| anyhow!("membre auteur introuvable"))?
            .into_owned(),
    };

    let sanctions = db::get_sanctions(
        &ctx.data().db,
        guild_id.get() as i64,
        member.user.id.get() as i64,
    )
    .await?;

    // Rôles tries par position decroissante, @everyone exclu — equivalent de
    // `reversed(member.roles)` chez discord.py.
    let (roles_str, role_count, colour) = {
        let guild = ctx
            .guild()
            .ok_or_else(|| anyhow!("guilde absente du cache"))?;
        let mut roles: Vec<_> = member
            .roles
            .iter()
            .filter_map(|id| guild.roles.get(id))
            .collect();
        roles.sort_by_key(|r| std::cmp::Reverse(r.position));

        let count = roles.len();
        let shown: Vec<String> = roles.iter().take(10).map(|r| format!("<@&{}>", r.id)).collect();
        let text = if shown.is_empty() {
            "Aucun rôle".to_string()
        } else if count > 10 {
            format!("{} *+{} autres*", shown.join(" "), count - 10)
        } else {
            shown.join(" ")
        };

        let colour = roles
            .iter()
            .find(|r| r.colour.0 != 0)
            .map(|r| r.colour.0)
            .unwrap_or(COLOR_INFO);

        (text, count, colour)
    };

    let mut embed = CreateEmbed::new()
        .title(format!("👤 Profil de {}", member.user.name))
        .color(colour)
        .thumbnail(member.face())
        .field("Nom d'utilisateur", member.user.name.clone(), true)
        .field("Pseudonyme", member.display_name().to_string(), true)
        .field("ID", member.user.id.to_string(), true)
        .field("Compte créé le", ts_date(&member.user.created_at()), true)
        .field(
            "Rejoint le",
            match member.joined_at {
                Some(t) => ts_date(&t),
                None => "Inconnu".to_string(),
            },
            true,
        )
        .field("Bot", if member.user.bot { "Oui" } else { "Non" }, true)
        .field(format!("Rôles ({role_count})"), roles_str, false)
        .field("Sanctions enregistrées", sanctions.len().to_string(), true);

    if let Some(since) = member.premium_since {
        embed = embed.field("Boost depuis", ts_date(&since), true);
    }

    ctx.send(
        poise::CreateReply::default()
            .embed(embed.footer(CreateEmbedFooter::new(format!("ID : {}", member.user.id)))),
    )
    .await?;

    Ok(())
}

// ── /serverinfo ──────────────────────────────────────────────────────────────

/// Informations sur le serveur
#[poise::command(slash_command, guild_only)]
pub async fn serverinfo(ctx: Context<'_>) -> Result<(), Error> {
    let guild_id = ctx.guild_id().ok_or_else(|| anyhow!("hors guilde"))?;

    // Le `GuildRef` du cache ne traverse pas un `await` : on extrait tout ici.
    let (
        name,
        icon,
        owner_id,
        member_count,
        channel_count,
        role_count,
        boosts,
        premium_tier,
        verification,
    ) = {
        let g = ctx
            .guild()
            .ok_or_else(|| anyhow!("guilde absente du cache"))?;
        (
            g.name.clone(),
            g.icon_url(),
            g.owner_id,
            g.member_count,
            g.channels.len(),
            g.roles.len(),
            g.premium_subscription_count.unwrap_or(0),
            match g.premium_tier {
                serenity::PremiumTier::Tier0 => 0u8,
                serenity::PremiumTier::Tier1 => 1,
                serenity::PremiumTier::Tier2 => 2,
                serenity::PremiumTier::Tier3 => 3,
                _ => 0,
            },
            format!("{:?}", g.verification_level),
        )
    };

    let mut embed = CreateEmbed::new()
        .title(format!("🏠 {name}"))
        .color(COLOR_INFO);
    if let Some(url) = icon {
        embed = embed.thumbnail(url);
    }

    embed = embed
        .field("Propriétaire", format!("<@{owner_id}>"), true)
        .field("ID", guild_id.to_string(), true)
        .field("Créé le", ts_date(&guild_id.created_at()), true)
        .field("Membres", member_count.to_string(), true)
        .field("Salons", channel_count.to_string(), true)
        .field("Rôles", role_count.to_string(), true)
        .field("Boosts", boosts.to_string(), true)
        .field("Niveau de boost", premium_tier.to_string(), true)
        .field("Vérification", capitalize(&verification), true);

    ctx.send(poise::CreateReply::default().embed(embed)).await?;
    Ok(())
}

// ── /historique ──────────────────────────────────────────────────────────────

/// Historique des sanctions d'un membre
#[poise::command(slash_command, guild_only)]
pub async fn historique(
    ctx: Context<'_>,
    #[description = "Le membre concerné"] member: Member,
) -> Result<(), Error> {
    let g = guild_ctx(ctx).await?;
    if !g.author_perms.manage_messages() {
        return deny(ctx, "❌ Permission insuffisante !").await;
    }

    let sanctions = db::get_sanctions(
        &ctx.data().db,
        g.guild_id.get() as i64,
        member.user.id.get() as i64,
    )
    .await?;

    if sanctions.is_empty() {
        ctx.send(
            poise::CreateReply::default().embed(
                CreateEmbed::new()
                    .title("✅ Aucune Sanction")
                    .description(format!("**{}** n'a aucune sanction.", member.user.name))
                    .color(COLOR_SUCCESS)
                    .footer(CreateEmbedFooter::new(format!("ID : {}", member.user.id))),
            ),
        )
        .await?;
        return Ok(());
    }

    let total = sanctions.len();
    let avatar = member.face();

    let pages = helpers::build_pages(
        &sanctions,
        &format!("📋 Historique de {}", member.user.name),
        COLOR_WARNING,
        5,
        |_, s| {
            let dur = s
                .duration
                .as_deref()
                .map(|d| format!(" ({d})"))
                .unwrap_or_default();
            (
                format!(
                    "{} Case #{} — {}{}",
                    action_emoji(&s.action),
                    s.case_id,
                    capitalize(&s.action),
                    dur
                ),
                format!(
                    "**Raison :** {}\n**Modérateur :** <@{}>\n**Date :** {}",
                    s.reason.as_deref().unwrap_or("Aucune"),
                    s.moderator_id,
                    s.timestamp
                ),
            )
        },
    );

    let pages: Vec<_> = pages
        .into_iter()
        .map(|p| {
            p.description(format!("Total : **{total}** sanction(s)"))
                .thumbnail(avatar.clone())
        })
        .collect();

    helpers::paginate(ctx, pages).await?;
    Ok(())
}

// ── /case ────────────────────────────────────────────────────────────────────

/// Consulter un case de modération
#[poise::command(slash_command, guild_only, rename = "case")]
pub async fn case_cmd(
    ctx: Context<'_>,
    #[description = "Numéro du case"] numero: i64,
) -> Result<(), Error> {
    let g = guild_ctx(ctx).await?;
    if !g.author_perms.manage_messages() {
        return deny(ctx, "❌ Permission insuffisante !").await;
    }

    let Some(row) = db::get_case(&ctx.data().db, g.guild_id.get() as i64, numero).await? else {
        return deny(ctx, &format!("❌ Case #{numero} introuvable.")).await;
    };

    let mut embed = CreateEmbed::new()
        .title(format!(
            "{} Case #{} — {}",
            action_emoji(&row.action),
            row.case_id,
            capitalize(&row.action)
        ))
        .color(COLOR_WARNING)
        .field("Membre", format!("<@{}>", row.user_id), true)
        .field("Modérateur", format!("<@{}>", row.moderator_id), true);

    if let Some(d) = &row.duration {
        embed = embed.field("Durée", d, true);
    }

    embed = embed
        .field("Raison", row.reason.as_deref().unwrap_or("Aucune"), false)
        .field("Date", &row.timestamp, false)
        .footer(CreateEmbedFooter::new(format!(
            "Case #{} • Utilisez /editcase {} pour modifier la raison",
            row.case_id, row.case_id
        )));

    ctx.send(poise::CreateReply::default().embed(embed)).await?;
    Ok(())
}

// ── /editcase ────────────────────────────────────────────────────────────────

/// Modifier la raison d'un case
#[poise::command(slash_command, guild_only)]
pub async fn editcase(
    ctx: Context<'_>,
    #[description = "Numéro du case"] numero: i64,
    #[description = "Nouvelle raison"] nouvelle_raison: String,
) -> Result<(), Error> {
    let g = guild_ctx(ctx).await?;
    if !g.author_perms.manage_messages() {
        return deny(ctx, "❌ Permission insuffisante !").await;
    }

    let updated = db::edit_case_reason(
        &ctx.data().db,
        g.guild_id.get() as i64,
        numero,
        &nouvelle_raison,
    )
    .await?;

    if !updated {
        return deny(ctx, &format!("❌ Case #{numero} introuvable.")).await;
    }

    ctx.send(
        poise::CreateReply::default().embed(
            CreateEmbed::new()
                .title("✅ Case Modifié")
                .description(format!(
                    "La raison du case **#{numero}** a été mise à jour."
                ))
                .color(COLOR_SUCCESS)
                .field("Nouvelle raison", &nouvelle_raison, false)
                .field("Modifié par", format!("<@{}>", ctx.author().id), false),
        ),
    )
    .await?;

    Ok(())
}

// ── /regles ──────────────────────────────────────────────────────────────────

/// Afficher les règles du serveur
#[poise::command(slash_command, guild_only)]
pub async fn regles(ctx: Context<'_>) -> Result<(), Error> {
    let guild_id = ctx.guild_id().ok_or_else(|| anyhow!("hors guilde"))?;

    let rules = db::get_guild_settings(&ctx.data().db, guild_id.get() as i64)
        .await?
        .and_then(|s| s.rules_text)
        .filter(|t| !t.trim().is_empty());

    let Some(rules) = rules else {
        return deny(
            ctx,
            "❌ Aucune règle définie. Un administrateur peut les configurer avec `/setregles`.",
        )
        .await;
    };

    let guild_name = ctx
        .partial_guild()
        .await
        .map(|g| g.name.clone())
        .unwrap_or_default();

    ctx.send(
        poise::CreateReply::default().embed(
            CreateEmbed::new()
                .title(format!("📜 Règles de {guild_name}"))
                .description(truncate(&rules, 4096))
                .color(COLOR_INFO)
                .footer(CreateEmbedFooter::new("Merci de respecter ces règles !")),
        ),
    )
    .await?;

    Ok(())
}

// ── /modhelp ─────────────────────────────────────────────────────────────────

/// Afficher toutes les commandes de modération
#[poise::command(slash_command, guild_only)]
pub async fn modhelp(ctx: Context<'_>) -> Result<(), Error> {
    let embed = CreateEmbed::new()
        .title("🛡️ Commandes de Modération")
        .color(COLOR_INFO)
        .field(
            "⚔️ Sanctions",
            "`/kick` — Expulser\n`/ban` — Bannir\n`/tempban` — Bannissement temporaire\n\
             `/unban` — Débannir\n`/mute [durée]` — Rendre muet\n`/unmute` — Retirer le mute",
            false,
        )
        .field(
            "⚠️ Avertissements",
            "`/warn` — Avertir\n`/warnings` — Voir les avertissements\n`/clearwarnings` — Effacer",
            false,
        )
        .field(
            "📋 Cases",
            "`/case <numéro>` — Consulter un case\n\
             `/editcase <numéro> <raison>` — Modifier la raison",
            false,
        )
        .field(
            "🔧 Messages",
            "`/purge` — Supprimer des messages\n`/slowmode` — Mode lent",
            false,
        )
        .field(
            "📊 Infos",
            "`/userinfo` — Profil d'un membre\n`/serverinfo` — Infos du serveur\n\
             `/historique` — Historique des sanctions\n`/regles` — Règles du serveur",
            false,
        )
        .field(
            "⚙️ Config (Admin)",
            "`/setlogchannel` — Salon de logs\n`/setmodchannel` — Salon modérateur\n\
             `/setregles` — Règles\n`/setwelcome` — Bienvenue\n\
             `/autorole_create_soumises` — Créer le rôle soumises",
            false,
        )
        .footer(CreateEmbedFooter::new(
            "Formats de durée acceptés : 30s • 10m • 2h • 1d",
        ));

    ctx.send(poise::CreateReply::default().embed(embed)).await?;
    Ok(())
}
