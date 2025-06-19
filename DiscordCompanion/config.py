import os
from dotenv import load_dotenv

load_dotenv()

# Bot Configuration
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN', '')

# Moderation Settings
MAX_WARNINGS = int(os.getenv('MAX_WARNINGS', 3))
MUTE_ROLE_NAME = os.getenv('MUTE_ROLE_NAME', 'Muted')
LOG_CHANNEL_NAME = os.getenv('LOG_CHANNEL_NAME', 'mod-logs')

# Auto-moderation Settings
SPAM_THRESHOLD = int(os.getenv('SPAM_THRESHOLD', 5))
SPAM_INTERVAL = int(os.getenv('SPAM_INTERVAL', 10))
MAX_MENTIONS = int(os.getenv('MAX_MENTIONS', 5))

# Database
DATABASE_PATH = 'moderation.db'

# Colors for embeds
COLORS = {
    'success': 0x00ff00,
    'error': 0xff0000,
    'warning': 0xffff00,
    'info': 0x0099ff
}
