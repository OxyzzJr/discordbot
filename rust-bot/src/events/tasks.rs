//! Tache periodique (portage de `Moderation.check_expired_punishments`).

use std::time::Duration;

use poise::serenity_prelude as serenity;
use serenity::all::GuildId;
use sqlx::SqlitePool;

use crate::db;
use crate::helpers;

/// Boucle d'une minute : leve les tempbans et les mutes arrives a echeance.
/// Complète les `tokio::spawn` poses lors des sanctions, qui ne survivent pas
/// a un redemarrage du bot.
pub fn spawn_expiry_loop(ctx: serenity::Context, pool: SqlitePool, mute_role_name: String) {
    tokio::spawn(async move {
        let mut ticker = tokio::time::interval(Duration::from_secs(60));
        loop {
            ticker.tick().await;
            if let Err(err) = run_once(&ctx, &pool, &mute_role_name).await {
                tracing::warn!("check_expired_punishments: {err}");
            }
        }
    });
}

async fn run_once(
    ctx: &serenity::Context,
    pool: &SqlitePool,
    mute_role_name: &str,
) -> anyhow::Result<()> {
    let now = chrono::Utc::now().naive_utc();

    // ── Tempbans expires ──
    for (guild_id, user_id, unban_at) in db::get_active_tempbans(pool).await? {
        if now < unban_at {
            continue;
        }
        let gid = GuildId::new(guild_id as u64);
        if ctx.cache.guild(gid).is_some() {
            let _ = helpers::unban_reason(
                &ctx.http,
                gid,
                serenity::UserId::new(user_id as u64),
                "Tempban expiré automatiquement",
            )
            .await;
        }
        db::deactivate_tempban(pool, guild_id, user_id).await?;
    }

    // ── Mutes temporaires expires ──
    // Le rôle est resolu une seule fois par guilde, comme le dict `_mute_roles`.
    let mut mute_roles: std::collections::HashMap<i64, serenity::RoleId> = Default::default();

    for (guild_id, user_id, unmute_at) in db::get_active_timed_mutes(pool).await? {
        if now < unmute_at {
            continue;
        }
        let gid = GuildId::new(guild_id as u64);

        if ctx.cache.guild(gid).is_some() {
            if let Ok(member) = gid.member(ctx, serenity::UserId::new(user_id as u64)).await {
                let role = match mute_roles.get(&guild_id) {
                    Some(r) => Some(*r),
                    None => {
                        match helpers::ensure_mute_role(ctx, gid, mute_role_name).await
                        {
                            Ok(r) => {
                                mute_roles.insert(guild_id, r);
                                Some(r)
                            }
                            Err(_) => None,
                        }
                    }
                };

                if let Some(role) = role {
                    if member.roles.contains(&role) {
                        let _ = helpers::remove_role_reason(
                            &ctx.http,
                            gid,
                            member.user.id,
                            role,
                            "Mute temporaire expiré",
                        )
                        .await;
                    }
                }
            }
        }

        db::remove_mute(pool, guild_id, user_id).await?;
    }

    Ok(())
}
