//! Verification des nouveaux membres (portage de `cogs/autorole.py`).

use poise::serenity_prelude as serenity;
use serenity::all::{
    ComponentInteraction, CreateActionRow, CreateButton, CreateEmbed, CreateEmbedFooter,
    CreateInteractionResponse, CreateInteractionResponseMessage, CreateMessage, Member, RoleId,
    UserId,
};

use crate::config::{COLOR_ERROR, COLOR_SUCCESS, COLOR_WARNING};
use crate::data::{Data, Error};
use crate::helpers;

pub const ROLE_SOUMISES: &str = "soumises";

/// Les `custom_id` embarquent l'ID du membre concerne. La version Python le
/// gardait dans l'instance de `ShabView`, ce qui rendait les boutons inertes
/// apres un redemarrage ; ici ils restent fonctionnels.
fn custom_id(answer: &str, member_id: UserId) -> String {
    format!("shab_{answer}:{member_id}")
}

/// Portage de `AutoRole.on_member_join`.
pub async fn on_member_join(
    ctx: &serenity::Context,
    data: &Data,
    member: &Member,
) -> Result<(), Error> {
    let guild_id = member.guild_id;

    let Some(mod_channel) = helpers::mod_channel(data, guild_id).await else {
        let guild_name = ctx
            .cache
            .guild(guild_id)
            .map(|g| g.name.to_string())
            .unwrap_or_default();
        tracing::warn!(
            "[AutoRole] Aucun salon modérateur défini pour {guild_name}. \
             Utilise /setmodchannel pour en définir un."
        );
        return Ok(());
    };

    let embed = CreateEmbed::new()
        .title("🔎 Nouveau membre — Vérification")
        .description(format!(
            "<@{}> vient de rejoindre le serveur.\n\n**Est-ce que c'est un shab ?**",
            member.user.id
        ))
        .color(COLOR_WARNING)
        .timestamp(serenity::Timestamp::now())
        .thumbnail(member.face())
        .field(
            "Utilisateur",
            format!("{} (ID : {})", member.user.name, member.user.id),
            true,
        )
        .field(
            "Compte créé le",
            member
                .user
                .created_at()
                .format("%d/%m/%Y %H:%M")
                .to_string(),
            true,
        );

    let row = CreateActionRow::Buttons(vec![
        CreateButton::new(custom_id("oui", member.user.id))
            .label("✅ Oui")
            .style(serenity::ButtonStyle::Danger),
        CreateButton::new(custom_id("non", member.user.id))
            .label("❌ Non")
            .style(serenity::ButtonStyle::Success),
    ]);

    if mod_channel
        .send_message(
            &ctx.http,
            CreateMessage::new().embed(embed).components(vec![row]),
        )
        .await
        .is_err()
    {
        tracing::error!("[AutoRole] Permission refusée pour écrire dans <#{mod_channel}>");
    }

    Ok(())
}

/// Portage des callbacks `ShabView.oui` / `ShabView.non`.
/// Renvoie `true` si l'interaction a ete prise en charge.
pub async fn handle_component(
    ctx: &serenity::Context,
    interaction: &ComponentInteraction,
) -> Result<bool, Error> {
    let id = &interaction.data.custom_id;
    let Some((prefix, target)) = id.split_once(':') else {
        return Ok(false);
    };
    let answer = match prefix {
        "shab_oui" => true,
        "shab_non" => false,
        _ => return Ok(false),
    };
    let Ok(target_id) = target.parse::<u64>().map(UserId::new) else {
        return Ok(false);
    };
    let Some(guild_id) = interaction.guild_id else {
        return Ok(false);
    };

    // `interaction.user.guild_permissions.manage_roles`
    let can_manage = match guild_id.member(ctx, interaction.user.id).await {
        Ok(m) => helpers::member_permissions(ctx, &m).manage_roles(),
        Err(_) => false,
    };
    if !can_manage {
        respond_ephemeral(
            ctx,
            interaction,
            "❌ Tu n'as pas la permission de gérer les rôles.",
        )
        .await?;
        return Ok(true);
    }

    let base_embed = interaction
        .message
        .embeds
        .first()
        .cloned()
        .map(CreateEmbed::from)
        .unwrap_or_default();

    if !answer {
        // Bouton « Non » : on confirme simplement, sans toucher aux rôles.
        finish(
            ctx,
            interaction,
            base_embed.color(COLOR_SUCCESS).footer(CreateEmbedFooter::new(format!(
                "✅ Confirmé : pas un shab — {} • {}",
                interaction.user.name,
                chrono::Utc::now().format("%H:%M:%S")
            ))),
        )
        .await?;
        return Ok(true);
    }

    let Ok(member) = guild_id.member(ctx, target_id).await else {
        respond_ephemeral(ctx, interaction, "❌ Le membre a quitté le serveur.").await?;
        let mut msg = interaction.message.as_ref().clone();
        let _ = msg
            .edit(ctx, serenity::EditMessage::new().components(vec![]))
            .await;
        return Ok(true);
    };

    let role: Option<RoleId> = guild_id
        .roles(&ctx.http)
        .await
        .ok()
        .and_then(|roles| {
            roles
                .into_values()
                .find(|r| r.name == ROLE_SOUMISES)
                .map(|r| r.id)
        });

    let Some(role) = role else {
        respond_ephemeral(
            ctx,
            interaction,
            &format!(
                "❌ Le rôle **{ROLE_SOUMISES}** est introuvable. \
                 Crée-le d'abord avec `/autorole_create_soumises`."
            ),
        )
        .await?;
        return Ok(true);
    };

    let reason = format!("Shab confirmé par {}", interaction.user.name);
    if helpers::add_role_reason(&ctx.http, guild_id, member.user.id, role, &reason)
        .await
        .is_err()
    {
        respond_ephemeral(
            ctx,
            interaction,
            "❌ Je n'ai pas la permission d'attribuer ce rôle (vérifie la hiérarchie).",
        )
        .await?;
        return Ok(true);
    }

    tracing::info!(
        "[AutoRole] Rôle '{ROLE_SOUMISES}' attribué à {} par {}",
        member.user.name,
        interaction.user.name
    );

    finish(
        ctx,
        interaction,
        base_embed.color(COLOR_ERROR).footer(CreateEmbedFooter::new(format!(
            "✅ Rôle '{ROLE_SOUMISES}' attribué par {} • {}",
            interaction.user.name,
            chrono::Utc::now().format("%H:%M:%S")
        ))),
    )
    .await?;

    Ok(true)
}

async fn respond_ephemeral(
    ctx: &serenity::Context,
    interaction: &ComponentInteraction,
    content: &str,
) -> Result<(), Error> {
    interaction
        .create_response(
            &ctx.http,
            CreateInteractionResponse::Message(
                CreateInteractionResponseMessage::new()
                    .content(content)
                    .ephemeral(true),
            ),
        )
        .await?;
    Ok(())
}

/// `_disable_all()` + `edit_message(embed=..., view=self)`.
async fn finish(
    ctx: &serenity::Context,
    interaction: &ComponentInteraction,
    embed: CreateEmbed,
) -> Result<(), Error> {
    interaction
        .create_response(
            &ctx.http,
            CreateInteractionResponse::UpdateMessage(
                CreateInteractionResponseMessage::new()
                    .embed(embed)
                    .components(vec![]),
            ),
        )
        .await?;
    Ok(())
}
