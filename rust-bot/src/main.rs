//! Bot de moderation Discord — portage Rust de `DiscordCompanion` (Python).
//!
//! Point d'entree : charge `.env`, initialise la base, monte le framework
//! poise puis lance le client serenity dans une boucle de reconnexion
//! equivalente au `while True` de `main.py`.

mod commands;
mod config;
mod data;
mod db;
mod events;
mod helpers;
mod keepalive;
mod util;

use std::time::Duration;

use anyhow::{Context as _, Result};
use poise::serenity_prelude as serenity;

use crate::config::Config;
use crate::data::{Data, Error};

#[tokio::main]
async fn main() -> Result<()> {
    dotenvy::dotenv().ok();

    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info,serenity=warn,tracing::span=warn".into()),
        )
        .init();

    let config = Config::from_env();

    if config.discord_token.is_empty() {
        tracing::error!("DISCORD_TOKEN not found in environment variables!");
        return Ok(());
    }

    // `keep_alive()` avant la boucle de connexion, comme dans `main.py`.
    keepalive::keep_alive(keepalive::now_epoch());

    let pool = db::connect(&config.database_path)
        .await
        .context("ouverture de la base SQLite")?;
    db::init_db(&pool).await.context("initialisation du schéma")?;

    let intents = serenity::GatewayIntents::non_privileged()
        | serenity::GatewayIntents::MESSAGE_CONTENT
        | serenity::GatewayIntents::GUILD_MEMBERS;

    // Boucle de reconnexion : serenity gere deja les coupures de gateway ; ce
    // niveau supplementaire couvre les erreurs fatales du client, comme le
    // `while True` de `main.py`.
    loop {
        let framework = poise::Framework::builder()
            .options(poise::FrameworkOptions {
                commands: commands::all(),
                prefix_options: poise::PrefixFrameworkOptions {
                    prefix: Some("!".into()),
                    case_insensitive_commands: true,
                    ..Default::default()
                },
                event_handler: |ctx, event, framework, data| {
                    Box::pin(events::handler(ctx, event, framework, data))
                },
                on_error: |error| Box::pin(on_error(error)),
                ..Default::default()
            })
            .setup({
                let pool = pool.clone();
                let config = config.clone();
                move |ctx, _ready, framework| {
                    Box::pin(async move {
                        match poise::builtins::register_globally(ctx, &framework.options().commands)
                            .await
                        {
                            Ok(()) => tracing::info!(
                                "Synced {} slash commands",
                                framework.options().commands.len()
                            ),
                            Err(e) => tracing::error!("Failed to sync commands: {e}"),
                        }

                        events::tasks::spawn_expiry_loop(
                            ctx.clone(),
                            pool.clone(),
                            config.mute_role_name.clone(),
                        );

                        Ok(Data::new(pool, config))
                    })
                }
            })
            .build();

        // Le cache de messages doit etre actif : `on_message_delete` ne reçoit
        // qu'un identifiant depuis la gateway.
        let mut cache_settings = serenity::cache::Settings::default();
        cache_settings.max_messages = 1000;

        let client = serenity::ClientBuilder::new(&config.discord_token, intents)
            .framework(framework)
            .cache_settings(cache_settings)
            .await;

        match client {
            Ok(mut client) => {
                if let Err(err) = client.start().await {
                    tracing::error!("Unexpected error: {err}");
                    tracing::info!("Reconnecting in 10 seconds...");
                    tokio::time::sleep(Duration::from_secs(10)).await;
                } else {
                    // Arret propre demande.
                    break;
                }
            }
            Err(err) => {
                tracing::error!("Invalid token provided or client build failed: {err}");
                break;
            }
        }
    }

    Ok(())
}

/// Portage de `on_command_error` : messages francais pour les erreurs
/// courantes, log brut pour le reste.
async fn on_error(error: poise::FrameworkError<'_, Data, Error>) {
    use poise::FrameworkError as FE;

    match error {
        FE::MissingUserPermissions { ctx, .. } => {
            let _ = ctx.say("❌ Ta pas les perms chef.").await;
        }
        FE::MissingBotPermissions { ctx, .. } => {
            let _ = ctx.say("❌ J'ai pas les perms chef.").await;
        }
        FE::CooldownHit {
            remaining_cooldown,
            ctx,
            ..
        } => {
            let _ = ctx
                .say(format!(
                    "⏰ Cette commande est en cooldown. Réessayez dans {:.1} secondes.",
                    remaining_cooldown.as_secs_f32()
                ))
                .await;
        }
        FE::ArgumentParse { error, ctx, .. } => {
            tracing::warn!("Argument parse error: {error}");
            let _ = ctx.say("❌ membre introuvable.").await;
        }
        other => {
            if let Err(e) = poise::builtins::on_error(other).await {
                tracing::error!("Unexpected error: {e}");
            }
        }
    }
}
