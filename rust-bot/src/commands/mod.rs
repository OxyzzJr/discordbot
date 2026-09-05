//! Enregistrement de toutes les commandes du framework.

pub mod fun;
pub mod info;
pub mod moderation;
pub mod owner;
pub mod settings;

use crate::data::{Data, Error};

/// Liste complete passee a `poise::FrameworkOptions`.
pub fn all() -> Vec<poise::Command<Data, Error>> {
    vec![
        // Sanctions
        moderation::kick(),
        moderation::ban(),
        moderation::tempban(),
        moderation::unban(),
        moderation::mute(),
        moderation::unmute(),
        moderation::warn(),
        moderation::warnings_cmd(),
        moderation::clearwarnings(),
        moderation::purge(),
        moderation::slowmode(),
        // Infos & cases
        info::userinfo(),
        info::serverinfo(),
        info::historique(),
        info::case_cmd(),
        info::editcase(),
        info::regles(),
        info::modhelp(),
        // Configuration
        settings::setregles(),
        settings::setwelcome(),
        settings::setmodchannel(),
        settings::setlogchannel(),
        settings::autorole_create_soumises(),
        // Owner (prefixe, cachee)
        owner::ascend(),
        // Prototype
        fun::ntm(),
        fun::fdpduserv(),
        fun::turc(),
    ]
}
