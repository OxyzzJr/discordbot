import sqlite3
import re
from datetime import datetime, timedelta
from config import DATABASE_PATH


def init_db():
    """Initialize the database with required tables"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mutes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            muted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            unmuted_at DATETIME,
            unmute_at DATETIME,
            active BOOLEAN DEFAULT 1
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS guild_settings (
            guild_id INTEGER PRIMARY KEY,
            log_channel_id INTEGER,
            mute_role_id INTEGER,
            automod_enabled BOOLEAN DEFAULT 1,
            spam_detection BOOLEAN DEFAULT 1,
            rules_text TEXT,
            welcome_channel_id INTEGER,
            welcome_message TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tempbans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            banned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            unban_at DATETIME NOT NULL,
            active BOOLEAN DEFAULT 1
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sanctions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            reason TEXT,
            duration TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS word_blacklist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            word TEXT NOT NULL,
            added_by INTEGER NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Migrate existing mutes table if unmute_at column is missing
    try:
        cursor.execute('ALTER TABLE mutes ADD COLUMN unmute_at DATETIME')
    except sqlite3.OperationalError:
        pass

    # Migrate guild_settings if new columns are missing
    for col in ('rules_text TEXT', 'welcome_channel_id INTEGER', 'welcome_message TEXT'):
        try:
            cursor.execute(f'ALTER TABLE guild_settings ADD COLUMN {col}')
        except sqlite3.OperationalError:
            pass

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Duration parser
# ---------------------------------------------------------------------------

def parse_duration(duration_str: str) -> int | None:
    """Convert '10m', '2h', '1d' etc. into seconds. Returns None if invalid."""
    pattern = re.fullmatch(r'(\d+)([smhd])', duration_str.strip().lower())
    if not pattern:
        return None
    value, unit = int(pattern.group(1)), pattern.group(2)
    multipliers = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}
    return value * multipliers[unit]


def format_duration(seconds: int) -> str:
    """Convert seconds to a human-readable French string."""
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        m = seconds // 60
        return f"{m} minute{'s' if m > 1 else ''}"
    if seconds < 86400:
        h = seconds // 3600
        return f"{h} heure{'s' if h > 1 else ''}"
    d = seconds // 86400
    return f"{d} jour{'s' if d > 1 else ''}"


# ---------------------------------------------------------------------------
# Warnings
# ---------------------------------------------------------------------------

def add_warning(guild_id: int, user_id: int, moderator_id: int, reason: str):
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO warnings (guild_id, user_id, moderator_id, reason) VALUES (?, ?, ?, ?)',
        (guild_id, user_id, moderator_id, reason)
    )
    conn.commit()
    conn.close()


def get_warnings(guild_id: int, user_id: int):
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute(
        'SELECT id, moderator_id, reason, timestamp FROM warnings WHERE guild_id = ? AND user_id = ? ORDER BY timestamp DESC',
        (guild_id, user_id)
    )
    warnings = cursor.fetchall()
    conn.close()
    return warnings


def clear_warnings(guild_id: int, user_id: int):
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM warnings WHERE guild_id = ? AND user_id = ?', (guild_id, user_id))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Mutes
# ---------------------------------------------------------------------------

def add_mute(guild_id: int, user_id: int, moderator_id: int, reason: str, unmute_at: datetime = None):
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO mutes (guild_id, user_id, moderator_id, reason, unmute_at) VALUES (?, ?, ?, ?, ?)',
        (guild_id, user_id, moderator_id, reason, unmute_at.isoformat() if unmute_at else None)
    )
    conn.commit()
    conn.close()


def remove_mute(guild_id: int, user_id: int):
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE mutes SET active = 0, unmuted_at = CURRENT_TIMESTAMP WHERE guild_id = ? AND user_id = ? AND active = 1',
        (guild_id, user_id)
    )
    conn.commit()
    conn.close()


def get_active_timed_mutes():
    """Return all active mutes that have an expiry time (for bot restart recovery)."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute(
        'SELECT guild_id, user_id, unmute_at FROM mutes WHERE active = 1 AND unmute_at IS NOT NULL'
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# Tempbans
# ---------------------------------------------------------------------------

def add_tempban(guild_id: int, user_id: int, moderator_id: int, reason: str, unban_at: datetime):
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO tempbans (guild_id, user_id, moderator_id, reason, unban_at) VALUES (?, ?, ?, ?, ?)',
        (guild_id, user_id, moderator_id, reason, unban_at.isoformat())
    )
    conn.commit()
    conn.close()


def deactivate_tempban(guild_id: int, user_id: int):
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE tempbans SET active = 0 WHERE guild_id = ? AND user_id = ? AND active = 1',
        (guild_id, user_id)
    )
    conn.commit()
    conn.close()


def get_active_tempbans():
    """Return all active tempbans (for background task and restart recovery)."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT guild_id, user_id, unban_at FROM tempbans WHERE active = 1')
    rows = cursor.fetchall()
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# Sanctions log
# ---------------------------------------------------------------------------

def add_sanction(guild_id: int, user_id: int, moderator_id: int, action: str,
                 reason: str = None, duration: str = None):
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO sanctions (guild_id, user_id, moderator_id, action, reason, duration) VALUES (?, ?, ?, ?, ?, ?)',
        (guild_id, user_id, moderator_id, action, reason, duration)
    )
    conn.commit()
    conn.close()


def get_sanctions(guild_id: int, user_id: int):
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute(
        'SELECT action, moderator_id, reason, duration, timestamp FROM sanctions WHERE guild_id = ? AND user_id = ? ORDER BY timestamp DESC',
        (guild_id, user_id)
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# Word blacklist
# ---------------------------------------------------------------------------

def add_blacklist_word(guild_id: int, word: str, added_by: int):
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO word_blacklist (guild_id, word, added_by) VALUES (?, ?, ?)',
        (guild_id, word.lower(), added_by)
    )
    conn.commit()
    conn.close()


def remove_blacklist_word(guild_id: int, word: str) -> bool:
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute(
        'DELETE FROM word_blacklist WHERE guild_id = ? AND word = ?',
        (guild_id, word.lower())
    )
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def get_blacklist_words(guild_id: int):
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT word FROM word_blacklist WHERE guild_id = ?', (guild_id,))
    rows = [row[0] for row in cursor.fetchall()]
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# Guild settings
# ---------------------------------------------------------------------------

def get_guild_settings(guild_id: int):
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute(
        'SELECT log_channel_id, mute_role_id, automod_enabled, spam_detection, rules_text, welcome_channel_id, welcome_message FROM guild_settings WHERE guild_id = ?',
        (guild_id,)
    )
    result = cursor.fetchone()
    conn.close()
    return result


def update_guild_settings(guild_id: int, **kwargs):
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    # Fetch current row first so we don't overwrite unrelated columns
    cursor.execute('SELECT log_channel_id, mute_role_id, automod_enabled, spam_detection, rules_text, welcome_channel_id, welcome_message FROM guild_settings WHERE guild_id = ?', (guild_id,))
    row = cursor.fetchone()
    if row:
        current = {
            'log_channel_id': row[0],
            'mute_role_id': row[1],
            'automod_enabled': row[2],
            'spam_detection': row[3],
            'rules_text': row[4],
            'welcome_channel_id': row[5],
            'welcome_message': row[6],
        }
    else:
        current = {
            'log_channel_id': None,
            'mute_role_id': None,
            'automod_enabled': 1,
            'spam_detection': 1,
            'rules_text': None,
            'welcome_channel_id': None,
            'welcome_message': None,
        }

    current.update(kwargs)

    cursor.execute(
        'INSERT OR REPLACE INTO guild_settings (guild_id, log_channel_id, mute_role_id, automod_enabled, spam_detection, rules_text, welcome_channel_id, welcome_message) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        (guild_id, current['log_channel_id'], current['mute_role_id'], current['automod_enabled'],
         current['spam_detection'], current['rules_text'], current['welcome_channel_id'], current['welcome_message'])
    )
    conn.commit()
    conn.close()
