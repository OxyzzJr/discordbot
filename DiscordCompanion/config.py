import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN', '')

MAX_WARNINGS = int(os.getenv('MAX_WARNINGS', 3))
MUTE_ROLE_NAME = os.getenv('MUTE_ROLE_NAME', 'Muted')
LOG_CHANNEL_NAME = os.getenv('LOG_CHANNEL_NAME', 'mod-logs')

SPAM_THRESHOLD = int(os.getenv('SPAM_THRESHOLD', 5))
SPAM_INTERVAL = int(os.getenv('SPAM_INTERVAL', 10))
MAX_MENTIONS = int(os.getenv('MAX_MENTIONS', 5))

DATABASE_PATH = os.getenv('DATABASE_PATH', 'moderation.db')

COLORS = {
    'success': 0x00ff00,
    'error': 0xff0000,
    'warning': 0xffff00,
    'info': 0x0099ff
}
