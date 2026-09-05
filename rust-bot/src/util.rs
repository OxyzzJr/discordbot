//! Helpers partages : parsing de durees, formatage FR, dates SQLite, embeds.

use chrono::NaiveDateTime;
use once_cell::sync::Lazy;
use poise::serenity_prelude as serenity;
use regex::Regex;

static DURATION_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"^(\d+)([smhd])$").unwrap());

/// Portage de `parse_duration` : `10m`, `2h`, `1d`... -> secondes.
pub fn parse_duration(input: &str) -> Option<i64> {
    let cleaned = input.trim().to_lowercase();
    let caps = DURATION_RE.captures(&cleaned)?;
    let value: i64 = caps.get(1)?.as_str().parse().ok()?;
    let mult = match caps.get(2)?.as_str() {
        "s" => 1,
        "m" => 60,
        "h" => 3600,
        "d" => 86400,
        _ => return None,
    };
    Some(value * mult)
}

/// Portage de `format_duration` : secondes -> libelle francais.
pub fn format_duration(seconds: i64) -> String {
    if seconds < 60 {
        return format!("{seconds}s");
    }
    if seconds < 3600 {
        let m = seconds / 60;
        return format!("{m} minute{}", if m > 1 { "s" } else { "" });
    }
    if seconds < 86400 {
        let h = seconds / 3600;
        return format!("{h} heure{}", if h > 1 { "s" } else { "" });
    }
    let d = seconds / 86400;
    format!("{d} jour{}", if d > 1 { "s" } else { "" })
}

/// Les timestamps en base viennent soit de `CURRENT_TIMESTAMP`
/// (`YYYY-MM-DD HH:MM:SS`), soit de `datetime.isoformat()` cote Python
/// (`YYYY-MM-DDTHH:MM:SS[.ffffff]`). On accepte les deux, comme
/// `datetime.fromisoformat`.
pub fn parse_db_datetime(raw: &str) -> Option<NaiveDateTime> {
    let raw = raw.trim();
    for fmt in [
        "%Y-%m-%dT%H:%M:%S%.f",
        "%Y-%m-%d %H:%M:%S%.f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ] {
        if let Ok(dt) = NaiveDateTime::parse_from_str(raw, fmt) {
            return Some(dt);
        }
    }
    None
}

/// Serialise comme `datetime.isoformat()` pour rester lisible par l'ancien code.
pub fn to_db_datetime(dt: NaiveDateTime) -> String {
    dt.format("%Y-%m-%dT%H:%M:%S%.6f").to_string()
}

/// `<t:...:F>` / `<t:...:R>` — horodatages dynamiques Discord.
pub fn ts_full(dt: &chrono::DateTime<chrono::Utc>) -> String {
    format!("<t:{}:F>", dt.timestamp())
}

pub fn ts_date(dt: &chrono::DateTime<chrono::Utc>) -> String {
    format!("<t:{}:D>", dt.timestamp())
}

pub fn ts_relative(dt: Option<&chrono::DateTime<chrono::Utc>>) -> String {
    match dt {
        Some(d) => format!("<t:{}:R>", d.timestamp()),
        None => "Inconnu".to_string(),
    }
}

/// Embed minimal titre + couleur, utilise pour les messages d'erreur courts.
pub fn simple_embed(title: &str, color: u32) -> serenity::CreateEmbed {
    serenity::CreateEmbed::new().title(title).color(color)
}

/// Tronque une valeur pour respecter la limite Discord d'un champ d'embed.
pub fn truncate(text: &str, max: usize) -> String {
    if text.chars().count() <= max {
        return text.to_string();
    }
    let head: String = text.chars().take(max).collect();
    format!("{head}…")
}

/// Un champ d'embed ne peut pas etre vide cote Discord.
pub fn non_empty(text: &str) -> String {
    if text.trim().is_empty() {
        "—".to_string()
    } else {
        text.to_string()
    }
}
