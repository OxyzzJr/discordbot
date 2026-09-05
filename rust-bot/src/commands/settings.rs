//! Commandes de configuration (portage de `setregles` / `setwelcome` de
//! `cogs/moderation.py`, `setmodchannel` + `autorole_create_soumises` de
//! `cogs/autorole.py`, et `setlogchannel` de `cogs/logging.py`).

use anyhow::anyhow;
use poise::serenity_prelude as serenity;
use serenity::all::{CreateEmbed, CreateMessage, EditRole, GuildChannel};

use crate::commands::moderation::{deny, guild_ctx};
use crate::config::{COLOR_INFO, COLOR_SUCCESS};
use crate::data::{Context, Error};
use crate::db::{self, GuildSettingsPatch};
use crate::events::autorole::ROLE_SOUMISES;
use crate::util::truncate;

// ── /setregles ───────────────────────────────────────────────────────────────

/// Définir les règles du serveur
#[poise::command(slash_command, guild_only)]
pub async fn setregles(
    ctx: Context<'_>,
    #[description = "Texte des règles (markdown supporté)"] texte: String,
) -> Result<(), Error> {
    let g = guild_ctx(ctx).await?;
    if !g.author_perms.administrator() {
        return deny(ctx, "❌ Administrateur requis !").await;
    }

    db::update_guild_settings(
        &ctx.data().db,
        g.guild_id.get() as i64,
        GuildSettingsPatch {
            rules_text: Some(Some(texte.clone())),
            ..Default::default()
        },
    )
    .await?;

    ctx.send(
        poise::CreateReply::default().embed(
            CreateEmbed::new()
                .title("✅ Règles Mises à Jour")
                .color(COLOR_SUCCESS)
                .field("Aperçu", truncate(&texte, 500), false),
        ),
    )
    .await?;

    Ok(())
}

// ── /setwelcome ──────────────────────────────────────────────────────────────

/// Configurer le message de bienvenue
#[poise::command(slash_command, guild_only)]
pub async fn setwelcome(
    ctx: Context<'_>,
    #[description = "Salon de bienvenue"] salon: GuildChannel,
    #[description = "Message ({mention}, {server}, {count})"] message: Option<String>,
) -> Result<(), Error> {
    let g = guild_ctx(ctx).await?;
    if !g.author_perms.administrator() {
        return deny(ctx, "❌ Administrateur requis !").await;
    }

    db::update_guild_settings(
        &ctx.data().db,
        g.guild_id.get() as i64,
        GuildSettingsPatch {
            welcome_channel_id: Some(Some(salon.id.get() as i64)),
            welcome_message: Some(message.clone()),
            ..Default::default()
        },
    )
    .await?;

    ctx.send(
        poise::CreateReply::default().embed(
            CreateEmbed::new()
                .title("✅ Message de Bienvenue Configuré")
                .color(COLOR_SUCCESS)
                .field("Salon", format!("<#{}>", salon.id), false)
                .field(
                    "Message",
                    message.unwrap_or_else(|| {
                        "*(Par défaut)* Bienvenue sur **{server}**, {mention} ! 🎉".to_string()
                    }),
                    false,
                )
                .field("Variables", "`{mention}` `{server}` `{count}`", false),
        ),
    )
    .await?;

    Ok(())
}

// ── /setmodchannel ───────────────────────────────────────────────────────────

/// Définir le salon modérateur où arrivent les vérifications de nouveaux membres
#[poise::command(slash_command, guild_only)]
pub async fn setmodchannel(
    ctx: Context<'_>,
    #[description = "Le salon modérateur (accès réservé au staff)"] channel: GuildChannel,
) -> Result<(), Error> {
    let g = guild_ctx(ctx).await?;
    if !g.author_perms.administrator() {
        return deny(
            ctx,
            "❌ Tu dois être administrateur pour configurer ce salon.",
        )
        .await;
    }

    db::update_guild_settings(
        &ctx.data().db,
        g.guild_id.get() as i64,
        GuildSettingsPatch {
            mod_channel_id: Some(Some(channel.id.get() as i64)),
            ..Default::default()
        },
    )
    .await?;

    ctx.send(
        poise::CreateReply::default()
            .embed(
                CreateEmbed::new()
                    .title("✅ Salon modérateur défini")
                    .description(format!(
                        "Les vérifications de nouveaux membres seront envoyées dans <#{}>.",
                        channel.id
                    ))
                    .color(COLOR_SUCCESS),
            )
            .ephemeral(true),
    )
    .await?;

    // Message de confirmation poste dans le salon cible.
    let _ = channel
        .id
        .send_message(
            ctx.http(),
            CreateMessage::new().embed(
                CreateEmbed::new()
                    .title("🔒 Salon modérateur actif")
                    .description(
                        "Ce salon recevra désormais les alertes de vérification \
                         des nouveaux membres.",
                    )
                    .color(COLOR_INFO)
                    .timestamp(serenity::Timestamp::now())
                    .field("Configuré par", format!("<@{}>", ctx.author().id), false),
            ),
        )
        .await;

    Ok(())
}

// ── /setlogchannel ───────────────────────────────────────────────────────────

/// (Obsolète) Utilise /setmodchannel — définit le salon de logs
#[poise::command(slash_command, guild_only)]
pub async fn setlogchannel(
    ctx: Context<'_>,
    #[description = "Le salon à utiliser pour les logs"] channel: GuildChannel,
) -> Result<(), Error> {
    let g = guild_ctx(ctx).await?;
    if !g.author_perms.administrator() {
        return deny(ctx, "❌ Tu dois être administrateur.").await;
    }

    // Alias historique : ecrit bien `mod_channel_id`, comme la version Python.
    db::update_guild_settings(
        &ctx.data().db,
        g.guild_id.get() as i64,
        GuildSettingsPatch {
            mod_channel_id: Some(Some(channel.id.get() as i64)),
            ..Default::default()
        },
    )
    .await?;

    ctx.send(
        poise::CreateReply::default()
            .embed(
                CreateEmbed::new()
                    .title("✅  Salon de Logs Défini")
                    .description(format!(
                        "Tous les logs seront envoyés dans <#{}>.\n\
                         *(Équivalent à `/setmodchannel`)*",
                        channel.id
                    ))
                    .color(COLOR_SUCCESS),
            )
            .ephemeral(true),
    )
    .await?;

    Ok(())
}

// ── /autorole_create_soumises ────────────────────────────────────────────────

/// Crée le rôle 'soumises' s'il n'existe pas encore
#[poise::command(slash_command, guild_only)]
pub async fn autorole_create_soumises(ctx: Context<'_>) -> Result<(), Error> {
    let g = guild_ctx(ctx).await?;
    if !g.author_perms.manage_roles() {
        return deny(ctx, "❌ Tu n'as pas la permission de gérer les rôles.").await;
    }

    let guild_id = ctx.guild_id().ok_or_else(|| anyhow!("hors guilde"))?;
    let existing = guild_id
        .roles(ctx.http())
        .await?
        .into_values()
        .find(|r| r.name == ROLE_SOUMISES);

    if existing.is_some() {
        ctx.send(
            poise::CreateReply::default()
                .content(format!("✅ Le rôle **{ROLE_SOUMISES}** existe déjà."))
                .ephemeral(true),
        )
        .await?;
        return Ok(());
    }

    let reason = format!(
        "Créé par {} via /autorole_create_soumises",
        ctx.author().name
    );
    match guild_id
        .create_role(
            ctx.http(),
            EditRole::new().name(ROLE_SOUMISES).audit_log_reason(&reason),
        )
        .await
    {
        Ok(role) => {
            ctx.send(
                poise::CreateReply::default()
                    .content(format!("✅ Rôle **{}** créé avec succès.", role.name))
                    .ephemeral(true),
            )
            .await?;
        }
        Err(_) => {
            deny(ctx, "❌ Je n'ai pas la permission de créer des rôles.").await?;
        }
    }

    Ok(())
}
