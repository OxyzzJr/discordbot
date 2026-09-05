//! Couche SQLite (portage de `utils/database.py`).
//!
//! Le schema est conserve a l'identique : la base `moderation.db` produite par
//! la version Python reste lisible et inscriptible par ce binaire.

use anyhow::Result;
use chrono::NaiveDateTime;
use sqlx::sqlite::{SqliteConnectOptions, SqlitePoolOptions};
use sqlx::AssertSqlSafe;
use sqlx::{Row, SqlitePool};

use crate::util::{parse_db_datetime, to_db_datetime};

// ── Configuration auto-mod ───────────────────────────────────────────────────

/// Portage de `AUTOMOD_DEFAULTS`.
#[derive(Debug, Clone, Copy)]
pub struct AutomodConfig {
    pub spam_threshold: i64,
    pub spam_interval: i64,
    pub max_mentions: i64,
    pub caps_detection: bool,
    pub caps_min_length: i64,
    pub caps_percent: i64,
    pub file_flood_limit: i64,
    pub file_flood_interval: i64,
    pub pts_warn: i64,
    pub pts_mute: i64,
    pub pts_mute_duration: i64,
    pub pts_kick: i64,
    pub pts_ban: i64,
    pub pts_ban_duration: i64,
}

impl Default for AutomodConfig {
    fn default() -> Self {
        Self {
            spam_threshold: 5,
            spam_interval: 10,
            max_mentions: 5,
            caps_detection: true,
            caps_min_length: 10,
            caps_percent: 70,
            file_flood_limit: 5,
            file_flood_interval: 30,
            pts_warn: 5,
            pts_mute: 10,
            pts_mute_duration: 600,
            pts_kick: 15,
            pts_ban: 20,
            pts_ban_duration: 3600,
        }
    }
}

/// Portage du tuple renvoye par `get_guild_settings`.
#[derive(Debug, Clone, Default)]
pub struct GuildSettings {
    pub log_channel_id: Option<i64>,
    pub mute_role_id: Option<i64>,
    pub automod_enabled: bool,
    pub spam_detection: bool,
    pub rules_text: Option<String>,
    pub welcome_channel_id: Option<i64>,
    pub welcome_message: Option<String>,
    pub mod_channel_id: Option<i64>,
}

/// Champs modifiables de `guild_settings` (equivalent des `**kwargs` Python).
#[derive(Debug, Default)]
pub struct GuildSettingsPatch {
    pub log_channel_id: Option<Option<i64>>,
    pub mute_role_id: Option<Option<i64>>,
    pub automod_enabled: Option<bool>,
    pub spam_detection: Option<bool>,
    pub rules_text: Option<Option<String>>,
    pub welcome_channel_id: Option<Option<i64>>,
    pub welcome_message: Option<Option<String>>,
    pub mod_channel_id: Option<Option<i64>>,
}

// ── Lignes retournees ────────────────────────────────────────────────────────

#[derive(Debug, Clone)]
pub struct Warning {
    #[allow(dead_code)]
    pub id: i64,
    pub moderator_id: i64,
    pub reason: String,
    pub timestamp: String,
}

#[derive(Debug, Clone)]
pub struct Sanction {
    pub case_id: i64,
    pub action: String,
    pub moderator_id: i64,
    pub reason: Option<String>,
    pub duration: Option<String>,
    pub timestamp: String,
}

#[derive(Debug, Clone)]
pub struct CaseRow {
    pub case_id: i64,
    pub user_id: i64,
    pub moderator_id: i64,
    pub action: String,
    pub reason: Option<String>,
    pub duration: Option<String>,
    pub timestamp: String,
}

/// `(guild_id, user_id, echeance)`
pub type Expiry = (i64, i64, NaiveDateTime);

// ── Initialisation ───────────────────────────────────────────────────────────

pub async fn connect(path: &str) -> Result<SqlitePool> {
    let opts = SqliteConnectOptions::new()
        .filename(path)
        .create_if_missing(true)
        .busy_timeout(std::time::Duration::from_secs(10));

    let pool = SqlitePoolOptions::new()
        .max_connections(5)
        .connect_with(opts)
        .await?;

    Ok(pool)
}

/// Portage de `init_db()` : creation des tables + migrations idempotentes.
pub async fn init_db(pool: &SqlitePool) -> Result<()> {
    let tables = [
        r#"CREATE TABLE IF NOT EXISTS warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL, reason TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )"#,
        r#"CREATE TABLE IF NOT EXISTS mutes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL, reason TEXT NOT NULL,
            muted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            unmuted_at DATETIME, unmute_at DATETIME, active BOOLEAN DEFAULT 1
        )"#,
        r#"CREATE TABLE IF NOT EXISTS guild_settings (
            guild_id INTEGER PRIMARY KEY,
            log_channel_id INTEGER, mute_role_id INTEGER,
            automod_enabled BOOLEAN DEFAULT 1, spam_detection BOOLEAN DEFAULT 1,
            rules_text TEXT, welcome_channel_id INTEGER, welcome_message TEXT,
            mod_channel_id INTEGER
        )"#,
        r#"CREATE TABLE IF NOT EXISTS tempbans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL, reason TEXT NOT NULL,
            banned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            unban_at DATETIME NOT NULL, active BOOLEAN DEFAULT 1
        )"#,
        r#"CREATE TABLE IF NOT EXISTS sanctions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER,
            guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL, action TEXT NOT NULL,
            reason TEXT, duration TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )"#,
        r#"CREATE TABLE IF NOT EXISTS word_blacklist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL, word TEXT NOT NULL,
            added_by INTEGER NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )"#,
        r#"CREATE TABLE IF NOT EXISTS violation_points (
            guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            points INTEGER DEFAULT 0,
            last_violation DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (guild_id, user_id)
        )"#,
        r#"CREATE TABLE IF NOT EXISTS automod_config (
            guild_id INTEGER PRIMARY KEY,
            spam_threshold INTEGER DEFAULT 5,
            spam_interval INTEGER DEFAULT 10,
            max_mentions INTEGER DEFAULT 5,
            caps_detection BOOLEAN DEFAULT 1,
            caps_min_length INTEGER DEFAULT 10,
            caps_percent INTEGER DEFAULT 70,
            file_flood_limit INTEGER DEFAULT 5,
            file_flood_interval INTEGER DEFAULT 30,
            pts_warn INTEGER DEFAULT 5,
            pts_mute INTEGER DEFAULT 10,
            pts_mute_duration INTEGER DEFAULT 600,
            pts_kick INTEGER DEFAULT 15,
            pts_ban INTEGER DEFAULT 20,
            pts_ban_duration INTEGER DEFAULT 3600
        )"#,
    ];

    for stmt in tables {
        sqlx::query(stmt).execute(pool).await?;
    }

    // Migrations best-effort : `ALTER TABLE` echoue si la colonne existe deja,
    // exactement comme le `except sqlite3.OperationalError: pass` cote Python.
    let migrations = [
        ("mutes", "unmute_at", "DATETIME"),
        ("mutes", "rules_text", "TEXT"),
        ("mutes", "welcome_channel_id", "INTEGER"),
        ("mutes", "welcome_message", "TEXT"),
        ("mutes", "mod_channel_id", "INTEGER"),
        ("guild_settings", "unmute_at", "DATETIME"),
        ("guild_settings", "rules_text", "TEXT"),
        ("guild_settings", "welcome_channel_id", "INTEGER"),
        ("guild_settings", "welcome_message", "TEXT"),
        ("guild_settings", "mod_channel_id", "INTEGER"),
        ("sanctions", "case_id", "INTEGER"),
    ];
    for (table, col, typedef) in migrations {
        // Noms de tables/colonnes constants, definis juste au-dessus : pas
        // d'entree utilisateur dans cette chaine.
        let _ = sqlx::query(AssertSqlSafe(format!(
            "ALTER TABLE {table} ADD COLUMN {col} {typedef}"
        )))
        .execute(pool)
        .await;
    }

    Ok(())
}

// ── Avertissements ───────────────────────────────────────────────────────────

pub async fn add_warning(
    pool: &SqlitePool,
    guild_id: i64,
    user_id: i64,
    moderator_id: i64,
    reason: &str,
) -> Result<()> {
    sqlx::query(
        "INSERT INTO warnings (guild_id, user_id, moderator_id, reason) VALUES (?, ?, ?, ?)",
    )
    .bind(guild_id)
    .bind(user_id)
    .bind(moderator_id)
    .bind(reason)
    .execute(pool)
    .await?;
    Ok(())
}

pub async fn get_warnings(pool: &SqlitePool, guild_id: i64, user_id: i64) -> Result<Vec<Warning>> {
    let rows = sqlx::query(
        "SELECT id, moderator_id, reason, timestamp FROM warnings \
         WHERE guild_id=? AND user_id=? ORDER BY timestamp DESC",
    )
    .bind(guild_id)
    .bind(user_id)
    .fetch_all(pool)
    .await?;

    Ok(rows
        .into_iter()
        .map(|r| Warning {
            id: r.get("id"),
            moderator_id: r.get("moderator_id"),
            reason: r.get("reason"),
            timestamp: r.get("timestamp"),
        })
        .collect())
}

pub async fn clear_warnings(pool: &SqlitePool, guild_id: i64, user_id: i64) -> Result<()> {
    sqlx::query("DELETE FROM warnings WHERE guild_id=? AND user_id=?")
        .bind(guild_id)
        .bind(user_id)
        .execute(pool)
        .await?;
    Ok(())
}

// ── Mutes ────────────────────────────────────────────────────────────────────

pub async fn add_mute(
    pool: &SqlitePool,
    guild_id: i64,
    user_id: i64,
    moderator_id: i64,
    reason: &str,
    unmute_at: Option<NaiveDateTime>,
) -> Result<()> {
    sqlx::query(
        "INSERT INTO mutes (guild_id, user_id, moderator_id, reason, unmute_at) \
         VALUES (?, ?, ?, ?, ?)",
    )
    .bind(guild_id)
    .bind(user_id)
    .bind(moderator_id)
    .bind(reason)
    .bind(unmute_at.map(to_db_datetime))
    .execute(pool)
    .await?;
    Ok(())
}

pub async fn remove_mute(pool: &SqlitePool, guild_id: i64, user_id: i64) -> Result<()> {
    sqlx::query(
        "UPDATE mutes SET active=0, unmuted_at=CURRENT_TIMESTAMP \
         WHERE guild_id=? AND user_id=? AND active=1",
    )
    .bind(guild_id)
    .bind(user_id)
    .execute(pool)
    .await?;
    Ok(())
}

pub async fn get_active_timed_mutes(pool: &SqlitePool) -> Result<Vec<Expiry>> {
    let rows = sqlx::query(
        "SELECT guild_id, user_id, unmute_at FROM mutes WHERE active=1 AND unmute_at IS NOT NULL",
    )
    .fetch_all(pool)
    .await?;
    Ok(collect_expiries(rows, "unmute_at"))
}

// ── Tempbans ─────────────────────────────────────────────────────────────────

pub async fn add_tempban(
    pool: &SqlitePool,
    guild_id: i64,
    user_id: i64,
    moderator_id: i64,
    reason: &str,
    unban_at: NaiveDateTime,
) -> Result<()> {
    sqlx::query(
        "INSERT INTO tempbans (guild_id, user_id, moderator_id, reason, unban_at) \
         VALUES (?, ?, ?, ?, ?)",
    )
    .bind(guild_id)
    .bind(user_id)
    .bind(moderator_id)
    .bind(reason)
    .bind(to_db_datetime(unban_at))
    .execute(pool)
    .await?;
    Ok(())
}

pub async fn deactivate_tempban(pool: &SqlitePool, guild_id: i64, user_id: i64) -> Result<()> {
    sqlx::query("UPDATE tempbans SET active=0 WHERE guild_id=? AND user_id=? AND active=1")
        .bind(guild_id)
        .bind(user_id)
        .execute(pool)
        .await?;
    Ok(())
}

pub async fn get_active_tempbans(pool: &SqlitePool) -> Result<Vec<Expiry>> {
    let rows = sqlx::query("SELECT guild_id, user_id, unban_at FROM tempbans WHERE active=1")
        .fetch_all(pool)
        .await?;
    Ok(collect_expiries(rows, "unban_at"))
}

/// Les lignes dont la date est illisible sont ignorees, comme le `try/except`
/// qui entoure chaque iteration dans `check_expired_punishments`.
fn collect_expiries(rows: Vec<sqlx::sqlite::SqliteRow>, column: &str) -> Vec<Expiry> {
    rows.into_iter()
        .filter_map(|r| {
            let raw: Option<String> = r.try_get(column).ok()?;
            let dt = parse_db_datetime(&raw?)?;
            Some((r.get("guild_id"), r.get("user_id"), dt))
        })
        .collect()
}

// ── Sanctions / cases ────────────────────────────────────────────────────────

/// Portage de `add_sanction` : alloue le prochain `case_id` de la guilde.
/// La transaction remplace le double aller-retour Python et evite deux
/// sanctions simultanees partageant le meme numero.
pub async fn add_sanction(
    pool: &SqlitePool,
    guild_id: i64,
    user_id: i64,
    moderator_id: i64,
    action: &str,
    reason: Option<&str>,
    duration: Option<&str>,
) -> Result<i64> {
    let mut tx = pool.begin().await?;

    let case_id: i64 =
        sqlx::query("SELECT COALESCE(MAX(case_id), 0) + 1 FROM sanctions WHERE guild_id=?")
            .bind(guild_id)
            .fetch_one(&mut *tx)
            .await?
            .get(0);

    sqlx::query(
        "INSERT INTO sanctions (case_id, guild_id, user_id, moderator_id, action, reason, duration) \
         VALUES (?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(case_id)
    .bind(guild_id)
    .bind(user_id)
    .bind(moderator_id)
    .bind(action)
    .bind(reason)
    .bind(duration)
    .execute(&mut *tx)
    .await?;

    tx.commit().await?;
    Ok(case_id)
}

pub async fn get_case(pool: &SqlitePool, guild_id: i64, case_id: i64) -> Result<Option<CaseRow>> {
    let row = sqlx::query(
        "SELECT case_id, user_id, moderator_id, action, reason, duration, timestamp \
         FROM sanctions WHERE guild_id=? AND case_id=?",
    )
    .bind(guild_id)
    .bind(case_id)
    .fetch_optional(pool)
    .await?;

    Ok(row.map(|r| CaseRow {
        case_id: r.get("case_id"),
        user_id: r.get("user_id"),
        moderator_id: r.get("moderator_id"),
        action: r.get("action"),
        reason: r.get("reason"),
        duration: r.get("duration"),
        timestamp: r.get("timestamp"),
    }))
}

pub async fn edit_case_reason(
    pool: &SqlitePool,
    guild_id: i64,
    case_id: i64,
    new_reason: &str,
) -> Result<bool> {
    let res = sqlx::query("UPDATE sanctions SET reason=? WHERE guild_id=? AND case_id=?")
        .bind(new_reason)
        .bind(guild_id)
        .bind(case_id)
        .execute(pool)
        .await?;
    Ok(res.rows_affected() > 0)
}

pub async fn get_sanctions(
    pool: &SqlitePool,
    guild_id: i64,
    user_id: i64,
) -> Result<Vec<Sanction>> {
    let rows = sqlx::query(
        "SELECT case_id, action, moderator_id, reason, duration, timestamp FROM sanctions \
         WHERE guild_id=? AND user_id=? ORDER BY timestamp DESC",
    )
    .bind(guild_id)
    .bind(user_id)
    .fetch_all(pool)
    .await?;

    Ok(rows
        .into_iter()
        .map(|r| Sanction {
            case_id: r.try_get("case_id").unwrap_or(0),
            action: r.get("action"),
            moderator_id: r.get("moderator_id"),
            reason: r.get("reason"),
            duration: r.get("duration"),
            timestamp: r.get("timestamp"),
        })
        .collect())
}

// ── Points de violation ──────────────────────────────────────────────────────

/// Portage de `get_violation_points` : les points expirent apres 24 h.
/// Aucun cog Python ne l'appelle (`add_violation_points` renvoie deja le
/// total) ; conserve pour la parite avec `utils/database.py`.
#[allow(dead_code)]
pub async fn get_violation_points(pool: &SqlitePool, guild_id: i64, user_id: i64) -> Result<i64> {
    let row = sqlx::query(
        "SELECT points, last_violation FROM violation_points WHERE guild_id=? AND user_id=?",
    )
    .bind(guild_id)
    .bind(user_id)
    .fetch_optional(pool)
    .await?;

    let Some(row) = row else { return Ok(0) };
    let points: i64 = row.get("points");
    let last: Option<String> = row.try_get("last_violation").ok().flatten();

    if let Some(last_str) = last {
        if let Some(last_dt) = parse_db_datetime(&last_str) {
            let elapsed = chrono::Utc::now().naive_utc() - last_dt;
            if elapsed.num_seconds() > 86400 {
                return Ok(0);
            }
        }
    }
    Ok(points)
}

pub async fn add_violation_points(
    pool: &SqlitePool,
    guild_id: i64,
    user_id: i64,
    points: i64,
) -> Result<i64> {
    sqlx::query(
        "INSERT INTO violation_points (guild_id, user_id, points, last_violation) \
         VALUES (?, ?, ?, CURRENT_TIMESTAMP) \
         ON CONFLICT(guild_id, user_id) DO UPDATE SET \
         points = points + ?, last_violation = CURRENT_TIMESTAMP",
    )
    .bind(guild_id)
    .bind(user_id)
    .bind(points)
    .bind(points)
    .execute(pool)
    .await?;

    let row = sqlx::query("SELECT points FROM violation_points WHERE guild_id=? AND user_id=?")
        .bind(guild_id)
        .bind(user_id)
        .fetch_optional(pool)
        .await?;

    Ok(row.map(|r| r.get("points")).unwrap_or(points))
}

pub async fn reset_violation_points(pool: &SqlitePool, guild_id: i64, user_id: i64) -> Result<()> {
    sqlx::query("UPDATE violation_points SET points=0 WHERE guild_id=? AND user_id=?")
        .bind(guild_id)
        .bind(user_id)
        .execute(pool)
        .await?;
    Ok(())
}

// ── Blacklist de mots ────────────────────────────────────────────────────────

/// Portage de `add_blacklist_word`. Aucun cog Python ne l'appelle : conserve
/// pour la parite fonctionnelle avec `utils/database.py`.
#[allow(dead_code)]
pub async fn add_blacklist_word(
    pool: &SqlitePool,
    guild_id: i64,
    word: &str,
    added_by: i64,
) -> Result<()> {
    sqlx::query("INSERT INTO word_blacklist (guild_id, word, added_by) VALUES (?, ?, ?)")
        .bind(guild_id)
        .bind(word.to_lowercase())
        .bind(added_by)
        .execute(pool)
        .await?;
    Ok(())
}

#[allow(dead_code)]
pub async fn remove_blacklist_word(pool: &SqlitePool, guild_id: i64, word: &str) -> Result<bool> {
    let res = sqlx::query("DELETE FROM word_blacklist WHERE guild_id=? AND word=?")
        .bind(guild_id)
        .bind(word.to_lowercase())
        .execute(pool)
        .await?;
    Ok(res.rows_affected() > 0)
}

pub async fn get_blacklist_words(pool: &SqlitePool, guild_id: i64) -> Result<Vec<String>> {
    let rows = sqlx::query("SELECT word FROM word_blacklist WHERE guild_id=?")
        .bind(guild_id)
        .fetch_all(pool)
        .await?;
    Ok(rows.into_iter().map(|r| r.get("word")).collect())
}

// ── Config auto-mod ──────────────────────────────────────────────────────────

pub async fn get_automod_config(pool: &SqlitePool, guild_id: i64) -> Result<AutomodConfig> {
    let row = sqlx::query(
        "SELECT spam_threshold, spam_interval, max_mentions, caps_detection, caps_min_length, \
         caps_percent, file_flood_limit, file_flood_interval, pts_warn, pts_mute, \
         pts_mute_duration, pts_kick, pts_ban, pts_ban_duration \
         FROM automod_config WHERE guild_id=?",
    )
    .bind(guild_id)
    .fetch_optional(pool)
    .await?;

    let Some(r) = row else {
        return Ok(AutomodConfig::default());
    };

    Ok(AutomodConfig {
        spam_threshold: r.get("spam_threshold"),
        spam_interval: r.get("spam_interval"),
        max_mentions: r.get("max_mentions"),
        caps_detection: r.get::<i64, _>("caps_detection") != 0,
        caps_min_length: r.get("caps_min_length"),
        caps_percent: r.get("caps_percent"),
        file_flood_limit: r.get("file_flood_limit"),
        file_flood_interval: r.get("file_flood_interval"),
        pts_warn: r.get("pts_warn"),
        pts_mute: r.get("pts_mute"),
        pts_mute_duration: r.get("pts_mute_duration"),
        pts_kick: r.get("pts_kick"),
        pts_ban: r.get("pts_ban"),
        pts_ban_duration: r.get("pts_ban_duration"),
    })
}

/// Portage de `update_automod_config` (read-modify-write sur la ligne entiere).
#[allow(dead_code)]
pub async fn update_automod_config(
    pool: &SqlitePool,
    guild_id: i64,
    cfg: AutomodConfig,
) -> Result<()> {
    sqlx::query(
        "INSERT OR REPLACE INTO automod_config (guild_id, spam_threshold, spam_interval, \
         max_mentions, caps_detection, caps_min_length, caps_percent, file_flood_limit, \
         file_flood_interval, pts_warn, pts_mute, pts_mute_duration, pts_kick, pts_ban, \
         pts_ban_duration) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(guild_id)
    .bind(cfg.spam_threshold)
    .bind(cfg.spam_interval)
    .bind(cfg.max_mentions)
    .bind(cfg.caps_detection as i64)
    .bind(cfg.caps_min_length)
    .bind(cfg.caps_percent)
    .bind(cfg.file_flood_limit)
    .bind(cfg.file_flood_interval)
    .bind(cfg.pts_warn)
    .bind(cfg.pts_mute)
    .bind(cfg.pts_mute_duration)
    .bind(cfg.pts_kick)
    .bind(cfg.pts_ban)
    .bind(cfg.pts_ban_duration)
    .execute(pool)
    .await?;
    Ok(())
}

// ── Reglages de guilde ───────────────────────────────────────────────────────

const SETTINGS_SELECT: &str = "SELECT log_channel_id, mute_role_id, automod_enabled, \
     spam_detection, rules_text, welcome_channel_id, welcome_message, mod_channel_id \
     FROM guild_settings WHERE guild_id=?";

pub async fn get_guild_settings(
    pool: &SqlitePool,
    guild_id: i64,
) -> Result<Option<GuildSettings>> {
    let row = sqlx::query(SETTINGS_SELECT)
        .bind(guild_id)
        .fetch_optional(pool)
        .await?;

    Ok(row.map(|r| GuildSettings {
        log_channel_id: r.try_get("log_channel_id").ok().flatten(),
        mute_role_id: r.try_get("mute_role_id").ok().flatten(),
        automod_enabled: r.try_get::<Option<i64>, _>("automod_enabled").ok().flatten().unwrap_or(1) != 0,
        spam_detection: r.try_get::<Option<i64>, _>("spam_detection").ok().flatten().unwrap_or(1) != 0,
        rules_text: r.try_get("rules_text").ok().flatten(),
        welcome_channel_id: r.try_get("welcome_channel_id").ok().flatten(),
        welcome_message: r.try_get("welcome_message").ok().flatten(),
        mod_channel_id: r.try_get("mod_channel_id").ok().flatten(),
    }))
}

/// Portage de `update_guild_settings(**kwargs)` : lit la ligne courante,
/// applique le patch, reecrit tout via `INSERT OR REPLACE`.
pub async fn update_guild_settings(
    pool: &SqlitePool,
    guild_id: i64,
    patch: GuildSettingsPatch,
) -> Result<()> {
    let mut current = get_guild_settings(pool, guild_id)
        .await?
        .unwrap_or(GuildSettings {
            automod_enabled: true,
            spam_detection: true,
            ..Default::default()
        });

    if let Some(v) = patch.log_channel_id {
        current.log_channel_id = v;
    }
    if let Some(v) = patch.mute_role_id {
        current.mute_role_id = v;
    }
    if let Some(v) = patch.automod_enabled {
        current.automod_enabled = v;
    }
    if let Some(v) = patch.spam_detection {
        current.spam_detection = v;
    }
    if let Some(v) = patch.rules_text {
        current.rules_text = v;
    }
    if let Some(v) = patch.welcome_channel_id {
        current.welcome_channel_id = v;
    }
    if let Some(v) = patch.welcome_message {
        current.welcome_message = v;
    }
    if let Some(v) = patch.mod_channel_id {
        current.mod_channel_id = v;
    }

    sqlx::query(
        "INSERT OR REPLACE INTO guild_settings \
         (guild_id, log_channel_id, mute_role_id, automod_enabled, spam_detection, \
          rules_text, welcome_channel_id, welcome_message, mod_channel_id) \
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(guild_id)
    .bind(current.log_channel_id)
    .bind(current.mute_role_id)
    .bind(current.automod_enabled as i64)
    .bind(current.spam_detection as i64)
    .bind(current.rules_text.as_deref())
    .bind(current.welcome_channel_id)
    .bind(current.welcome_message.as_deref())
    .bind(current.mod_channel_id)
    .execute(pool)
    .await?;

    Ok(())
}
