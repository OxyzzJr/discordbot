//! Etat global partage entre commandes et listeners.
//!
//! Remplace les attributs d'instance des cogs Python (`spam_tracker`,
//! `last_messages`, `file_tracker`, `_blacklist_cache`). `DashMap` fournit
//! l'interieur mutable concurrent sans envelopper toute la struct dans un
//! `RwLock` unique.

use std::collections::VecDeque;
use std::time::Instant;

use dashmap::DashMap;
use sqlx::SqlitePool;

use crate::config::Config;

pub struct Data {
    pub db: SqlitePool,
    pub config: Config,
    /// Horodatages des derniers messages, par utilisateur (detection de spam).
    pub spam_tracker: DashMap<u64, VecDeque<Instant>>,
    /// Dernier contenu poste par utilisateur (detection de repetition).
    pub last_messages: DashMap<u64, String>,
    /// Horodatages des pieces jointes recentes, par utilisateur.
    pub file_tracker: DashMap<u64, VecDeque<Instant>>,
    /// Cache par guilde de la blacklist de mots (invalide via `invalidate_blacklist`).
    pub blacklist_cache: DashMap<u64, Vec<String>>,
    /// Instantane des emojis par guilde. discord.py fournit `before`/`after` a
    /// `on_guild_emojis_update` ; la gateway ne transmet que l'etat courant, on
    /// conserve donc le precedent pour calculer le diff.
    pub emoji_snapshot: DashMap<u64, Vec<(u64, String)>>,
    /// Idem pour `on_guild_stickers_update`.
    pub sticker_snapshot: DashMap<u64, Vec<(u64, String)>>,
}

impl Data {
    pub fn new(db: SqlitePool, config: Config) -> Self {
        Self {
            db,
            config,
            spam_tracker: DashMap::new(),
            last_messages: DashMap::new(),
            file_tracker: DashMap::new(),
            blacklist_cache: DashMap::new(),
            emoji_snapshot: DashMap::new(),
            sticker_snapshot: DashMap::new(),
        }
    }

    /// Portage de `AutoMod.get_blacklist` : lecture SQL une seule fois par guilde.
    pub async fn blacklist(&self, guild_id: u64) -> Vec<String> {
        if let Some(cached) = self.blacklist_cache.get(&guild_id) {
            return cached.clone();
        }
        let words = crate::db::get_blacklist_words(&self.db, guild_id as i64)
            .await
            .unwrap_or_default();
        self.blacklist_cache.insert(guild_id, words.clone());
        words
    }

    /// Portage de `AutoMod.invalidate_cache`.
    #[allow(dead_code)]
    pub fn invalidate_blacklist(&self, guild_id: u64) {
        self.blacklist_cache.remove(&guild_id);
    }

    /// Fenetre glissante commune aux compteurs de spam et de fichiers.
    /// Renvoie le nombre d'evenements encore dans la fenetre.
    pub fn push_window(
        map: &DashMap<u64, VecDeque<Instant>>,
        user_id: u64,
        now: Instant,
        window_secs: i64,
        pushes: usize,
    ) -> usize {
        let mut entry = map.entry(user_id).or_default();
        for _ in 0..pushes {
            entry.push_back(now);
        }
        let window = std::time::Duration::from_secs(window_secs.max(0) as u64);
        while let Some(front) = entry.front() {
            if now.duration_since(*front) > window {
                entry.pop_front();
            } else {
                break;
            }
        }
        entry.len()
    }

    pub fn clear_window(map: &DashMap<u64, VecDeque<Instant>>, user_id: u64) {
        if let Some(mut entry) = map.get_mut(&user_id) {
            entry.clear();
        }
    }
}

pub type Error = Box<dyn std::error::Error + Send + Sync>;
pub type Context<'a> = poise::Context<'a, Data, Error>;
