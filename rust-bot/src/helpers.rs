//! Helpers Discord : rôle Muted, hierarchie, DM, salon mod, audit log,
//! et les deux vues interactives portees depuis `utils/ui.py`.

use std::time::Duration;

use anyhow::{anyhow, Result};
use poise::serenity_prelude as serenity;
use serenity::all::{
    ChannelId, ChannelType, CreateEmbed, CreateMessage, EditRole, GuildId, Member,
    PermissionOverwrite, PermissionOverwriteType, Permissions, RoleId, UserId,
};

use crate::config::COLOR_ERROR;
use crate::data::{Context, Data};

// ── Permissions & hierarchie ─────────────────────────────────────────────────

/// Equivalent de `member.guild_permissions` cote discord.py : permissions de
/// guilde, sans tenir compte des surcharges de salon.
pub fn member_permissions(ctx: &serenity::Context, member: &Member) -> Permissions {
    ctx.cache
        .guild(member.guild_id)
        .map(|g| g.member_permissions(member))
        .unwrap_or_else(Permissions::empty)
}

/// Position du rôle le plus haut — base des comparaisons `top_role >= ...`.
pub fn top_role_position(ctx: &serenity::Context, member: &Member) -> i64 {
    ctx.cache
        .guild(member.guild_id)
        .and_then(|g| g.member_highest_role(member).map(|r| r.position as i64))
        .unwrap_or(0)
}

// ── Actions avec raison d'audit ──────────────────────────────────────────────
//
// `Member::add_role` / `remove_role` et `GuildId::unban` ne transmettent pas de
// raison en serenity 0.12 ; on passe par `Http` pour conserver les entrees
// d'audit produites par la version Python.

pub async fn add_role_reason(
    http: &serenity::Http,
    guild_id: GuildId,
    user_id: UserId,
    role_id: RoleId,
    reason: &str,
) -> serenity::Result<()> {
    http.add_member_role(guild_id, user_id, role_id, Some(reason)).await
}

pub async fn remove_role_reason(
    http: &serenity::Http,
    guild_id: GuildId,
    user_id: UserId,
    role_id: RoleId,
    reason: &str,
) -> serenity::Result<()> {
    http.remove_member_role(guild_id, user_id, role_id, Some(reason)).await
}

pub async fn unban_reason(
    http: &serenity::Http,
    guild_id: GuildId,
    user_id: UserId,
    reason: &str,
) -> serenity::Result<()> {
    http.remove_ban(guild_id, user_id, Some(reason)).await
}

/// Permissions du bot dans la guilde.
pub async fn bot_permissions(
    ctx: &serenity::Context,
    guild_id: GuildId,
) -> Result<Permissions> {
    let bot_id = ctx.cache.current_user().id;
    let me = guild_id.member(ctx, bot_id).await?;
    Ok(member_permissions(ctx, &me))
}

pub async fn bot_top_role_position(ctx: &serenity::Context, guild_id: GuildId) -> Result<i64> {
    let bot_id = ctx.cache.current_user().id;
    let me = guild_id.member(ctx, bot_id).await?;
    Ok(top_role_position(ctx, &me))
}

/// Proprietaire de la guilde (les comparaisons de rôles ne s'y appliquent pas).
pub fn guild_owner_id(ctx: &serenity::Context, guild_id: GuildId) -> Option<UserId> {
    ctx.cache.guild(guild_id).map(|g| g.owner_id)
}

// ── Rôle Muted ───────────────────────────────────────────────────────────────

/// Portage de `ensure_mute_role` : recupere le rôle Muted ou le cree, puis
/// applique les refus de permissions sur chaque salon textuel et vocal.
pub async fn ensure_mute_role(
    ctx: &serenity::Context,
    guild_id: GuildId,
    role_name: &str,
) -> Result<RoleId> {
    if let Some(existing) = ctx
        .cache
        .guild(guild_id)
        .and_then(|g| g.roles.values().find(|r| r.name == role_name).map(|r| r.id))
    {
        return Ok(existing);
    }

    // Repli sur l'API si le cache est froid.
    let roles = guild_id.roles(&ctx.http).await?;
    if let Some(r) = roles.values().find(|r| r.name == role_name) {
        return Ok(r.id);
    }

    let role = guild_id
        .create_role(
            &ctx.http,
            EditRole::new()
                .name(role_name)
                .colour(serenity::Colour::new(0x607d8b))
                .audit_log_reason("Création automatique du rôle Muted"),
        )
        .await?;

    let text_deny = Permissions::SEND_MESSAGES
        | Permissions::ADD_REACTIONS
        | Permissions::SEND_MESSAGES_IN_THREADS
        | Permissions::CREATE_PUBLIC_THREADS
        | Permissions::CREATE_PRIVATE_THREADS;
    let voice_deny = Permissions::SPEAK | Permissions::STREAM | Permissions::USE_VAD;

    for channel in guild_id.channels(&ctx.http).await?.values() {
        let deny = match channel.kind {
            ChannelType::Text | ChannelType::News | ChannelType::Forum => text_deny,
            ChannelType::Voice | ChannelType::Stage => voice_deny,
            _ => continue,
        };
        // `discord.Forbidden -> continue` cote Python.
        let _ = channel
            .id
            .create_permission(
                &ctx.http,
                PermissionOverwrite {
                    allow: Permissions::empty(),
                    deny,
                    kind: PermissionOverwriteType::Role(role.id),
                },
            )
            .await;
    }

    Ok(role.id)
}

pub fn member_has_role(member: &Member, role_id: RoleId) -> bool {
    member.roles.contains(&role_id)
}

// ── Messages prives ──────────────────────────────────────────────────────────

/// Portage de `_send_dm` : les DM fermes (`discord.Forbidden`) sont ignores.
pub async fn send_dm(ctx: &serenity::Context, user_id: UserId, embed: CreateEmbed) {
    if let Ok(channel) = user_id.create_dm_channel(ctx).await {
        let _ = channel
            .send_message(&ctx.http, CreateMessage::new().embed(embed))
            .await;
    }
}

// ── Salon moderateur ─────────────────────────────────────────────────────────

/// Portage de `_mod_channel` / `_get_mod_channel` (index 7 du tuple settings).
pub async fn mod_channel(data: &Data, guild_id: GuildId) -> Option<ChannelId> {
    crate::db::get_guild_settings(&data.db, guild_id.get() as i64)
        .await
        .ok()
        .flatten()
        .and_then(|s| s.mod_channel_id)
        .map(|id| ChannelId::new(id as u64))
}

/// Portage de `EventLogger._log` : envoie dans le salon mod s'il est configure.
pub async fn log_event(
    ctx: &serenity::Context,
    data: &Data,
    guild_id: GuildId,
    embed: CreateEmbed,
    content: Option<&str>,
) {
    let Some(channel) = mod_channel(data, guild_id).await else {
        return;
    };
    let mut msg = CreateMessage::new().embed(embed);
    if let Some(c) = content {
        msg = msg.content(c);
    }
    let _ = channel.send_message(&ctx.http, msg).await;
}

// ── Audit log ────────────────────────────────────────────────────────────────

/// Portage de `_audit` : cherche l'entree d'audit recente correspondant a
/// l'action et, si fourni, a la cible.
pub async fn audit_entry(
    ctx: &serenity::Context,
    guild_id: GuildId,
    action: serenity::audit_log::Action,
    target_id: Option<u64>,
    delay_secs: i64,
) -> Option<serenity::AuditLogEntry> {
    let logs = guild_id
        .audit_logs(&ctx.http, Some(action), None, None, Some(5))
        .await
        .ok()?;

    let now = chrono::Utc::now();
    for entry in logs.entries {
        let created = *entry.id.created_at();
        if (now - created).num_seconds() > delay_secs {
            break;
        }
        match target_id {
            None => return Some(entry),
            Some(tid) if entry.target_id.map(|t| t.get()) == Some(tid) => return Some(entry),
            Some(_) => continue,
        }
    }
    None
}

/// `entry.user.mention` avec repli « Inconnu ».
pub fn audit_user_mention(entry: Option<&serenity::AuditLogEntry>) -> String {
    match entry {
        Some(e) => format!("<@{}>", e.user_id.get()),
        None => "Inconnu".to_string(),
    }
}

pub fn audit_reason(entry: Option<&serenity::AuditLogEntry>, fallback: &str) -> String {
    entry
        .and_then(|e| e.reason.clone())
        .filter(|r| !r.trim().is_empty())
        .unwrap_or_else(|| fallback.to_string())
}

// ── ConfirmView (utils/ui.py) ────────────────────────────────────────────────

/// Portage de `ConfirmView` : envoie l'apercu en ephemere avec deux boutons,
/// attend 30 s, et affiche « Action Annulée » si refus ou expiration.
/// Renvoie `true` uniquement si l'auteur a confirme.
pub async fn confirm_action(ctx: Context<'_>, preview: CreateEmbed) -> Result<bool> {
    let confirm_id = format!("confirm_{}", ctx.id());
    let cancel_id = format!("cancel_{}", ctx.id());

    let components = vec![serenity::CreateActionRow::Buttons(vec![
        serenity::CreateButton::new(&confirm_id)
            .label("✅ Confirmer")
            .style(serenity::ButtonStyle::Danger),
        serenity::CreateButton::new(&cancel_id)
            .label("❌ Annuler")
            .style(serenity::ButtonStyle::Secondary),
    ])];

    let reply = ctx
        .send(
            poise::CreateReply::default()
                .embed(preview)
                .components(components)
                .ephemeral(true),
        )
        .await?;

    let confirmed = match serenity::ComponentInteractionCollector::new(ctx.serenity_context())
        .author_id(ctx.author().id)
        .timeout(Duration::from_secs(30))
        .filter({
            let confirm_id = confirm_id.clone();
            let cancel_id = cancel_id.clone();
            move |i| i.data.custom_id == confirm_id || i.data.custom_id == cancel_id
        })
        .await
    {
        Some(interaction) => {
            // `_disable_all()` + `edit_message(view=self)` cote Python.
            interaction
                .create_response(
                    ctx.http(),
                    serenity::CreateInteractionResponse::UpdateMessage(
                        serenity::CreateInteractionResponseMessage::new().components(vec![]),
                    ),
                )
                .await?;
            interaction.data.custom_id == confirm_id
        }
        None => false,
    };

    if !confirmed {
        reply
            .edit(
                ctx,
                poise::CreateReply::default()
                    .embed(crate::util::simple_embed("❌ Action Annulée", COLOR_ERROR))
                    .components(vec![]),
            )
            .await?;
    }

    Ok(confirmed)
}

// ── PaginationView (utils/ui.py) ─────────────────────────────────────────────

/// Portage de `build_pages` : decoupe `entries` en pages de `per_page` champs.
/// Au moins une page est produite, meme si la liste est vide.
pub fn build_pages<T>(
    entries: &[T],
    title: &str,
    color: u32,
    per_page: usize,
    formatter: impl Fn(usize, &T) -> (String, String),
) -> Vec<CreateEmbed> {
    let mut pages = Vec::new();
    let total = entries.len().max(1);
    let mut start = 0;
    while start < total {
        let chunk = entries.get(start..(start + per_page).min(entries.len()));
        let mut embed = CreateEmbed::new().title(title).color(color);
        if let Some(chunk) = chunk {
            for (offset, entry) in chunk.iter().enumerate() {
                let (name, value) = formatter(start + offset + 1, entry);
                embed = embed.field(name, value, false);
            }
        }
        pages.push(embed);
        start += per_page;
    }
    pages
}

/// Portage de `PaginationView` : boutons Précédent/Suivant, 120 s de timeout,
/// reserves a l'auteur (les autres reçoivent un refus ephemere).
pub async fn paginate(ctx: Context<'_>, pages: Vec<CreateEmbed>) -> Result<()> {
    if pages.is_empty() {
        return Err(anyhow!("aucune page à afficher"));
    }

    let total = pages.len();
    let footer = |i: usize| serenity::CreateEmbedFooter::new(format!("Page {}/{}", i + 1, total));

    if total == 1 {
        ctx.send(poise::CreateReply::default().embed(pages[0].clone().footer(footer(0))))
            .await?;
        return Ok(());
    }

    let prev_id = format!("prev_{}", ctx.id());
    let next_id = format!("next_{}", ctx.id());

    let row = |current: usize| {
        serenity::CreateActionRow::Buttons(vec![
            serenity::CreateButton::new(&prev_id)
                .label("◀ Précédent")
                .style(serenity::ButtonStyle::Secondary)
                .disabled(current == 0),
            serenity::CreateButton::new(&next_id)
                .label("Suivant ▶")
                .style(serenity::ButtonStyle::Secondary)
                .disabled(current + 1 >= total),
        ])
    };

    let mut current = 0usize;
    let reply = ctx
        .send(
            poise::CreateReply::default()
                .embed(pages[0].clone().footer(footer(0)))
                .components(vec![row(0)]),
        )
        .await?;

    let message_id = reply.message().await?.id;

    while let Some(interaction) =
        serenity::ComponentInteractionCollector::new(ctx.serenity_context())
            .message_id(message_id)
            .timeout(Duration::from_secs(120))
            .filter({
                let prev_id = prev_id.clone();
                let next_id = next_id.clone();
                move |i| i.data.custom_id == prev_id || i.data.custom_id == next_id
            })
            .await
    {
        // `interaction_check` : seul l'auteur pilote la pagination.
        if interaction.user.id != ctx.author().id {
            let _ = interaction
                .create_response(
                    ctx.http(),
                    serenity::CreateInteractionResponse::Message(
                        serenity::CreateInteractionResponseMessage::new()
                            .content("❌ Vous ne pouvez pas utiliser ces boutons.")
                            .ephemeral(true),
                    ),
                )
                .await;
            continue;
        }

        if interaction.data.custom_id == prev_id {
            current = current.saturating_sub(1);
        } else {
            current = (current + 1).min(total - 1);
        }

        interaction
            .create_response(
                ctx.http(),
                serenity::CreateInteractionResponse::UpdateMessage(
                    serenity::CreateInteractionResponseMessage::new()
                        .embed(pages[current].clone().footer(footer(current)))
                        .components(vec![row(current)]),
                ),
            )
            .await?;
    }

    // `on_timeout` : desactive les boutons.
    let _ = reply
        .edit(
            ctx,
            poise::CreateReply::default()
                .embed(pages[current].clone().footer(footer(current)))
                .components(vec![]),
        )
        .await;

    Ok(())
}
