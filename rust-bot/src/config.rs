//! Configuration issue de l'environnement (portage de `config.py`).

use std::env;

/// Palette utilisee par les embeds, identique au dict `COLORS` de `config.py`.
pub const COLOR_SUCCESS: u32 = 0x00ff00;
pub const COLOR_ERROR: u32 = 0xff0000;
pub const COLOR_WARNING: u32 = 0xffff00;
pub const COLOR_INFO: u32 = 0x0099ff;

#[derive(Debug, Clone)]
pub struct Config {
    pub discord_token: String,
    pub owner_id: u64,
    pub max_warnings: i64,
    pub mute_role_name: String,
    #[allow(dead_code)] // present dans config.py, jamais lu par les cogs
    pub log_channel_name: String,
    #[allow(dead_code)] // surcharge par automod_config en base
    pub spam_threshold: i64,
    #[allow(dead_code)]
    pub spam_interval: i64,
    #[allow(dead_code)]
    pub max_mentions: i64,
    pub database_path: String,
}

fn env_or<T: std::str::FromStr>(key: &str, default: T) -> T {
    env::var(key)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}

impl Config {
    /// Charge la configuration depuis `.env` puis l'environnement du processus.
    pub fn from_env() -> Self {
        Self {
            discord_token: env::var("DISCORD_TOKEN").unwrap_or_default(),
            owner_id: env_or("OWNER_ID", 0),
            max_warnings: env_or("MAX_WARNINGS", 3),
            mute_role_name: env::var("MUTE_ROLE_NAME").unwrap_or_else(|_| "Muted".into()),
            log_channel_name: env::var("LOG_CHANNEL_NAME").unwrap_or_else(|_| "mod-logs".into()),
            spam_threshold: env_or("SPAM_THRESHOLD", 5),
            spam_interval: env_or("SPAM_INTERVAL", 10),
            max_mentions: env_or("MAX_MENTIONS", 5),
            database_path: env::var("DATABASE_PATH").unwrap_or_else(|_| "moderation.db".into()),
        }
    }
}
