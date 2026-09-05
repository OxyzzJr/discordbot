//! Commandes du prototype `attached_assets/bot_1749742200669.py`.
//!
//! Elles n'etaient pas chargees par `main.py` ; portees ici a la demande.

use crate::data::{Context, Error};
use poise::serenity_prelude as serenity;

/// ntm
#[poise::command(slash_command)]
pub async fn ntm(
    ctx: Context<'_>,
    #[description = "La personne que vous voulez niquer la mams a "] user: serenity::Member,
) -> Result<(), Error> {
    ctx.say(format!("pine ta mams <@{}> !", user.user.id)).await?;
    Ok(())
}

/// Mentionne un membre donné comme le fdp
#[poise::command(slash_command)]
pub async fn fdpduserv(
    ctx: Context<'_>,
    #[description = "Le membre que vous voulez mentionner"] user: serenity::Member,
) -> Result<(), Error> {
    ctx.say(format!(
        "<@{}> est le plus gros fdp que ce monde ai connu meme gazem prime \
         n'arrive pas a sa cheville!!!",
        user.user.id
    ))
    .await?;
    Ok(())
}

/// kardesh
#[poise::command(slash_command)]
pub async fn turc(ctx: Context<'_>) -> Result<(), Error> {
    ctx.say(
        "Arap tout casser et flemmard et vendre shit et voler Nous kardeshim faire kredi \
         por bmw a 16 ans vous arap tout casser turk tout reparer MEHMET IL EST OÙ MON \
         AYRAN BRRRRRRRRR SKIBIDI DOP DOP YES YES YES MANGER KEBAB JAMAIS MALAD",
    )
    .await?;
    Ok(())
}
