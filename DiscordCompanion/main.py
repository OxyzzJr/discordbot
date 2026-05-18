import os
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv
import sqlite3
from utils.keepalive import keep_alive
import logging

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Bot configuration
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True


class ModerationBot(commands.Bot):

    def __init__(self):
        super().__init__(command_prefix="!",
                         intents=intents,
                         help_command=None,
                         case_insensitive=True,
                         heartbeat_timeout=60.0,
                         guild_ready_timeout=10.0)

    async def setup_hook(self):
        """Load cogs and sync commands"""
        # Initialize database
        from utils.database import init_db
        init_db()

        # Load cogs
        try:
            await self.load_extension('cogs.moderation')
            await self.load_extension('cogs.automod')
            await self.load_extension('cogs.logging')
            print("All cogs loaded successfully")
        except Exception as e:
            print(f"Error loading cogs: {e}")

        # Sync slash commands
        try:
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} slash commands")
        except Exception as e:
            print(f"Failed to sync commands: {e}")

    async def on_ready(self):
        logger.info(f'{self.user} is now online!')
        logger.info(f'Bot is in {len(self.guilds)} guilds')

        # Set bot status
        await self.change_presence(
            activity=discord.Activity(type=discord.ActivityType.watching,
                                      name="les violations de règles"))

    async def on_disconnect(self):
        logger.warning("Bot disconnected from Discord")

    async def on_resumed(self):
        logger.info("Bot reconnected to Discord successfully")

    async def on_command_error(self, ctx, error):
        """Global error handler"""
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ Ta pas les perms chef.")
        elif isinstance(error, commands.BotMissingPermissions):
            await ctx.send("❌ J'ai pas les perms chef.")
        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"⏰ Cette commande est en cooldown. Réessayez dans {error.retry_after:.1f} secondes."
            )
        elif isinstance(error, commands.MemberNotFound):
            await ctx.send("❌ membre introuvable.")
        else:
            print(f"Unexpected error: {error}")


async def main():
    # Start keep-alive server once (runs in daemon thread)
    keep_alive()

    while True:
        bot = ModerationBot()

        # Get token from environment variable
        token = os.getenv('DISCORD_TOKEN')
        if not token:
            logger.error("DISCORD_TOKEN not found in environment variables!")
            return

        try:
            await bot.start(token)
        except discord.LoginFailure:
            logger.error("Invalid token provided!")
            break
        except discord.ConnectionClosed:
            logger.warning("Connection closed, reconnecting in 5 seconds...")
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            logger.info("Reconnecting in 10 seconds...")
            await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(main())
