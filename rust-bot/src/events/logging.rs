//! Journalisation des evenements de serveur (portage de `cogs/logging.py`).

use poise::serenity_prelude as serenity;
use serenity::all::{
    audit_log::Action, ChannelType, CreateEmbed, CreateEmbedFooter, CreateMessage, GuildChannel,
    GuildId, Member, Message, MessageId, PartialGuild, Role, User, VoiceState,
};

use crate::data::{Data, Error};
use crate::helpers::{audit_entry, audit_reason, audit_user_mention, log_event};
use crate::util::{non_empty, truncate, ts_relative};

// Palette de `cogs/logging.py`.
pub const C_JOIN: u32 = 0x57F287;
pub const C_LEAVE: u32 = 0xED4245;
pub const C_BAN: u32 = 0xED4245;
pub const C_UNBAN: u32 = 0xFEE75C;
pub const C_VOICE: u32 = 0x5865F2;
pub const C_WARN: u32 = 0xFFA500;
pub const C_DELETE: u32 = 0xFFA500;
pub const C_EDIT: u32 = 0xFEE75C;
pub const C_ROLE: u32 = 0xEB459E;
pub const C_CHANNEL: u32 = 0x57F287;
pub const C_SERVER: u32 = 0x5865F2;
pub const C_TIMEOUT: u32 = 0xED4245;
pub const C_INFO: u32 = 0x5865F2;

fn footer_id(id: impl std::fmt::Display) -> CreateEmbedFooter {
    CreateEmbedFooter::new(format!("ID : {id}"))
}

fn now() -> serenity::Timestamp {
    serenity::Timestamp::now()
}

// ── on_member_join ───────────────────────────────────────────────────────────

/// Portage de `EventLogger.on_member_join` : rôle « Membre », message de
/// bienvenue, puis log d'arrivee avec ping `@here`.
pub async fn on_member_join(
    ctx: &serenity::Context,
    data: &Data,
    member: &Member,
) -> Result<(), Error> {
    let guild_id = member.guild_id;

    // Auto-attribution du rôle « Membre » s'il existe.
    let membre_role = ctx
        .cache
        .guild(guild_id)
        .and_then(|g| g.roles.values().find(|r| r.name == "Membre").map(|r| r.id));
    if let Some(role) = membre_role {
        let _ = crate::helpers::add_role_reason(
            &ctx.http,
            guild_id,
            member.user.id,
            role,
            "Auto-attribution rôle Membre",
        )
        .await;
    }

    let settings = crate::db::get_guild_settings(&data.db, guild_id.get() as i64).await?;

    let (member_count, guild_name) = {
        let g = ctx.cache.guild(guild_id);
        (
            g.as_ref().map(|g| g.member_count).unwrap_or(0),
            g.map(|g| g.name.to_string()).unwrap_or_default(),
        )
    };

    if let Some(s) = &settings {
        if let Some(channel_id) = s.welcome_channel_id {
            let channel = serenity::ChannelId::new(channel_id as u64);
            let msg = s
                .welcome_message
                .clone()
                .unwrap_or_else(|| "Bienvenue sur **{server}**, {mention} ! 🎉".to_string())
                .replace("{mention}", &format!("<@{}>", member.user.id))
                .replace("{server}", &guild_name)
                .replace("{count}", &member_count.to_string());

            let _ = channel
                .send_message(
                    &ctx.http,
                    CreateMessage::new().embed(
                        CreateEmbed::new()
                            .title("👋 Bienvenue !")
                            .description(msg)
                            .color(C_JOIN)
                            .timestamp(now())
                            .thumbnail(member.face()),
                    ),
                )
                .await;
        }
    }

    let age_days = (chrono::Utc::now() - *member.user.created_at()).num_days();

    let mut embed = CreateEmbed::new()
        .title("📥  Nouveau Membre")
        .description(format!(
            "<@{}> vient de rejoindre le serveur.",
            member.user.id
        ))
        .color(C_JOIN)
        .timestamp(now())
        .thumbnail(member.face())
        .field(
            "👤 Utilisateur",
            format!("`{}` — ID `{}`", member.user.name, member.user.id),
            false,
        )
        .field(
            "📅 Compte créé",
            ts_relative(Some(&member.user.created_at())),
            true,
        )
        .field("👥 Membre nº", format!("`{member_count}`"), true);

    if age_days < 7 {
        embed = embed.field(
            "⚠️  Compte récent !",
            format!(
                "Ce compte n'a que **{age_days} jour{}**.",
                if age_days != 1 { "s" } else { "" }
            ),
            false,
        );
    }

    log_event(
        ctx,
        data,
        guild_id,
        embed.footer(footer_id(member.user.id)),
        Some("@here"),
    )
    .await;

    Ok(())
}

// ── on_member_remove ─────────────────────────────────────────────────────────

pub async fn on_member_remove(
    ctx: &serenity::Context,
    data: &Data,
    guild_id: GuildId,
    user: &User,
    member: Option<&Member>,
) -> Result<(), Error> {
    let entry = audit_entry(ctx, guild_id, Action::Member(serenity::MemberAction::Kick), Some(user.id.get()), 10).await;

    let mut embed = if entry.is_some() {
        CreateEmbed::new()
            .title("👢  Membre Expulsé (Kick)")
            .description(format!("<@{}> a été expulsé.", user.id))
            .color(C_BAN)
            .timestamp(now())
            .field(
                "👤 Utilisateur",
                format!("`{}` — ID `{}`", user.name, user.id),
                false,
            )
            .field("🛡️ Modérateur", audit_user_mention(entry.as_ref()), true)
            .field(
                "📋 Raison",
                audit_reason(entry.as_ref(), "Aucune raison"),
                true,
            )
    } else {
        let member_count = ctx.cache.guild(guild_id).map(|g| g.member_count).unwrap_or(0);
        let mut e = CreateEmbed::new()
            .title("📤  Membre Parti")
            .description(format!("<@{}> a quitté le serveur.", user.id))
            .color(C_LEAVE)
            .timestamp(now())
            .field(
                "👤 Utilisateur",
                format!("`{}` — ID `{}`", user.name, user.id),
                false,
            )
            .field(
                "📅 Arrivé",
                ts_relative(member.and_then(|m| m.joined_at.as_deref())),
                true,
            )
            .field("👥 Membres", format!("`{member_count}`"), true);

        if let Some(m) = member {
            let roles: Vec<String> = m.roles.iter().map(|r| format!("<@&{r}>")).collect();
            if !roles.is_empty() {
                e = e.field("🏷️ Rôles", truncate(&roles.join(" "), 1024), false);
            }
        }
        e
    };

    embed = embed.thumbnail(user.face()).footer(footer_id(user.id));
    log_event(ctx, data, guild_id, embed, None).await;
    Ok(())
}

// ── on_member_ban / on_member_unban ──────────────────────────────────────────

pub async fn on_member_ban(
    ctx: &serenity::Context,
    data: &Data,
    guild_id: GuildId,
    user: &User,
) -> Result<(), Error> {
    let entry = audit_entry(ctx, guild_id, Action::Member(serenity::MemberAction::BanAdd), Some(user.id.get()), 10).await;

    let embed = CreateEmbed::new()
        .title("🔨  Membre Banni")
        .description(format!("<@{}> a été banni du serveur.", user.id))
        .color(C_BAN)
        .timestamp(now())
        .thumbnail(user.face())
        .field(
            "👤 Utilisateur",
            format!("`{}` — ID `{}`", user.name, user.id),
            false,
        )
        .field("🛡️ Modérateur", audit_user_mention(entry.as_ref()), true)
        .field("📋 Raison", audit_reason(entry.as_ref(), "Aucune"), true)
        .footer(footer_id(user.id));

    log_event(ctx, data, guild_id, embed, None).await;
    Ok(())
}

pub async fn on_member_unban(
    ctx: &serenity::Context,
    data: &Data,
    guild_id: GuildId,
    user: &User,
) -> Result<(), Error> {
    let entry = audit_entry(ctx, guild_id, Action::Member(serenity::MemberAction::BanRemove), Some(user.id.get()), 10).await;

    let embed = CreateEmbed::new()
        .title("✅  Membre Débanni")
        .description(format!("<@{}> a été débanni.", user.id))
        .color(C_UNBAN)
        .timestamp(now())
        .thumbnail(user.face())
        .field(
            "👤 Utilisateur",
            format!("`{}` — ID `{}`", user.name, user.id),
            false,
        )
        .field("🛡️ Modérateur", audit_user_mention(entry.as_ref()), true)
        .footer(footer_id(user.id));

    log_event(ctx, data, guild_id, embed, None).await;
    Ok(())
}

// ── on_member_update ─────────────────────────────────────────────────────────

pub async fn on_member_update(
    ctx: &serenity::Context,
    data: &Data,
    before: Option<&Member>,
    after: &Member,
) -> Result<(), Error> {
    let guild_id = after.guild_id;
    let before_timeout = before.and_then(|b| b.communication_disabled_until);
    let after_timeout = after.communication_disabled_until;

    // Timeout : traite en priorite puis `return`, comme cote Python.
    if before_timeout != after_timeout {
        let embed = if let Some(until) = after_timeout {
            let entry = audit_entry(
                ctx,
                guild_id,
                Action::Member(serenity::MemberAction::Update),
                Some(after.user.id.get()),
                10,
            )
            .await;
            CreateEmbed::new()
                .title("⏱️  Timeout Appliqué")
                .description(format!("<@{}> a reçu un timeout.", after.user.id))
                .color(C_TIMEOUT)
                .timestamp(now())
                .field("👤 Membre", format!("`{}`", after.user.name), true)
                .field("🛡️ Modérateur", audit_user_mention(entry.as_ref()), true)
                .field("⏰ Expire", ts_relative(Some(&until)), true)
                .field("📋 Raison", audit_reason(entry.as_ref(), "Aucune"), false)
        } else {
            CreateEmbed::new()
                .title("✅  Timeout Levé")
                .description(format!("Le timeout de <@{}> a été levé.", after.user.id))
                .color(C_UNBAN)
                .timestamp(now())
                .field("👤 Membre", format!("`{}`", after.user.name), true)
        };

        log_event(
            ctx,
            data,
            guild_id,
            embed.footer(footer_id(after.user.id)),
            None,
        )
        .await;
        return Ok(());
    }

    let Some(before) = before else { return Ok(()) };

    if before.nick != after.nick {
        let embed = CreateEmbed::new()
            .title("✏️  Pseudo Modifié")
            .description(format!("Le pseudo de <@{}> a changé.", after.user.id))
            .color(C_EDIT)
            .timestamp(now())
            .field(
                "Avant",
                format!("`{}`", before.nick.as_deref().unwrap_or(&before.user.name)),
                true,
            )
            .field(
                "Après",
                format!("`{}`", after.nick.as_deref().unwrap_or(&after.user.name)),
                true,
            )
            .footer(footer_id(after.user.id));
        log_event(ctx, data, guild_id, embed, None).await;
    }

    let added: Vec<_> = after
        .roles
        .iter()
        .filter(|r| !before.roles.contains(r))
        .collect();
    let removed: Vec<_> = before
        .roles
        .iter()
        .filter(|r| !after.roles.contains(r))
        .collect();

    if !added.is_empty() || !removed.is_empty() {
        let entry = audit_entry(
            ctx,
            guild_id,
            Action::Member(serenity::MemberAction::RoleUpdate),
            Some(after.user.id.get()),
            10,
        )
        .await;

        let mut embed = CreateEmbed::new()
            .title("🏷️  Rôles Modifiés")
            .description(format!("Les rôles de <@{}> ont changé.", after.user.id))
            .color(C_ROLE)
            .timestamp(now())
            .field("👤 Membre", format!("`{}`", after.user.name), true);

        if entry.is_some() {
            embed = embed.field("🛡️ Par", audit_user_mention(entry.as_ref()), true);
        }
        if !added.is_empty() {
            let list: Vec<String> = added.iter().map(|r| format!("<@&{r}>")).collect();
            embed = embed.field("✅ Ajoutés", truncate(&list.join(" "), 1024), false);
        }
        if !removed.is_empty() {
            let list: Vec<String> = removed.iter().map(|r| format!("<@&{r}>")).collect();
            embed = embed.field("❌ Retirés", truncate(&list.join(" "), 1024), false);
        }

        log_event(
            ctx,
            data,
            guild_id,
            embed.footer(footer_id(after.user.id)),
            None,
        )
        .await;
    }

    Ok(())
}

// ── on_voice_state_update ────────────────────────────────────────────────────

pub async fn on_voice_state_update(
    ctx: &serenity::Context,
    data: &Data,
    before: Option<&VoiceState>,
    after: &VoiceState,
) -> Result<(), Error> {
    let Some(guild_id) = after.guild_id else {
        return Ok(());
    };
    let user_id = after.user_id;
    let name = match &after.member {
        Some(m) => m.user.name.to_string(),
        None => guild_id
            .member(ctx, user_id)
            .await
            .map(|m| m.user.name.to_string())
            .unwrap_or_else(|_| user_id.to_string()),
    };

    let before_channel = before.and_then(|b| b.channel_id);
    let after_channel = after.channel_id;

    // ── Changements de salon ──
    if before_channel.is_none() && after_channel.is_some() {
        let embed = CreateEmbed::new()
            .title("🔊  Rejoint un Vocal")
            .description(format!("<@{user_id}> a rejoint un salon vocal."))
            .color(C_JOIN)
            .timestamp(now())
            .field("👤 Membre", format!("`{name}`"), true)
            .field("📢 Salon", format!("<#{}>", after_channel.unwrap()), true)
            .footer(footer_id(user_id));
        log_event(ctx, data, guild_id, embed, None).await;
        return Ok(());
    }

    if before_channel.is_some() && after_channel.is_none() {
        let entry = audit_entry(
            ctx,
            guild_id,
            Action::Member(serenity::MemberAction::MemberDisconnect),
            None,
            5,
        )
        .await;

        let embed = if entry.is_some() {
            CreateEmbed::new()
                .title("🔇  Expulsé du Vocal")
                .description(format!(
                    "<@{user_id}> a été déconnecté de force d'un salon vocal."
                ))
                .color(C_BAN)
                .timestamp(now())
                .field("👤 Membre", format!("`{name}`"), true)
                .field("📢 Salon", format!("<#{}>", before_channel.unwrap()), true)
                .field("🛡️ Modérateur", audit_user_mention(entry.as_ref()), true)
        } else {
            CreateEmbed::new()
                .title("🔇  Quitté un Vocal")
                .description(format!("<@{user_id}> a quitté un salon vocal."))
                .color(C_LEAVE)
                .timestamp(now())
                .field("👤 Membre", format!("`{name}`"), true)
                .field("📢 Salon", format!("<#{}>", before_channel.unwrap()), true)
        };

        log_event(ctx, data, guild_id, embed.footer(footer_id(user_id)), None).await;
        return Ok(());
    }

    if before_channel.is_some() && after_channel.is_some() && before_channel != after_channel {
        let entry = audit_entry(
            ctx,
            guild_id,
            Action::Member(serenity::MemberAction::MemberMove),
            None,
            5,
        )
        .await;

        let embed = if entry.is_some() {
            CreateEmbed::new()
                .title("🔀  Déplacé par un Modérateur")
                .description(format!(
                    "<@{user_id}> a été déplacé dans un autre salon vocal."
                ))
                .color(C_WARN)
                .timestamp(now())
                .field("👤 Membre", format!("`{name}`"), true)
                .field("📢 Avant", format!("<#{}>", before_channel.unwrap()), true)
                .field("📢 Après", format!("<#{}>", after_channel.unwrap()), true)
                .field("🛡️ Déplacé par", audit_user_mention(entry.as_ref()), true)
        } else {
            CreateEmbed::new()
                .title("🔀  Changé de Vocal")
                .description(format!(
                    "<@{user_id}> a changé de salon vocal par lui-même."
                ))
                .color(C_VOICE)
                .timestamp(now())
                .field("👤 Membre", format!("`{name}`"), true)
                .field("📢 Avant", format!("<#{}>", before_channel.unwrap()), true)
                .field("📢 Après", format!("<#{}>", after_channel.unwrap()), true)
        };

        log_event(ctx, data, guild_id, embed.footer(footer_id(user_id)), None).await;
        return Ok(());
    }

    // ── Changements d'etat dans le meme salon ──
    let Some(before) = before else { return Ok(()) };
    let Some(channel) = after_channel else {
        return Ok(());
    };
    if before_channel != after_channel {
        return Ok(());
    }

    let mut logs: Vec<CreateEmbed> = Vec::new();

    if before.mute != after.mute {
        logs.push(
            CreateEmbed::new()
                .title(format!(
                    "🔇  {} (serveur)",
                    if after.mute { "Muté" } else { "Démuté" }
                ))
                .description(format!(
                    "<@{user_id}> a été **{}** par le serveur.",
                    if after.mute { "muté" } else { "démuté" }
                ))
                .color(C_WARN),
        );
    }

    if before.deaf != after.deaf {
        logs.push(
            CreateEmbed::new()
                .title(format!(
                    "🙉  {} (serveur)",
                    if after.deaf {
                        "Sourdine"
                    } else {
                        "Sourdine Levée"
                    }
                ))
                .description(format!(
                    "<@{user_id}> a été **{}** par le serveur.",
                    if after.deaf {
                        "mis en sourdine"
                    } else {
                        "retiré de la sourdine"
                    }
                ))
                .color(C_WARN),
        );
    }

    if before.self_mute != after.self_mute {
        logs.push(
            CreateEmbed::new()
                .title(format!(
                    "🎙️  {} (soi-même)",
                    if after.self_mute { "Muté" } else { "Démuté" }
                ))
                .description(format!(
                    "<@{user_id}> s'est **{}**.",
                    if after.self_mute {
                        "mis en sourdine micro"
                    } else {
                        "démuté"
                    }
                ))
                .color(if after.self_mute { C_WARN } else { C_JOIN }),
        );
    }

    if before.self_deaf != after.self_deaf {
        logs.push(
            CreateEmbed::new()
                .title(format!(
                    "🔈  {} (soi-même)",
                    if after.self_deaf {
                        "Sourdine"
                    } else {
                        "Sourdine Levée"
                    }
                ))
                .description(format!(
                    "<@{user_id}> s'est **{}**.",
                    if after.self_deaf {
                        "mis en sourdine"
                    } else {
                        "retiré de la sourdine"
                    }
                ))
                .color(if after.self_deaf { C_WARN } else { C_JOIN }),
        );
    }

    if before.self_stream != after.self_stream {
        let streaming = after.self_stream.unwrap_or(false);
        logs.push(
            CreateEmbed::new()
                .title(format!(
                    "📺  Stream {}",
                    if streaming { "Démarré" } else { "Terminé" }
                ))
                .description(format!(
                    "<@{user_id}> a **{}** son stream.",
                    if streaming { "lancé" } else { "arrêté" }
                ))
                .color(C_VOICE),
        );
    }

    for embed in logs {
        let embed = embed
            .timestamp(now())
            .field("👤 Membre", format!("`{name}`"), true)
            .field("📢 Salon", format!("<#{channel}>"), true)
            .footer(footer_id(user_id));
        log_event(ctx, data, guild_id, embed, None).await;
    }

    Ok(())
}

// ── Messages ─────────────────────────────────────────────────────────────────

pub async fn on_message_delete(
    ctx: &serenity::Context,
    data: &Data,
    guild_id: GuildId,
    message: &Message,
) -> Result<(), Error> {
    if message.author.bot {
        return Ok(());
    }

    let mut embed = CreateEmbed::new()
        .title("🗑️  Message Supprimé")
        .description(format!(
            "Message de <@{}> supprimé dans <#{}>",
            message.author.id, message.channel_id
        ))
        .color(C_DELETE)
        .timestamp(now())
        .field(
            "👤 Auteur",
            format!("`{}` — ID `{}`", message.author.name, message.author.id),
            false,
        )
        .field("📝 Salon", format!("<#{}>", message.channel_id), true);

    if !message.content.is_empty() {
        embed = embed.field(
            "💬 Contenu",
            format!("```{}```", truncate(&message.content, 1020)),
            false,
        );
    }

    if !message.attachments.is_empty() {
        let list: Vec<String> = message
            .attachments
            .iter()
            .map(|a| format!("`{}`", a.filename))
            .collect();
        embed = embed.field("📎 Pièces jointes", truncate(&list.join("\n"), 1024), false);
    }

    log_event(
        ctx,
        data,
        guild_id,
        embed.footer(CreateEmbedFooter::new(format!(
            "ID message : {}",
            message.id
        ))),
        None,
    )
    .await;

    Ok(())
}

pub async fn on_bulk_message_delete(
    ctx: &serenity::Context,
    data: &Data,
    guild_id: GuildId,
    channel_id: serenity::ChannelId,
    ids: &[MessageId],
) -> Result<(), Error> {
    if ids.is_empty() {
        return Ok(());
    }

    let embed = CreateEmbed::new()
        .title("🗑️  Suppression Massive")
        .description(format!(
            "**{}** messages supprimés en masse dans <#{channel_id}>.",
            ids.len()
        ))
        .color(C_BAN)
        .timestamp(now())
        .field("📝 Salon", format!("<#{channel_id}>"), true)
        .field("📊 Nombre", ids.len().to_string(), true);

    log_event(ctx, data, guild_id, embed, None).await;
    Ok(())
}

// ── Salons ───────────────────────────────────────────────────────────────────

/// Portage de `_CHANNEL_TYPES`.
fn channel_type_label(kind: ChannelType) -> &'static str {
    match kind {
        ChannelType::Text | ChannelType::News => "📝 Textuel",
        ChannelType::Voice => "🔊 Vocal",
        ChannelType::Category => "📁 Catégorie",
        ChannelType::Stage => "🎙️ Scène",
        ChannelType::Forum => "💬 Forum",
        ChannelType::PublicThread | ChannelType::PrivateThread | ChannelType::NewsThread => {
            "🧵 Thread"
        }
        _ => "Salon",
    }
}

pub async fn on_channel_create(
    ctx: &serenity::Context,
    data: &Data,
    channel: &GuildChannel,
) -> Result<(), Error> {
    let entry = audit_entry(
        ctx,
        channel.guild_id,
        Action::Channel(serenity::ChannelAction::Create),
        Some(channel.id.get()),
        10,
    )
    .await;

    let embed = CreateEmbed::new()
        .title(format!(
            "✅  Salon Créé — {}",
            channel_type_label(channel.kind)
        ))
        .description(format!("Le salon <#{}> a été créé.", channel.id))
        .color(C_CHANNEL)
        .timestamp(now())
        .field("📝 Nom", format!("`{}`", channel.name), true)
        .field("🛡️ Créé par", audit_user_mention(entry.as_ref()), true)
        .footer(footer_id(channel.id));

    log_event(ctx, data, channel.guild_id, embed, None).await;
    Ok(())
}

pub async fn on_channel_delete(
    ctx: &serenity::Context,
    data: &Data,
    channel: &GuildChannel,
) -> Result<(), Error> {
    let entry = audit_entry(
        ctx,
        channel.guild_id,
        Action::Channel(serenity::ChannelAction::Delete),
        None,
        10,
    )
    .await;

    let embed = CreateEmbed::new()
        .title("❌  Salon Supprimé")
        .description(format!("Le salon **#{}** a été supprimé.", channel.name))
        .color(C_BAN)
        .timestamp(now())
        .field("📝 Nom", format!("`{}`", channel.name), true)
        .field("🛡️ Supprimé par", audit_user_mention(entry.as_ref()), true)
        .footer(footer_id(channel.id));

    log_event(ctx, data, channel.guild_id, embed, None).await;
    Ok(())
}

pub async fn on_channel_update(
    ctx: &serenity::Context,
    data: &Data,
    before: Option<&GuildChannel>,
    after: &GuildChannel,
) -> Result<(), Error> {
    let Some(before) = before else { return Ok(()) };
    let mut changes: Vec<String> = Vec::new();

    if before.name != after.name {
        changes.push(format!("**Nom** : `{}` → `{}`", before.name, after.name));
    }
    if before.topic != after.topic {
        changes.push(format!(
            "**Description** : `{}` → `{}`",
            before.topic.as_deref().unwrap_or("—"),
            after.topic.as_deref().unwrap_or("—")
        ));
    }
    if before.nsfw != after.nsfw {
        changes.push(format!("**NSFW** : `{}` → `{}`", before.nsfw, after.nsfw));
    }
    if before.rate_limit_per_user != after.rate_limit_per_user {
        changes.push(format!(
            "**Slowmode** : `{}s` → `{}s`",
            before.rate_limit_per_user.unwrap_or(0),
            after.rate_limit_per_user.unwrap_or(0)
        ));
    }
    if changes.is_empty() {
        return Ok(());
    }

    let embed = CreateEmbed::new()
        .title("✏️  Salon Modifié")
        .description(format!("Le salon <#{}> a été modifié.", after.id))
        .color(C_EDIT)
        .timestamp(now())
        .field(
            "🔄 Modifications",
            truncate(&changes.join("\n"), 1024),
            false,
        )
        .footer(footer_id(after.id));

    log_event(ctx, data, after.guild_id, embed, None).await;
    Ok(())
}

// ── Rôles ────────────────────────────────────────────────────────────────────

pub async fn on_role_create(
    ctx: &serenity::Context,
    data: &Data,
    role: &Role,
) -> Result<(), Error> {
    let entry = audit_entry(
        ctx,
        role.guild_id,
        Action::Role(serenity::RoleAction::Create),
        Some(role.id.get()),
        10,
    )
    .await;

    let embed = CreateEmbed::new()
        .title("✅  Rôle Créé")
        .description(format!("Le rôle <@&{}> a été créé.", role.id))
        .color(C_ROLE)
        .timestamp(now())
        .field("🏷️ Nom", format!("`{}`", role.name), true)
        .field("🎨 Couleur", format!("#{:06x}", role.colour.0), true)
        .field("🛡️ Créé par", audit_user_mention(entry.as_ref()), true)
        .footer(footer_id(role.id));

    log_event(ctx, data, role.guild_id, embed, None).await;
    Ok(())
}

pub async fn on_role_delete(
    ctx: &serenity::Context,
    data: &Data,
    guild_id: GuildId,
    role_id: serenity::RoleId,
    role: Option<&Role>,
) -> Result<(), Error> {
    let entry = audit_entry(
        ctx,
        guild_id,
        Action::Role(serenity::RoleAction::Delete),
        None,
        10,
    )
    .await;

    let name = role.map(|r| r.name.to_string()).unwrap_or_else(|| "inconnu".into());

    let embed = CreateEmbed::new()
        .title("❌  Rôle Supprimé")
        .description(format!("Le rôle **{name}** a été supprimé."))
        .color(C_BAN)
        .timestamp(now())
        .field("🏷️ Nom", format!("`{name}`"), true)
        .field("🛡️ Supprimé par", audit_user_mention(entry.as_ref()), true)
        .footer(footer_id(role_id));

    log_event(ctx, data, guild_id, embed, None).await;
    Ok(())
}

pub async fn on_role_update(
    ctx: &serenity::Context,
    data: &Data,
    before: Option<&Role>,
    after: &Role,
) -> Result<(), Error> {
    let Some(before) = before else { return Ok(()) };
    let mut changes: Vec<String> = Vec::new();

    if before.name != after.name {
        changes.push(format!("**Nom** : `{}` → `{}`", before.name, after.name));
    }
    if before.colour != after.colour {
        changes.push(format!(
            "**Couleur** : `#{:06x}` → `#{:06x}`",
            before.colour.0, after.colour.0
        ));
    }
    if before.hoist != after.hoist {
        changes.push(format!(
            "**Affiché séparément** : `{}` → `{}`",
            before.hoist,
            after.hoist
        ));
    }
    if before.mentionable != after.mentionable {
        changes.push(format!(
            "**Mentionnable** : `{}` → `{}`",
            before.mentionable,
            after.mentionable
        ));
    }
    if before.permissions != after.permissions {
        changes.push("**Permissions** modifiées".to_string());
    }
    if changes.is_empty() {
        return Ok(());
    }

    let embed = CreateEmbed::new()
        .title("✏️  Rôle Modifié")
        .description(format!("Le rôle <@&{}> a été modifié.", after.id))
        .color(C_ROLE)
        .timestamp(now())
        .field(
            "🔄 Modifications",
            truncate(&changes.join("\n"), 1024),
            false,
        )
        .footer(footer_id(after.id));

    log_event(ctx, data, after.guild_id, embed, None).await;
    Ok(())
}

// ── Serveur ──────────────────────────────────────────────────────────────────

pub async fn on_guild_update(
    ctx: &serenity::Context,
    data: &Data,
    before: Option<&serenity::Guild>,
    after: &PartialGuild,
) -> Result<(), Error> {
    let Some(before) = before else { return Ok(()) };
    let mut changes: Vec<String> = Vec::new();

    if before.name != after.name {
        changes.push(format!("**Nom** : `{}` → `{}`", before.name, after.name));
    }
    if before.icon != after.icon {
        changes.push("**Icône** modifiée".to_string());
    }
    if before.banner != after.banner {
        changes.push("**Bannière** modifiée".to_string());
    }
    if before.verification_level != after.verification_level {
        changes.push(format!(
            "**Vérification** : `{:?}` → `{:?}`",
            before.verification_level, after.verification_level
        ));
    }
    if before.explicit_content_filter != after.explicit_content_filter {
        changes.push(format!(
            "**Filtre contenu** : `{:?}` → `{:?}`",
            before.explicit_content_filter, after.explicit_content_filter
        ));
    }
    if changes.is_empty() {
        return Ok(());
    }

    let embed = CreateEmbed::new()
        .title("⚙️  Serveur Modifié")
        .description(format!("Le serveur **{}** a été mis à jour.", after.name))
        .color(C_SERVER)
        .timestamp(now())
        .field(
            "🔄 Modifications",
            truncate(&changes.join("\n"), 1024),
            false,
        );

    log_event(ctx, data, after.id, embed, None).await;
    Ok(())
}

// ── Invitations ──────────────────────────────────────────────────────────────

pub async fn on_invite_create(
    ctx: &serenity::Context,
    data: &Data,
    event: &serenity::InviteCreateEvent,
) -> Result<(), Error> {
    let Some(guild_id) = event.guild_id else {
        return Ok(());
    };

    // discord.py expose `invite.expires_at` ; la gateway ne transmet que
    // `max_age`, on le derive de la date de création.
    let expires = if event.max_age == 0 {
        "Jamais".to_string()
    } else {
        let at = *event.created_at + chrono::Duration::seconds(event.max_age as i64);
        format!("<t:{}:R>", at.timestamp())
    };

    let embed = CreateEmbed::new()
        .title("🔗  Invitation Créée")
        .color(C_INFO)
        .timestamp(now())
        .field("🔑 Code", format!("`{}`", event.code), true)
        .field(
            "👤 Créée par",
            match &event.inviter {
                Some(u) => format!("<@{}>", u.id),
                None => "Inconnu".to_string(),
            },
            true,
        )
        .field("📢 Salon", format!("<#{}>", event.channel_id), true)
        .field("⏰ Expire", expires, true)
        .field(
            "🔢 Utilisations max",
            if event.max_uses == 0 {
                "∞".to_string()
            } else {
                event.max_uses.to_string()
            },
            true,
        );

    log_event(ctx, data, guild_id, embed, None).await;
    Ok(())
}

pub async fn on_invite_delete(
    ctx: &serenity::Context,
    data: &Data,
    event: &serenity::InviteDeleteEvent,
) -> Result<(), Error> {
    let Some(guild_id) = event.guild_id else {
        return Ok(());
    };

    let embed = CreateEmbed::new()
        .title("🔗  Invitation Supprimée")
        .description(format!("L'invitation `{}` a été révoquée.", event.code))
        .color(C_LEAVE)
        .timestamp(now())
        .field("🔑 Code", format!("`{}`", event.code), true)
        .field("📢 Salon", format!("<#{}>", event.channel_id), true);

    log_event(ctx, data, guild_id, embed, None).await;
    Ok(())
}

// ── Emojis & stickers ────────────────────────────────────────────────────────

/// Diff generique entre l'instantane precedent et l'etat courant.
fn diff_snapshot(
    snapshot: &dashmap::DashMap<u64, Vec<(u64, String)>>,
    guild_id: GuildId,
    current: Vec<(u64, String)>,
) -> (Vec<(u64, String)>, Vec<(u64, String)>) {
    let previous = snapshot
        .insert(guild_id.get(), current.clone())
        .unwrap_or_default();

    let added = current
        .iter()
        .filter(|(id, _)| !previous.iter().any(|(pid, _)| pid == id))
        .cloned()
        .collect();
    let removed = previous
        .iter()
        .filter(|(id, _)| !current.iter().any(|(cid, _)| cid == id))
        .cloned()
        .collect();

    (added, removed)
}

pub async fn on_emojis_update(
    ctx: &serenity::Context,
    data: &Data,
    guild_id: GuildId,
    current: Vec<(u64, String)>,
) -> Result<(), Error> {
    let is_first = !data.emoji_snapshot.contains_key(&guild_id.get());
    let (added, removed) = diff_snapshot(&data.emoji_snapshot, guild_id, current);

    // Premier evenement apres le demarrage : rien a comparer.
    if is_first || (added.is_empty() && removed.is_empty()) {
        return Ok(());
    }

    let mut embed = CreateEmbed::new()
        .title("😀  Emojis Modifiés")
        .color(C_INFO)
        .timestamp(now());

    if !added.is_empty() {
        let list: Vec<String> = added
            .iter()
            .take(20)
            .map(|(id, name)| format!("<:{name}:{id}>"))
            .collect();
        embed = embed.field("✅ Ajoutés", non_empty(&list.join(" ")), false);
    }
    if !removed.is_empty() {
        let list: Vec<String> = removed
            .iter()
            .take(20)
            .map(|(_, name)| format!("`:{name}:`"))
            .collect();
        embed = embed.field("❌ Supprimés", non_empty(&list.join(" ")), false);
    }

    log_event(ctx, data, guild_id, embed, None).await;
    Ok(())
}

pub async fn on_stickers_update(
    ctx: &serenity::Context,
    data: &Data,
    guild_id: GuildId,
    current: Vec<(u64, String)>,
) -> Result<(), Error> {
    let is_first = !data.sticker_snapshot.contains_key(&guild_id.get());
    let (added, removed) = diff_snapshot(&data.sticker_snapshot, guild_id, current);

    if is_first || (added.is_empty() && removed.is_empty()) {
        return Ok(());
    }

    let mut embed = CreateEmbed::new()
        .title("🎭  Stickers Modifiés")
        .color(C_INFO)
        .timestamp(now());

    if !added.is_empty() {
        let list: Vec<String> = added
            .iter()
            .take(20)
            .map(|(_, name)| format!("`{name}`"))
            .collect();
        embed = embed.field("✅ Ajoutés", non_empty(&list.join("\n")), false);
    }
    if !removed.is_empty() {
        let list: Vec<String> = removed
            .iter()
            .take(20)
            .map(|(_, name)| format!("`{name}`"))
            .collect();
        embed = embed.field("❌ Supprimés", non_empty(&list.join("\n")), false);
    }

    log_event(ctx, data, guild_id, embed, None).await;
    Ok(())
}

// ── Threads ──────────────────────────────────────────────────────────────────

pub async fn on_thread_create(
    ctx: &serenity::Context,
    data: &Data,
    thread: &GuildChannel,
) -> Result<(), Error> {
    let parent = match thread.parent_id {
        Some(p) => format!("<#{p}>"),
        None => "un salon".to_string(),
    };

    let embed = CreateEmbed::new()
        .title("🧵  Thread Créé")
        .description(format!("Un nouveau thread a été créé dans {parent}."))
        .color(C_CHANNEL)
        .timestamp(now())
        .field("📝 Thread", format!("<#{}>", thread.id), true)
        .field(
            "👤 Créé par",
            match thread.owner_id {
                Some(o) => format!("<@{o}>"),
                None => "Inconnu".to_string(),
            },
            true,
        )
        .footer(footer_id(thread.id));

    log_event(ctx, data, thread.guild_id, embed, None).await;
    Ok(())
}

pub async fn on_thread_delete(
    ctx: &serenity::Context,
    data: &Data,
    guild_id: GuildId,
    thread_id: serenity::ChannelId,
    name: Option<&str>,
) -> Result<(), Error> {
    let name = name.unwrap_or("inconnu");

    let embed = CreateEmbed::new()
        .title("🧵  Thread Supprimé")
        .description(format!("Le thread **{name}** a été supprimé."))
        .color(C_BAN)
        .timestamp(now())
        .field("📝 Nom", format!("`{name}`"), true)
        .footer(footer_id(thread_id));

    log_event(ctx, data, guild_id, embed, None).await;
    Ok(())
}
