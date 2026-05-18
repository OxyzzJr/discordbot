import discord
from discord.ext import commands
from collections import defaultdict, deque
import time
import re
from config import SPAM_THRESHOLD, SPAM_INTERVAL, MAX_MENTIONS, COLORS
from utils.permissions import ensure_mute_role
from utils.database import get_blacklist_words, add_warning, get_warnings
from config import MAX_WARNINGS


class AutoMod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.spam_tracker = defaultdict(lambda: deque())
        self.last_messages = defaultdict(str)

        self.invite_pattern = re.compile(
            r'discord\.gg/[a-zA-Z0-9]+|discord\.com/invite/[a-zA-Z0-9]+|discordapp\.com/invite/[a-zA-Z0-9]+'
        )
        self.spam_words = ['spam', 'scam', 'free nitro', 'free money', 'click here']

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        if message.author.guild_permissions.manage_messages:
            return

        await self._check_spam(message)
        await self._check_mention_spam(message)
        await self._check_discord_invites(message)
        await self._check_suspicious_content(message)
        await self._check_blacklist(message)

    async def _check_spam(self, message):
        user_id = message.author.id
        current_time = time.time()

        self.spam_tracker[user_id].append(current_time)

        while self.spam_tracker[user_id] and current_time - self.spam_tracker[user_id][0] > SPAM_INTERVAL:
            self.spam_tracker[user_id].popleft()

        if len(self.spam_tracker[user_id]) >= SPAM_THRESHOLD:
            await self._handle_spam_violation(message, "Spam de messages détecté")
            self.spam_tracker[user_id].clear()

        if self.last_messages[user_id] == message.content and len(message.content) > 10:
            await self._handle_spam_violation(message, "Spam de messages répétés")

        self.last_messages[user_id] = message.content

    async def _check_mention_spam(self, message):
        mention_count = len(message.mentions) + len(message.role_mentions)
        if mention_count >= MAX_MENTIONS:
            await self._handle_spam_violation(message, f"Spam de mentions excessif ({mention_count} mentions)")

    async def _check_discord_invites(self, message):
        if self.invite_pattern.search(message.content):
            if not message.author.guild_permissions.manage_messages:
                try:
                    await message.delete()
                    embed = discord.Embed(
                        title="🔗 Lien d'Invitation Supprimé",
                        description=f"{message.author.mention}, les liens d'invitation Discord ne sont pas autorisés !",
                        color=COLORS['warning']
                    )
                    warning_msg = await message.channel.send(embed=embed)
                    await warning_msg.delete(delay=10)
                except discord.Forbidden:
                    pass

    async def _check_suspicious_content(self, message):
        content_lower = message.content.lower()
        for spam_word in self.spam_words:
            if spam_word in content_lower:
                await self._handle_spam_violation(message, f"Contenu suspect détecté : {spam_word}")
                break

    async def _check_blacklist(self, message):
        words = get_blacklist_words(message.guild.id)
        if not words:
            return
        content_lower = message.content.lower()
        for word in words:
            if word in content_lower:
                try:
                    await message.delete()
                    # Add automatic warning
                    add_warning(message.guild.id, message.author.id, self.bot.user.id, f"Mot interdit utilisé : {word}")
                    warnings = get_warnings(message.guild.id, message.author.id)

                    embed = discord.Embed(
                        title="🚫 Mot Interdit Supprimé",
                        description=f"{message.author.mention}, ce message contient un mot interdit et a été supprimé.",
                        color=COLORS['error']
                    )
                    embed.add_field(name="Avertissements", value=f"{len(warnings)}/{MAX_WARNINGS}", inline=True)
                    warning_msg = await message.channel.send(embed=embed)
                    await warning_msg.delete(delay=10)

                    # Auto-mute if max warnings reached
                    if len(warnings) >= MAX_WARNINGS:
                        await self._handle_spam_violation(message, f"Nombre maximum d'avertissements atteint (mot interdit)")
                except discord.Forbidden:
                    pass
                break

    async def _handle_spam_violation(self, message, reason):
        try:
            await message.delete()
        except (discord.Forbidden, discord.NotFound):
            pass

        try:
            mute_role = await ensure_mute_role(message.guild)
            if mute_role not in message.author.roles:
                await message.author.add_roles(mute_role, reason=f"Auto-modération : {reason}")

                embed = discord.Embed(
                    title="🤖 Action Auto-Modération",
                    description=f"{message.author.mention} a été temporairement rendu muet",
                    color=COLORS['warning']
                )
                embed.add_field(name="Raison", value=reason, inline=True)
                embed.add_field(name="Action", value="Mute temporaire (5 minutes)", inline=True)
                embed.set_footer(text="Système d'auto-modération")

                notification = await message.channel.send(embed=embed)
                await notification.delete(delay=15)

                await self._schedule_auto_unmute(message.author, mute_role, 300)
        except discord.Forbidden:
            embed = discord.Embed(
                title="⚠️ Avertissement Auto-Modération",
                description=f"{message.author.mention}, veuillez respecter les règles du serveur !",
                color=COLORS['warning']
            )
            embed.add_field(name="Violation", value=reason, inline=True)
            warning_msg = await message.channel.send(embed=embed)
            await warning_msg.delete(delay=10)

    async def _schedule_auto_unmute(self, member, mute_role, delay):
        import asyncio

        async def auto_unmute():
            await asyncio.sleep(delay)
            try:
                if mute_role in member.roles:
                    await member.remove_roles(mute_role, reason="Auto-unmute : Mute temporaire expiré")
            except (discord.Forbidden, discord.NotFound):
                pass

        self.bot.loop.create_task(auto_unmute())

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if before.content != after.content:
            await self.on_message(after)


async def setup(bot):
    await bot.add_cog(AutoMod(bot))
