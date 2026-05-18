import sqlite3
import re
from datetime import datetime, timedelta
from config import DATABASE_PATH

# ---------------------------------------------------------------------------
# Automod config defaults
# ---------------------------------------------------------------------------

AUTOMOD_DEFAULTS = {
    'spam_threshold': 5,
    'spam_interval': 10,
    'max_mentions': 5,
    'caps_detection': 1,
    'caps_min_length': 10,
    'caps_percent': 70,
    'file_flood_limit': 5,
    'file_flood_interval': 30,
    'pts_warn': 5,
    'pts_mute': 10,
    'pts_mute_duration': 600,
    'pts_kick': 15,
    'pts_ban': 20,
    'pts_ban_duration': 3600,
}

AUTOMOD_CONFIG_COLS = [
    'guild_id', 'spam_threshold', 'spam_interval', 'max_mentions',
    'caps_detection', 'caps_min_length', 'caps_percent',
    'file_flood_limit', 'file_flood_interval',
    'pts_warn', 'pts_mute', 'pts_mute_duration',
    'pts_kick', 'pts_ban', 'pts_ban_duration',
]


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

def init_db():
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS warnings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
        moderator_id INTEGER NOT NULL, reason TEXT NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS mutes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
        moderator_id INTEGER NOT NULL, reason TEXT NOT NULL,
        muted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        unmuted_at DATETIME, unmute_at DATETIME, active BOOLEAN DEFAULT 1
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS guild_settings (
        guild_id INTEGER PRIMARY KEY,
        log_channel_id INTEGER, mute_role_id INTEGER,
        automod_enabled BOOLEAN DEFAULT 1, spam_detection BOOLEAN DEFAULT 1,
        rules_text TEXT, welcome_channel_id INTEGER, welcome_message TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS tempbans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
        moderator_id INTEGER NOT NULL, reason TEXT NOT NULL,
        banned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        unban_at DATETIME NOT NULL, active BOOLEAN DEFAULT 1
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS sanctions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        case_id INTEGER,
        guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
        moderator_id INTEGER NOT NULL, action TEXT NOT NULL,
        reason TEXT, duration TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS word_blacklist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL, word TEXT NOT NULL,
        added_by INTEGER NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS violation_points (
        guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
        points INTEGER DEFAULT 0,
        last_violation DATETIME DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (guild_id, user_id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS automod_config (
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
    )''')

    # Migrations
    for col, typedef in [
        ('unmute_at', 'DATETIME'),
        ('rules_text', 'TEXT'),
        ('welcome_channel_id', 'INTEGER'),
        ('welcome_message', 'TEXT'),
    ]:
        try:
            c.execute(f'ALTER TABLE mutes ADD COLUMN {col} {typedef}')
        except sqlite3.OperationalError:
            pass
        try:
            c.execute(f'ALTER TABLE guild_settings ADD COLUMN {col} {typedef}')
        except sqlite3.OperationalError:
            pass

    try:
        c.execute('ALTER TABLE sanctions ADD COLUMN case_id INTEGER')
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Duration helpers
# ---------------------------------------------------------------------------

def parse_duration(duration_str: str) -> int | None:
    pattern = re.fullmatch(r'(\d+)([smhd])', duration_str.strip().lower())
    if not pattern:
        return None
    value, unit = int(pattern.group(1)), pattern.group(2)
    return value * {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}[unit]


def format_duration(seconds: int) -> str:
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
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.execute(
            'INSERT INTO warnings (guild_id, user_id, moderator_id, reason) VALUES (?, ?, ?, ?)',
            (guild_id, user_id, moderator_id, reason)
        )


def get_warnings(guild_id: int, user_id: int):
    with sqlite3.connect(DATABASE_PATH) as conn:
        return conn.execute(
            'SELECT id, moderator_id, reason, timestamp FROM warnings WHERE guild_id=? AND user_id=? ORDER BY timestamp DESC',
            (guild_id, user_id)
        ).fetchall()


def clear_warnings(guild_id: int, user_id: int):
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.execute('DELETE FROM warnings WHERE guild_id=? AND user_id=?', (guild_id, user_id))


# ---------------------------------------------------------------------------
# Mutes
# ---------------------------------------------------------------------------

def add_mute(guild_id: int, user_id: int, moderator_id: int, reason: str, unmute_at: datetime = None):
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.execute(
            'INSERT INTO mutes (guild_id, user_id, moderator_id, reason, unmute_at) VALUES (?, ?, ?, ?, ?)',
            (guild_id, user_id, moderator_id, reason, unmute_at.isoformat() if unmute_at else None)
        )


def remove_mute(guild_id: int, user_id: int):
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.execute(
            'UPDATE mutes SET active=0, unmuted_at=CURRENT_TIMESTAMP WHERE guild_id=? AND user_id=? AND active=1',
            (guild_id, user_id)
        )


def get_active_timed_mutes():
    with sqlite3.connect(DATABASE_PATH) as conn:
        return conn.execute(
            'SELECT guild_id, user_id, unmute_at FROM mutes WHERE active=1 AND unmute_at IS NOT NULL'
        ).fetchall()


# ---------------------------------------------------------------------------
# Tempbans
# ---------------------------------------------------------------------------

def add_tempban(guild_id: int, user_id: int, moderator_id: int, reason: str, unban_at: datetime):
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.execute(
            'INSERT INTO tempbans (guild_id, user_id, moderator_id, reason, unban_at) VALUES (?, ?, ?, ?, ?)',
            (guild_id, user_id, moderator_id, reason, unban_at.isoformat())
        )


def deactivate_tempban(guild_id: int, user_id: int):
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.execute(
            'UPDATE tempbans SET active=0 WHERE guild_id=? AND user_id=? AND active=1',
            (guild_id, user_id)
        )


def get_active_tempbans():
    with sqlite3.connect(DATABASE_PATH) as conn:
        return conn.execute(
            'SELECT guild_id, user_id, unban_at FROM tempbans WHERE active=1'
        ).fetchall()


# ---------------------------------------------------------------------------
# Sanctions (avec case_id par guild)
# ---------------------------------------------------------------------------

def add_sanction(guild_id: int, user_id: int, moderator_id: int, action: str,
                 reason: str = None, duration: str = None) -> int:
    with sqlite3.connect(DATABASE_PATH) as conn:
        row = conn.execute(
            'SELECT COALESCE(MAX(case_id), 0) + 1 FROM sanctions WHERE guild_id=?',
            (guild_id,)
        ).fetchone()
        case_id = row[0] if row else 1
        conn.execute(
            'INSERT INTO sanctions (case_id, guild_id, user_id, moderator_id, action, reason, duration) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (case_id, guild_id, user_id, moderator_id, action, reason, duration)
        )
        return case_id


def get_case(guild_id: int, case_id: int):
    with sqlite3.connect(DATABASE_PATH) as conn:
        return conn.execute(
            'SELECT case_id, user_id, moderator_id, action, reason, duration, timestamp FROM sanctions WHERE guild_id=? AND case_id=?',
            (guild_id, case_id)
        ).fetchone()


def edit_case_reason(guild_id: int, case_id: int, new_reason: str) -> bool:
    with sqlite3.connect(DATABASE_PATH) as conn:
        c = conn.execute(
            'UPDATE sanctions SET reason=? WHERE guild_id=? AND case_id=?',
            (new_reason, guild_id, case_id)
        )
        return c.rowcount > 0


def get_sanctions(guild_id: int, user_id: int):
    with sqlite3.connect(DATABASE_PATH) as conn:
        return conn.execute(
            'SELECT case_id, action, moderator_id, reason, duration, timestamp FROM sanctions WHERE guild_id=? AND user_id=? ORDER BY timestamp DESC',
            (guild_id, user_id)
        ).fetchall()


# ---------------------------------------------------------------------------
# Violation points
# ---------------------------------------------------------------------------

def get_violation_points(guild_id: int, user_id: int) -> int:
    with sqlite3.connect(DATABASE_PATH) as conn:
        row = conn.execute(
            'SELECT points, last_violation FROM violation_points WHERE guild_id=? AND user_id=?',
            (guild_id, user_id)
        ).fetchone()
    if not row:
        return 0
    points, last_str = row
    if last_str:
        last_dt = datetime.fromisoformat(last_str)
        if (datetime.utcnow() - last_dt).total_seconds() > 86400:
            return 0
    return points


def add_violation_points(guild_id: int, user_id: int, points: int) -> int:
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.execute(
            '''INSERT INTO violation_points (guild_id, user_id, points, last_violation)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(guild_id, user_id) DO UPDATE SET
               points = points + ?, last_violation = CURRENT_TIMESTAMP''',
            (guild_id, user_id, points, points)
        )
        row = conn.execute(
            'SELECT points FROM violation_points WHERE guild_id=? AND user_id=?',
            (guild_id, user_id)
        ).fetchone()
        return row[0] if row else points


def reset_violation_points(guild_id: int, user_id: int):
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.execute(
            'UPDATE violation_points SET points=0 WHERE guild_id=? AND user_id=?',
            (guild_id, user_id)
        )


# ---------------------------------------------------------------------------
# Blacklist
# ---------------------------------------------------------------------------

def add_blacklist_word(guild_id: int, word: str, added_by: int):
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.execute(
            'INSERT INTO word_blacklist (guild_id, word, added_by) VALUES (?, ?, ?)',
            (guild_id, word.lower(), added_by)
        )


def remove_blacklist_word(guild_id: int, word: str) -> bool:
    with sqlite3.connect(DATABASE_PATH) as conn:
        c = conn.execute(
            'DELETE FROM word_blacklist WHERE guild_id=? AND word=?',
            (guild_id, word.lower())
        )
        return c.rowcount > 0


def get_blacklist_words(guild_id: int) -> list[str]:
    with sqlite3.connect(DATABASE_PATH) as conn:
        return [r[0] for r in conn.execute(
            'SELECT word FROM word_blacklist WHERE guild_id=?', (guild_id,)
        ).fetchall()]


# ---------------------------------------------------------------------------
# Automod config
# ---------------------------------------------------------------------------

def get_automod_config(guild_id: int) -> dict:
    with sqlite3.connect(DATABASE_PATH) as conn:
        row = conn.execute(
            'SELECT * FROM automod_config WHERE guild_id=?', (guild_id,)
        ).fetchone()
    if not row:
        return AUTOMOD_DEFAULTS.copy()
    config = dict(zip(AUTOMOD_CONFIG_COLS, row))
    config.pop('guild_id', None)
    return config


def update_automod_config(guild_id: int, **kwargs):
    current = get_automod_config(guild_id)
    current.update(kwargs)
    cols = [c for c in AUTOMOD_CONFIG_COLS if c != 'guild_id']
    placeholders = ', '.join(f'{c}=?' for c in cols)
    values = [current[c] for c in cols] + [guild_id]
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.execute(
            f'''INSERT OR REPLACE INTO automod_config (guild_id, {", ".join(cols)})
                VALUES (?, {", ".join("?" for _ in cols)})''',
            [guild_id] + [current[c] for c in cols]
        )


# ---------------------------------------------------------------------------
# Guild settings
# ---------------------------------------------------------------------------

def get_guild_settings(guild_id: int):
    with sqlite3.connect(DATABASE_PATH) as conn:
        return conn.execute(
            'SELECT log_channel_id, mute_role_id, automod_enabled, spam_detection, rules_text, welcome_channel_id, welcome_message FROM guild_settings WHERE guild_id=?',
            (guild_id,)
        ).fetchone()


def update_guild_settings(guild_id: int, **kwargs):
    with sqlite3.connect(DATABASE_PATH) as conn:
        row = conn.execute(
            'SELECT log_channel_id, mute_role_id, automod_enabled, spam_detection, rules_text, welcome_channel_id, welcome_message FROM guild_settings WHERE guild_id=?',
            (guild_id,)
        ).fetchone()

    current = dict(zip(
        ['log_channel_id', 'mute_role_id', 'automod_enabled', 'spam_detection', 'rules_text', 'welcome_channel_id', 'welcome_message'],
        row
    )) if row else {
        'log_channel_id': None, 'mute_role_id': None,
        'automod_enabled': 1, 'spam_detection': 1,
        'rules_text': None, 'welcome_channel_id': None, 'welcome_message': None,
    }
    current.update(kwargs)

    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.execute(
            '''INSERT OR REPLACE INTO guild_settings
               (guild_id, log_channel_id, mute_role_id, automod_enabled, spam_detection, rules_text, welcome_channel_id, welcome_message)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (guild_id, current['log_channel_id'], current['mute_role_id'],
             current['automod_enabled'], current['spam_detection'],
             current['rules_text'], current['welcome_channel_id'], current['welcome_message'])
        )
