import sqlite3
import asyncio
from datetime import datetime
from config import DATABASE_PATH

def init_db():
    """Initialize the database with required tables"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # Warnings table
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
    
    # Mutes table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mutes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            muted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            unmuted_at DATETIME,
            active BOOLEAN DEFAULT 1
        )
    ''')
    
    # Guild settings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS guild_settings (
            guild_id INTEGER PRIMARY KEY,
            log_channel_id INTEGER,
            mute_role_id INTEGER,
            automod_enabled BOOLEAN DEFAULT 1,
            spam_detection BOOLEAN DEFAULT 1
        )
    ''')
    
    conn.commit()
    conn.close()

def add_warning(guild_id: int, user_id: int, moderator_id: int, reason: str):
    """Add a warning to the database"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO warnings (guild_id, user_id, moderator_id, reason)
        VALUES (?, ?, ?, ?)
    ''', (guild_id, user_id, moderator_id, reason))
    
    conn.commit()
    conn.close()

def get_warnings(guild_id: int, user_id: int):
    """Get all warnings for a user in a guild"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT id, moderator_id, reason, timestamp
        FROM warnings
        WHERE guild_id = ? AND user_id = ?
        ORDER BY timestamp DESC
    ''', (guild_id, user_id))
    
    warnings = cursor.fetchall()
    conn.close()
    return warnings

def clear_warnings(guild_id: int, user_id: int):
    """Clear all warnings for a user in a guild"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        DELETE FROM warnings
        WHERE guild_id = ? AND user_id = ?
    ''', (guild_id, user_id))
    
    conn.commit()
    conn.close()

def add_mute(guild_id: int, user_id: int, moderator_id: int, reason: str):
    """Add a mute record to the database"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO mutes (guild_id, user_id, moderator_id, reason)
        VALUES (?, ?, ?, ?)
    ''', (guild_id, user_id, moderator_id, reason))
    
    conn.commit()
    conn.close()

def remove_mute(guild_id: int, user_id: int):
    """Mark a mute as inactive"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE mutes
        SET active = 0, unmuted_at = CURRENT_TIMESTAMP
        WHERE guild_id = ? AND user_id = ? AND active = 1
    ''', (guild_id, user_id))
    
    conn.commit()
    conn.close()

def get_guild_settings(guild_id: int):
    """Get guild settings"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT log_channel_id, mute_role_id, automod_enabled, spam_detection
        FROM guild_settings
        WHERE guild_id = ?
    ''', (guild_id,))
    
    result = cursor.fetchone()
    conn.close()
    return result

def update_guild_settings(guild_id: int, **kwargs):
    """Update guild settings"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # Insert or update guild settings
    cursor.execute('''
        INSERT OR REPLACE INTO guild_settings 
        (guild_id, log_channel_id, mute_role_id, automod_enabled, spam_detection)
        VALUES (?, ?, ?, ?, ?)
    ''', (
        guild_id,
        kwargs.get('log_channel_id'),
        kwargs.get('mute_role_id'),
        kwargs.get('automod_enabled', 1),
        kwargs.get('spam_detection', 1)
    ))
    
    conn.commit()
    conn.close()
