//! Commandes de sanction (portage de `cogs/moderation.py`, partie sanctions).

use anyhow::anyhow;
use chrono::{Duration as ChronoDuration, Utc};
use poise::serenity_prelude as serenity;
use serenity::all::{CreateEmbed, CreateEmbedFooter, GuildId, Member, Permissions, UserId};

use crate::config::{COLOR_ERROR, COLOR_INFO, COLOR_SUCCESS, COLOR_WARNING};
use crate::data::{Context, Error};
use crate::db;
use crate::helpers;
use crate::util::{format_duration, parse_duration, ts_full};

/// Portage de `_case_footer`.
pub fn case_footer(case_id: i64, member_id: u64) -> CreateEmbedFooter {
    CreateEmbedFooter::new(format!("Case #{case_id} • ID : {member_id}"))
}

/// Reponse ephemere courte (equivalent des `return await interaction.response
/// .send_message(..., ephemeral=True)` qui parsement le code Python).
pub async fn deny(ctx: Context<'_>, message: &str) -> Result<(), Error> {
    ctx.send(poise::CreateReply::default().content(message).ephemeral(true))
        .await?;
    Ok(())
}

/// Contexte de guilde resolu une fois par commande.
pub struct GuildCtx {
    pub guild_id: GuildId,
    pub author_perms: Permissions,
    pub author_top: i64,
    pub owner_id: UserId,
}

impl GuildCtx {
    /// `interaction.user != interaction.guild.owner` cote Python.
    pub fn author_is_owner(&self, author: UserId) -> bool {
        self.owner_id == author
    }
}

pub async fn guild_ctx(ctx: Context<'_>) -> Result<GuildCtx, Error> {
    let guild_id = ctx.guild_id().ok_or_else(|| anyhow!("hors guilde"))?;
    let author = ctx
        .author_member()
        .await
        .ok_or_else(|| anyhow!("membre auteur introuvable"))?
        .into_owned();

    Ok(GuildCtx {
        guild_id,
        author_perms: helpers::member_permissions(ctx.serenity_context(), &author),
        author_top: helpers::top_role_position(ctx.serenity_context(), &author),
        owner_id: helpers::guild_owner_id(ctx.serenity_context(), guild_id)
            .ok_or_else(|| anyhow!("guilde absente du cache"))?,
    })
}

/// `member.top_role >= interaction.user.top_role and user != owner`
pub fn outranks_author(ctx: Context<'_>, g: &GuildCtx, target: &Member) -> bool {
    let target_top = helpers::top_role_position(ctx.serenity_context(), target);
    target_top >= g.author_top && !g.author_is_owner(ctx.author().id)
}

/// `member.top_role >= interaction.guild.me.top_role`
pub async fn outranks_bot(ctx: Context<'_>, guild_id: GuildId, target: &Member) -> bool {
    let bot_top = helpers::bot_top_role_position(ctx.serenity_context(), guild_id)
        .await
        .unwrap_or(i64::MAX);
    helpers::top_role_position(ctx.serenity_context(), target) >= bot_top
}

const NO_REASON: &str = "Aucune raison fournie";

// ── /kick ────────────────────────────────────────────────────────────────────

/// Expulser un membre du serveur
#[poise::command(slash_command, guild_only)]
pub async fn kick(
    ctx: Context<'_>,
    #[description = "Le membre à expulser"] member: Member,
    #[description = "Raison de l'expulsion"] raison: Option<String>,
) -> Result<(), Error> {
    let raison = raison.unwrap_or_else(|| NO_REASON.to_string());
    let g = guild_ctx(ctx).await?;

    if !g.author_perms.kick_members() {
        return deny(ctx, "❌ Vous n'avez pas la permission d'expulser des membres !").await;
    }
    let bot_perms = helpers::bot_permissions(ctx.serenity_context(), g.guild_id).await?;
    if !bot_perms.kick_members() {
        return deny(ctx, "❌ Je n'ai pas la permission d'expulser des membres !").await;
    }
    if outranks_author(ctx, &g, &member) {
        return deny(ctx, "❌ Rôle supérieur ou égal — action impossible !").await;
    }
    if outranks_bot(ctx, g.guild_id, &member).await {
        return deny(
            ctx,
            "❌ Je ne peux pas agir sur ce membre (rôle supérieur au mien) !",
        )
        .await;
    }

    let preview = CreateEmbed::new()
        .title("👢 Confirmer l'Expulsion")
        .description(format!(
            "Vous êtes sur le point d'expulser **{}**.",
            member.user.name
        ))
        .color(COLOR_WARNING)
        .field("Raison", &raison, false);

    if !helpers::confirm_action(ctx, preview).await? {
        return Ok(());
    }

    let guild_name = ctx
        .partial_guild()
        .await
        .map(|g| g.name.clone())
        .unwrap_or_default();

    helpers::send_dm(
        ctx.serenity_context(),
        member.user.id,
        CreateEmbed::new()
            .title("Vous avez été expulsé")
            .description(format!("Vous avez été expulsé de **{guild_name}**"))
            .color(COLOR_WARNING)
            .field("Raison", &raison, false)
            .field("Modérateur", ctx.author().name.clone(), false),
    )
    .await;

    let reason_log = format!("Expulsé par {} | {}", ctx.author().name, raison);
    if member
        .kick_with_reason(ctx.serenity_context(), &reason_log)
        .await
        .is_err()
    {
        ctx.send(
            poise::CreateReply::default()
                .embed(crate::util::simple_embed("❌ Permission refusée", COLOR_ERROR))
                .components(vec![]),
        )
        .await?;
        return Ok(());
    }

    let case_id = db::add_sanction(
        &ctx.data().db,
        g.guild_id.get() as i64,
        member.user.id.get() as i64,
        ctx.author().id.get() as i64,
        "kick",
        Some(&raison),
        None,
    )
    .await?;

    ctx.send(
        poise::CreateReply::default()
            .embed(
                CreateEmbed::new()
                    .title("✅ Membre Expulsé")
                    .description(format!("**{}** a été expulsé.", member.user.name))
                    .color(COLOR_SUCCESS)
                    .field("Modérateur", format!("<@{}>", ctx.author().id), true)
                    .field("Raison", &raison, true)
                    .footer(case_footer(case_id, member.user.id.get())),
            )
            .components(vec![]),
    )
    .await?;

    Ok(())
}

// ── /ban ─────────────────────────────────────────────────────────────────────

/// Bannir un membre du serveur
#[poise::command(slash_command, guild_only)]
pub async fn ban(
    ctx: Context<'_>,
    #[description = "Le membre à bannir"] member: Member,
    #[description = "Raison du bannissement"] raison: Option<String>,
    #[description = "Jours de messages à supprimer (0-7)"] supprimer_jours: Option<i64>,
) -> Result<(), Error> {
    let raison = raison.unwrap_or_else(|| NO_REASON.to_string());
    let jours = supprimer_jours.unwrap_or(0);
    let g = guild_ctx(ctx).await?;

    if !g.author_perms.ban_members() {
        return deny(ctx, "❌ Vous n'avez pas la permission de bannir des membres !").await;
    }
    let bot_perms = helpers::bot_permissions(ctx.serenity_context(), g.guild_id).await?;
    if !bot_perms.ban_members() {
        return deny(ctx, "❌ Je n'ai pas la permission de bannir des membres !").await;
    }
    if !(0..=7).contains(&jours) {
        return deny(ctx, "❌ Les jours doivent être entre 0 et 7 !").await;
    }
    if outranks_author(ctx, &g, &member) {
        return deny(ctx, "❌ Rôle supérieur ou égal — action impossible !").await;
    }
    if outranks_bot(ctx, g.guild_id, &member).await {
        return deny(ctx, "❌ Je ne peux pas agir sur ce membre !").await;
    }

    let preview = CreateEmbed::new()
        .title("🔨 Confirmer le Bannissement")
        .description(format!(
            "Vous êtes sur le point de bannir **{}**.",
            member.user.name
        ))
        .color(COLOR_ERROR)
        .field("Raison", &raison, false)
        .field("Messages supprimés", format!("{jours} jours"), false);

    if !helpers::confirm_action(ctx, preview).await? {
        return Ok(());
    }

    let guild_name = ctx
        .partial_guild()
        .await
        .map(|g| g.name.clone())
        .unwrap_or_default();

    helpers::send_dm(
        ctx.serenity_context(),
        member.user.id,
        CreateEmbed::new()
            .title("Vous avez été banni")
            .description(format!("Vous avez été banni de **{guild_name}**"))
            .color(COLOR_ERROR)
            .field("Raison", &raison, false)
            .field("Modérateur", ctx.author().name.clone(), false),
    )
    .await;

    let reason_log = format!("Banni par {} | {}", ctx.author().name, raison);
    if member
        .ban_with_reason(ctx.http(), jours as u8, &reason_log)
        .await
        .is_err()
    {
        ctx.send(
            poise::CreateReply::default()
                .embed(crate::util::simple_embed("❌ Permission refusée", COLOR_ERROR))
                .components(vec![]),
        )
        .await?;
        return Ok(());
    }

    let case_id = db::add_sanction(
        &ctx.data().db,
        g.guild_id.get() as i64,
        member.user.id.get() as i64,
        ctx.author().id.get() as i64,
        "ban",
        Some(&raison),
        None,
    )
    .await?;

    ctx.send(
        poise::CreateReply::default()
            .embed(
                CreateEmbed::new()
                    .title("🔨 Membre Banni")
                    .description(format!("**{}** a été banni.", member.user.name))
                    .color(COLOR_ERROR)
                    .field("Modérateur", format!("<@{}>", ctx.author().id), true)
                    .field("Raison", &raison, true)
                    .field("Messages Supprimés", format!("{jours} jours"), true)
                    .footer(case_footer(case_id, member.user.id.get())),
            )
            .components(vec![]),
    )
    .await?;

    Ok(())
}

// ── /tempban ─────────────────────────────────────────────────────────────────

/// Bannir temporairement un membre
#[poise::command(slash_command, guild_only)]
pub async fn tempban(
    ctx: Context<'_>,
    #[description = "Le membre à bannir"] member: Member,
    #[description = "Durée (ex: 10m, 2h, 1d)"] duree: String,
    #[description = "Raison"] raison: Option<String>,
) -> Result<(), Error> {
    let raison = raison.unwrap_or_else(|| NO_REASON.to_string());
    let g = guild_ctx(ctx).await?;

    if !g.author_perms.ban_members() {
        return deny(ctx, "❌ Vous n'avez pas la permission de bannir des membres !").await;
    }
    if outranks_author(ctx, &g, &member) {
        return deny(ctx, "❌ Rôle supérieur ou égal — action impossible !").await;
    }

    let Some(seconds) = parse_duration(&duree) else {
        return deny(ctx, "❌ Format invalide. Exemples : `10m`, `2h`, `1d`").await;
    };

    let unban_at = Utc::now() + ChronoDuration::seconds(seconds);
    let duree_lisible = format_duration(seconds);

    let preview = CreateEmbed::new()
        .title("⏱️ Confirmer le Bannissement Temporaire")
        .description(format!(
            "Bannir **{}** pendant **{duree_lisible}** ?",
            member.user.name
        ))
        .color(COLOR_ERROR)
        .field("Raison", &raison, false);

    if !helpers::confirm_action(ctx, preview).await? {
        return Ok(());
    }

    let guild_name = ctx
        .partial_guild()
        .await
        .map(|g| g.name.clone())
        .unwrap_or_default();

    helpers::send_dm(
        ctx.serenity_context(),
        member.user.id,
        CreateEmbed::new()
            .title("Vous avez été banni temporairement")
            .description(format!(
                "Banni de **{guild_name}** pendant **{duree_lisible}**."
            ))
            .color(COLOR_ERROR)
            .field("Raison", &raison, false),
    )
    .await;

    let reason_log = format!(
        "Tempban ({duree_lisible}) par {} | {}",
        ctx.author().name,
        raison
    );
    if member
        .ban_with_reason(ctx.http(), 0, &reason_log)
        .await
        .is_err()
    {
        ctx.send(
            poise::CreateReply::default()
                .embed(crate::util::simple_embed("❌ Permission refusée", COLOR_ERROR))
                .components(vec![]),
        )
        .await?;
        return Ok(());
    }

    db::add_tempban(
        &ctx.data().db,
        g.guild_id.get() as i64,
        member.user.id.get() as i64,
        ctx.author().id.get() as i64,
        &raison,
        unban_at.naive_utc(),
    )
    .await?;

    let case_id = db::add_sanction(
        &ctx.data().db,
        g.guild_id.get() as i64,
        member.user.id.get() as i64,
        ctx.author().id.get() as i64,
        "tempban",
        Some(&raison),
        Some(&duree),
    )
    .await?;

    ctx.send(
        poise::CreateReply::default()
            .embed(
                CreateEmbed::new()
                    .title("⏱️ Membre Banni Temporairement")
                    .description(format!(
                        "**{}** banni pour **{duree_lisible}**.",
                        member.user.name
                    ))
                    .color(COLOR_ERROR)
                    .field("Modérateur", format!("<@{}>", ctx.author().id), true)
                    .field("Durée", &duree_lisible, true)
                    .field("Raison", &raison, true)
                    .field("Débannissement le", ts_full(&unban_at), false)
                    .footer(case_footer(case_id, member.user.id.get())),
            )
            .components(vec![]),
    )
    .await?;

    Ok(())
}

// ── /unban ───────────────────────────────────────────────────────────────────

/// Débannir un utilisateur du serveur
#[poise::command(slash_command, guild_only)]
pub async fn unban(
    ctx: Context<'_>,
    #[description = "L'ID de l'utilisateur à débannir"] user_id: String,
    #[description = "Raison"] raison: Option<String>,
) -> Result<(), Error> {
    let raison = raison.unwrap_or_else(|| NO_REASON.to_string());
    let g = guild_ctx(ctx).await?;

    if !g.author_perms.ban_members() {
        return deny(ctx, "❌ Vous n'avez pas la permission de débannir !").await;
    }

    let Ok(uid) = user_id.parse::<u64>() else {
        return deny(ctx, "❌ ID invalide !").await;
    };
    let uid = UserId::new(uid);

    // Remplace le parcours des 2000 premiers bans cote Python par une
    // interrogation directe : meme resultat, une seule requete.
    let Ok(Some(ban)) = ctx.http().get_ban(g.guild_id, uid).await else {
        return deny(ctx, "❌ Cet utilisateur n'est pas banni !").await;
    };

    let reason_log = format!("Débanni par {} | {}", ctx.author().name, raison);
    if helpers::unban_reason(ctx.http(), g.guild_id, uid, &reason_log)
        .await
        .is_err()
    {
        return deny(ctx, "❌ Permission refusée !").await;
    }

    db::deactivate_tempban(&ctx.data().db, g.guild_id.get() as i64, uid.get() as i64).await?;
    let case_id = db::add_sanction(
        &ctx.data().db,
        g.guild_id.get() as i64,
        uid.get() as i64,
        ctx.author().id.get() as i64,
        "unban",
        Some(&raison),
        None,
    )
    .await?;

    ctx.send(
        poise::CreateReply::default().embed(
            CreateEmbed::new()
                .title("✅ Membre Débanni")
                .description(format!("**{}** a été débanni.", ban.user.name))
                .color(COLOR_SUCCESS)
                .field("Modérateur", format!("<@{}>", ctx.author().id), true)
                .field("Raison", &raison, true)
                .footer(case_footer(case_id, uid.get())),
        ),
    )
    .await?;

    Ok(())
}

// ── /mute ────────────────────────────────────────────────────────────────────

/// Rendre muet un membre
#[poise::command(slash_command, guild_only)]
pub async fn mute(
    ctx: Context<'_>,
    #[description = "Le membre à rendre muet"] member: Member,
    #[description = "Durée optionnelle (ex: 10m, 2h)"] duree: Option<String>,
    #[description = "Raison"] raison: Option<String>,
) -> Result<(), Error> {
    let raison = raison.unwrap_or_else(|| NO_REASON.to_string());
    let g = guild_ctx(ctx).await?;

    if !g.author_perms.manage_messages() {
        return deny(ctx, "❌ Permission insuffisante !").await;
    }
    if outranks_author(ctx, &g, &member) {
        return deny(ctx, "❌ Rôle supérieur ou égal — action impossible !").await;
    }

    let mut seconds = None;
    let mut unmute_at = None;
    let mut duree_lisible = "Permanent".to_string();

    if let Some(ref d) = duree {
        let Some(secs) = parse_duration(d) else {
            return deny(ctx, "❌ Format invalide. Exemples : `10m`, `2h`, `1d`").await;
        };
        seconds = Some(secs);
        unmute_at = Some(Utc::now() + ChronoDuration::seconds(secs));
        duree_lisible = format_duration(secs);
    }

    let mute_role = helpers::ensure_mute_role(
        ctx.serenity_context(),
        g.guild_id,
        &ctx.data().config.mute_role_name,
    )
    .await?;

    if helpers::member_has_role(&member, mute_role) {
        return deny(ctx, "❌ Ce membre est déjà muet !").await;
    }

    let reason_log = format!("Mute par {} | {}", ctx.author().name, raison);
    if helpers::add_role_reason(
        ctx.http(),
        g.guild_id,
        member.user.id,
        mute_role,
        &reason_log,
    )
    .await
    .is_err()
    {
        return deny(ctx, "❌ Permission refusée !").await;
    }

    db::add_mute(
        &ctx.data().db,
        g.guild_id.get() as i64,
        member.user.id.get() as i64,
        ctx.author().id.get() as i64,
        &raison,
        unmute_at.map(|d| d.naive_utc()),
    )
    .await?;

    let case_id = db::add_sanction(
        &ctx.data().db,
        g.guild_id.get() as i64,
        member.user.id.get() as i64,
        ctx.author().id.get() as i64,
        "mute",
        Some(&raison),
        duree.as_deref(),
    )
    .await?;

    let mut embed = CreateEmbed::new()
        .title("🔇 Membre Rendu Muet")
        .description(format!("**{}** est maintenant muet.", member.user.name))
        .color(COLOR_WARNING)
        .field("Modérateur", format!("<@{}>", ctx.author().id), true)
        .field("Durée", &duree_lisible, true)
        .field("Raison", &raison, true);
    if let Some(at) = unmute_at {
        embed = embed.field("Unmute le", ts_full(&at), false);
    }
    embed = embed.footer(case_footer(case_id, member.user.id.get()));

    ctx.send(poise::CreateReply::default().embed(embed)).await?;

    // Portage du `bot.loop.create_task(_unmute())` : demute differe en tache
    // detachee. La boucle `check_expired_punishments` sert de filet apres un
    // redemarrage du bot.
    if let Some(secs) = seconds {
        let http = ctx.serenity_context().http.clone();
        let pool = ctx.data().db.clone();
        let guild_id = g.guild_id;
        let target = member.user.id;
        tokio::spawn(async move {
            tokio::time::sleep(std::time::Duration::from_secs(secs.max(0) as u64)).await;
            if let Ok(m) = guild_id.member(&http, target).await {
                if m.roles.contains(&mute_role) {
                    let _ = helpers::remove_role_reason(
                        &http,
                        guild_id,
                        target,
                        mute_role,
                        "Mute temporaire expiré",
                    )
                    .await;
                }
            }
            let _ = db::remove_mute(&pool, guild_id.get() as i64, target.get() as i64).await;
        });
    }

    Ok(())
}

// ── /unmute ──────────────────────────────────────────────────────────────────

/// Retirer le mute d'un membre
#[poise::command(slash_command, guild_only)]
pub async fn unmute(
    ctx: Context<'_>,
    #[description = "Le membre à unmute"] member: Member,
    #[description = "Raison"] raison: Option<String>,
) -> Result<(), Error> {
    let raison = raison.unwrap_or_else(|| NO_REASON.to_string());
    let g = guild_ctx(ctx).await?;

    if !g.author_perms.manage_messages() {
        return deny(ctx, "❌ Permission insuffisante !").await;
    }

    let mute_role = helpers::ensure_mute_role(
        ctx.serenity_context(),
        g.guild_id,
        &ctx.data().config.mute_role_name,
    )
    .await?;

    if !helpers::member_has_role(&member, mute_role) {
        return deny(ctx, "❌ Ce membre n'est pas muet !").await;
    }

    let reason_log = format!("Unmute par {} | {}", ctx.author().name, raison);
    if helpers::remove_role_reason(
        ctx.http(),
        g.guild_id,
        member.user.id,
        mute_role,
        &reason_log,
    )
    .await
    .is_err()
    {
        return deny(ctx, "❌ Permission refusée !").await;
    }

    db::remove_mute(
        &ctx.data().db,
        g.guild_id.get() as i64,
        member.user.id.get() as i64,
    )
    .await?;

    let case_id = db::add_sanction(
        &ctx.data().db,
        g.guild_id.get() as i64,
        member.user.id.get() as i64,
        ctx.author().id.get() as i64,
        "unmute",
        Some(&raison),
        None,
    )
    .await?;

    ctx.send(
        poise::CreateReply::default().embed(
            CreateEmbed::new()
                .title("🔊 Membre Unmute")
                .description(format!("**{}** n'est plus muet.", member.user.name))
                .color(COLOR_SUCCESS)
                .field("Modérateur", format!("<@{}>", ctx.author().id), true)
                .field("Raison", &raison, true)
                .footer(case_footer(case_id, member.user.id.get())),
        ),
    )
    .await?;

    Ok(())
}

// ── /warn ────────────────────────────────────────────────────────────────────

/// Avertir un membre
#[poise::command(slash_command, guild_only)]
pub async fn warn(
    ctx: Context<'_>,
    #[description = "Le membre à avertir"] member: Member,
    #[description = "Raison"] raison: Option<String>,
) -> Result<(), Error> {
    let raison = raison.unwrap_or_else(|| NO_REASON.to_string());
    let g = guild_ctx(ctx).await?;

    if !g.author_perms.manage_messages() {
        return deny(ctx, "❌ Permission insuffisante !").await;
    }

    let gid = g.guild_id.get() as i64;
    let uid = member.user.id.get() as i64;
    let max_warnings = ctx.data().config.max_warnings;

    db::add_warning(&ctx.data().db, gid, uid, ctx.author().id.get() as i64, &raison).await?;
    let case_id = db::add_sanction(
        &ctx.data().db,
        gid,
        uid,
        ctx.author().id.get() as i64,
        "warn",
        Some(&raison),
        None,
    )
    .await?;

    let count = db::get_warnings(&ctx.data().db, gid, uid).await?.len() as i64;

    let mut embed = CreateEmbed::new()
        .title("⚠️ Membre Averti")
        .description(format!("**{}** a été averti.", member.user.name))
        .color(COLOR_WARNING)
        .field("Modérateur", format!("<@{}>", ctx.author().id), true)
        .field("Raison", &raison, true)
        .field("Total", format!("{count}/{max_warnings}"), true);

    if count >= max_warnings {
        let mute_role = helpers::ensure_mute_role(
            ctx.serenity_context(),
            g.guild_id,
            &ctx.data().config.mute_role_name,
        )
        .await?;
        if !helpers::member_has_role(&member, mute_role) {
            let applied = helpers::add_role_reason(
                ctx.http(),
                g.guild_id,
                member.user.id,
                mute_role,
                "Auto-mute : max avertissements atteint",
            )
            .await
            .is_ok();
            if applied {
                embed = embed.field("Action Automatique", "🔇 Auto-mute déclenché", false);
            }
        }
    }

    ctx.send(
        poise::CreateReply::default().embed(embed.footer(case_footer(case_id, member.user.id.get()))),
    )
    .await?;

    let guild_name = ctx
        .partial_guild()
        .await
        .map(|g| g.name.clone())
        .unwrap_or_default();

    helpers::send_dm(
        ctx.serenity_context(),
        member.user.id,
        CreateEmbed::new()
            .title("Vous avez été averti")
            .description(format!("Avertissement dans **{guild_name}**"))
            .color(COLOR_WARNING)
            .field("Raison", &raison, false)
            .field("Avertissements", format!("{count}/{max_warnings}"), false),
    )
    .await;

    Ok(())
}

// ── /warnings ────────────────────────────────────────────────────────────────

/// Voir les avertissements d'un membre
#[poise::command(slash_command, guild_only, rename = "warnings")]
pub async fn warnings_cmd(
    ctx: Context<'_>,
    #[description = "Le membre concerné"] member: Member,
) -> Result<(), Error> {
    let gid = ctx.guild_id().ok_or_else(|| anyhow!("hors guilde"))?.get() as i64;
    let warns = db::get_warnings(&ctx.data().db, gid, member.user.id.get() as i64).await?;

    if warns.is_empty() {
        ctx.send(
            poise::CreateReply::default().embed(
                CreateEmbed::new()
                    .title("✅ Aucun Avertissement")
                    .description(format!(
                        "**{}** n'a aucun avertissement.",
                        member.user.name
                    ))
                    .color(COLOR_SUCCESS)
                    .footer(CreateEmbedFooter::new(format!("ID : {}", member.user.id))),
            ),
        )
        .await?;
        return Ok(());
    }

    let total = warns.len();
    let pages = helpers::build_pages(
        &warns,
        &format!("⚠️ Avertissements de {}", member.user.name),
        COLOR_WARNING,
        5,
        |i, w| {
            (
                format!("Avertissement #{i}"),
                format!(
                    "**Raison :** {}\n**Modérateur :** <@{}>\n**Date :** {}",
                    w.reason, w.moderator_id, w.timestamp
                ),
            )
        },
    );

    let pages: Vec<_> = pages
        .into_iter()
        .map(|p| p.description(format!("Total : **{total}** avertissement(s)")))
        .collect();

    helpers::paginate(ctx, pages).await?;
    Ok(())
}

// ── /clearwarnings ───────────────────────────────────────────────────────────

/// Effacer tous les avertissements d'un membre
#[poise::command(slash_command, guild_only)]
pub async fn clearwarnings(
    ctx: Context<'_>,
    #[description = "Le membre concerné"] member: Member,
) -> Result<(), Error> {
    let g = guild_ctx(ctx).await?;
    if !g.author_perms.manage_messages() {
        return deny(ctx, "❌ Permission insuffisante !").await;
    }

    let gid = g.guild_id.get() as i64;
    let uid = member.user.id.get() as i64;
    let warns = db::get_warnings(&ctx.data().db, gid, uid).await?;

    if warns.is_empty() {
        return deny(
            ctx,
            &format!("❌ **{}** n'a aucun avertissement.", member.user.name),
        )
        .await;
    }

    db::clear_warnings(&ctx.data().db, gid, uid).await?;

    ctx.send(
        poise::CreateReply::default().embed(
            CreateEmbed::new()
                .title("✅ Avertissements Effacés")
                .description(format!(
                    "**{}** avertissement(s) effacé(s) pour **{}**.",
                    warns.len(),
                    member.user.name
                ))
                .color(COLOR_SUCCESS)
                .field("Modérateur", format!("<@{}>", ctx.author().id), false)
                .footer(CreateEmbedFooter::new(format!("ID : {}", member.user.id))),
        ),
    )
    .await?;

    Ok(())
}

// ── /purge ───────────────────────────────────────────────────────────────────

/// Supprimer plusieurs messages d'un coup
#[poise::command(slash_command, guild_only)]
pub async fn purge(
    ctx: Context<'_>,
    #[description = "Nombre de messages (1-100)"] nombre: i64,
    #[description = "Ne supprimer que les messages de ce membre"] membre: Option<Member>,
) -> Result<(), Error> {
    ctx.defer_ephemeral().await?;

    let g = guild_ctx(ctx).await?;
    if !g.author_perms.manage_messages() {
        return deny(ctx, "❌ Permission insuffisante !").await;
    }
    if !(1..=100).contains(&nombre) {
        return deny(ctx, "❌ Le nombre doit être entre 1 et 100 !").await;
    }

    let channel = ctx.channel_id();
    let fetched = channel
        .messages(
            ctx.http(),
            serenity::GetMessages::new().limit(nombre as u8),
        )
        .await?;

    let ids: Vec<_> = fetched
        .iter()
        .filter(|m| match &membre {
            Some(target) => m.author.id == target.user.id,
            None => true,
        })
        .map(|m| m.id)
        .collect();

    if ids.is_empty() {
        ctx.send(
            poise::CreateReply::default()
                .content("🗑️ **0** message(s) supprimé(s).")
                .ephemeral(true),
        )
        .await?;
        return Ok(());
    }

    // `delete_messages` refuse les lots de 1 : on retombe sur une suppression
    // unitaire, comme le fait `TextChannel.purge` en interne.
    // `delete_messages` retombe seul sur `delete_message` pour un lot de 1.
    let deleted = if channel.delete_messages(ctx.http(), &ids).await.is_ok() {
        ids.len()
    } else {
        return deny(ctx, "❌ Permission refusée !").await;
    };

    let mut embed = CreateEmbed::new()
        .title("🗑️ Messages Supprimés")
        .description(format!("**{deleted}** message(s) supprimé(s)."))
        .color(COLOR_SUCCESS)
        .field("Modérateur", format!("<@{}>", ctx.author().id), true);
    if let Some(target) = &membre {
        embed = embed.field("Membre ciblé", format!("<@{}>", target.user.id), true);
    }
    embed = embed.field("Salon", format!("<#{}>", channel.get()), true);

    ctx.send(poise::CreateReply::default().embed(embed).ephemeral(true))
        .await?;

    Ok(())
}

// ── /slowmode ────────────────────────────────────────────────────────────────

/// Activer ou désactiver le mode lent sur un salon
#[poise::command(slash_command, guild_only)]
pub async fn slowmode(
    ctx: Context<'_>,
    #[description = "Délai en secondes (0 = désactiver, max 21600)"] secondes: Option<i64>,
    #[description = "Salon (défaut : actuel)"] salon: Option<serenity::GuildChannel>,
) -> Result<(), Error> {
    let secondes = secondes.unwrap_or(0);
    let g = guild_ctx(ctx).await?;

    if !g.author_perms.manage_channels() {
        return deny(ctx, "❌ Permission insuffisante !").await;
    }
    if !(0..=21600).contains(&secondes) {
        return deny(ctx, "❌ Valeur entre 0 et 21600 secondes.").await;
    }

    let target = salon.map(|c| c.id).unwrap_or_else(|| ctx.channel_id());
    target
        .edit(
            ctx.http(),
            serenity::EditChannel::new().rate_limit_per_user(secondes as u16),
        )
        .await?;

    let embed = if secondes == 0 {
        CreateEmbed::new()
            .title("✅ Mode Lent Désactivé")
            .description(format!("Mode lent désactivé dans <#{}>.", target.get()))
            .color(COLOR_SUCCESS)
    } else {
        CreateEmbed::new()
            .title("🐢 Mode Lent Activé")
            .description(format!("Mode lent activé dans <#{}>.", target.get()))
            .color(COLOR_INFO)
            .field("Délai", format_duration(secondes), false)
    };

    ctx.send(
        poise::CreateReply::default()
            .embed(embed.field("Modérateur", format!("<@{}>", ctx.author().id), false)),
    )
    .await?;

    Ok(())
}
