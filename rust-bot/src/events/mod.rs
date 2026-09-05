//! Dispatcher d'evenements : route chaque `FullEvent` vers les portages des
//! listeners Python.

pub mod automod;
pub mod autorole;
pub mod logging;
pub mod tasks;

use poise::serenity_prelude as serenity;
use serenity::all::FullEvent;

use crate::data::{Data, Error};

pub async fn handler(
    ctx: &serenity::Context,
    event: &FullEvent,
    _framework: poise::FrameworkContext<'_, Data, Error>,
    data: &Data,
) -> Result<(), Error> {
    match event {
        // ── Cycle de vie ─────────────────────────────────────────────────────
        FullEvent::Ready { data_about_bot } => {
            tracing::info!("{} is now online!", data_about_bot.user.name);
            tracing::info!("Bot is in {} guilds", data_about_bot.guilds.len());
            ctx.set_activity(Some(serenity::ActivityData::watching(
                "les violations de règles",
            )));
        }

        FullEvent::Resume { .. } => {
            tracing::info!("Bot reconnected to Discord successfully");
        }

        // Amorce les instantanes emojis/stickers pour pouvoir calculer un diff
        // au premier `GuildEmojisUpdate`.
        FullEvent::GuildCreate { guild, .. } => {
            data.emoji_snapshot.insert(
                guild.id.get(),
                guild
                    .emojis
                    .values()
                    .map(|e| (e.id.get(), e.name.to_string()))
                    .collect(),
            );
            data.sticker_snapshot.insert(
                guild.id.get(),
                guild
                    .stickers
                    .values()
                    .map(|s| (s.id.get(), s.name.to_string()))
                    .collect(),
            );
        }

        // ── Messages ─────────────────────────────────────────────────────────
        FullEvent::Message { new_message } => {
            automod::on_message(ctx, data, new_message).await?;
        }

        // `AutoMod.on_message_edit` : rejoue les filtres si le contenu change.
        FullEvent::MessageUpdate {
            old_if_available,
            new,
            ..
        } => {
            if let Some(after) = new {
                let changed = old_if_available
                    .as_ref()
                    .map(|before| before.content != after.content)
                    .unwrap_or(true);
                if changed {
                    automod::on_message(ctx, data, after).await?;
                }
            }
        }

        FullEvent::MessageDelete {
            channel_id,
            deleted_message_id,
            guild_id,
        } => {
            let Some(guild_id) = guild_id else {
                return Ok(());
            };
            // Le contenu ne vient pas de la gateway : il faut qu'il soit
            // encore dans le cache de messages (`max_messages` cote client).
            if let Some(message) = ctx.cache.message(*channel_id, *deleted_message_id).map(|m| m.clone()) {
                logging::on_message_delete(ctx, data, *guild_id, &message).await?;
            }
        }

        FullEvent::MessageDeleteBulk {
            channel_id,
            multiple_deleted_messages_ids,
            guild_id,
        } => {
            if let Some(guild_id) = guild_id {
                logging::on_bulk_message_delete(
                    ctx,
                    data,
                    *guild_id,
                    *channel_id,
                    multiple_deleted_messages_ids,
                )
                .await?;
            }
        }

        // ── Membres ──────────────────────────────────────────────────────────
        // Les deux cogs Python ecoutaient `on_member_join` : on conserve les
        // deux comportements, dans l'ordre de chargement des cogs.
        FullEvent::GuildMemberAddition { new_member } => {
            logging::on_member_join(ctx, data, new_member).await?;
            autorole::on_member_join(ctx, data, new_member).await?;
        }

        FullEvent::GuildMemberRemoval {
            guild_id,
            user,
            member_data_if_available,
        } => {
            logging::on_member_remove(
                ctx,
                data,
                *guild_id,
                user,
                member_data_if_available.as_ref(),
            )
            .await?;
        }

        FullEvent::GuildMemberUpdate {
            old_if_available,
            new,
            ..
        } => {
            if let Some(after) = new {
                logging::on_member_update(ctx, data, old_if_available.as_ref(), after).await?;
            }
        }

        FullEvent::GuildBanAddition {
            guild_id,
            banned_user,
        } => {
            logging::on_member_ban(ctx, data, *guild_id, banned_user).await?;
        }

        FullEvent::GuildBanRemoval {
            guild_id,
            unbanned_user,
        } => {
            logging::on_member_unban(ctx, data, *guild_id, unbanned_user).await?;
        }

        // ── Vocal ────────────────────────────────────────────────────────────
        FullEvent::VoiceStateUpdate { old, new } => {
            logging::on_voice_state_update(ctx, data, old.as_ref(), new).await?;
        }

        // ── Salons ───────────────────────────────────────────────────────────
        FullEvent::ChannelCreate { channel } => {
            logging::on_channel_create(ctx, data, channel).await?;
        }

        FullEvent::ChannelDelete { channel, .. } => {
            logging::on_channel_delete(ctx, data, channel).await?;
        }

        FullEvent::ChannelUpdate { old, new } => {
            logging::on_channel_update(ctx, data, old.as_ref(), new).await?;
        }

        // ── Rôles ────────────────────────────────────────────────────────────
        FullEvent::GuildRoleCreate { new } => {
            logging::on_role_create(ctx, data, new).await?;
        }

        FullEvent::GuildRoleDelete {
            guild_id,
            removed_role_id,
            removed_role_data_if_available,
        } => {
            logging::on_role_delete(
                ctx,
                data,
                *guild_id,
                *removed_role_id,
                removed_role_data_if_available.as_ref(),
            )
            .await?;
        }

        FullEvent::GuildRoleUpdate {
            old_data_if_available,
            new,
        } => {
            logging::on_role_update(ctx, data, old_data_if_available.as_ref(), new).await?;
        }

        // ── Serveur ──────────────────────────────────────────────────────────
        FullEvent::GuildUpdate {
            old_data_if_available,
            new_data,
        } => {
            logging::on_guild_update(ctx, data, old_data_if_available.as_ref(), new_data).await?;
        }

        // ── Invitations ──────────────────────────────────────────────────────
        FullEvent::InviteCreate { data: event } => {
            logging::on_invite_create(ctx, data, event).await?;
        }

        FullEvent::InviteDelete { data: event } => {
            logging::on_invite_delete(ctx, data, event).await?;
        }

        // ── Emojis / stickers ────────────────────────────────────────────────
        FullEvent::GuildEmojisUpdate {
            guild_id,
            current_state,
        } => {
            let current = current_state
                .values()
                .map(|e| (e.id.get(), e.name.to_string()))
                .collect();
            logging::on_emojis_update(ctx, data, *guild_id, current).await?;
        }

        FullEvent::GuildStickersUpdate {
            guild_id,
            current_state,
        } => {
            let current = current_state
                .values()
                .map(|s| (s.id.get(), s.name.to_string()))
                .collect();
            logging::on_stickers_update(ctx, data, *guild_id, current).await?;
        }

        // ── Threads ──────────────────────────────────────────────────────────
        FullEvent::ThreadCreate { thread } => {
            logging::on_thread_create(ctx, data, thread).await?;
        }

        FullEvent::ThreadDelete {
            thread,
            full_thread_data,
        } => {
            logging::on_thread_delete(
                ctx,
                data,
                thread.guild_id,
                thread.id,
                full_thread_data.as_ref().map(|t| t.name.as_str()),
            )
            .await?;
        }

        // ── Composants persistants (`ShabView`) ──────────────────────────────
        FullEvent::InteractionCreate { interaction } => {
            if let Some(component) = interaction.as_message_component() {
                autorole::handle_component(ctx, component).await?;
            }
        }

        _ => {}
    }

    Ok(())
}
