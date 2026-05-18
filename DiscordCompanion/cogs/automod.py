import discord
from discord.ext import commands
from collections import defaultdict, deque
import time
import re
from config import COLORS, MAX_WARNINGS
from utils.permissions import ensure_mute_role
from utils.database import (
    get_blacklist_words, add_warning, get_warnings,
    add_violation_points, reset_violation_points, get_violation_points,
    get_automod_config, add_sanction, add_mute, remove_mute,
    parse_duration, format_duration,
)
from datetime import datetime, timedelta
import asyncio


# Emojis de niveau de violation
LEVEL_COLORS = {
    'info':    0x3498db,
    'warn':    0xf39c12,
    'mute':    0xe67e22,
    'kick':    0xe74c3c,
    'ban':     0x8e44ad,
}


class AutoMod(commands.Cog):
    # Cache blacklist par guild_id → liste de mots
    _blacklist_cache: dict[int, list[str]] = {}

    def __init__(self, bot):
        self.bot = bot
        self.spam_tracker: dict[int, deque] = defaultdict(deque)
        self.last_messages: dict[int, str] = defaultdict(str)
        self.file_tracker: dict[int, deque] = defaultdict(deque)

        self.invite_pattern = re.compile(
            r'discord\.gg/[a-zA-Z0-9]+|discord\.com/invite/[a-zA-Z0-9]+|discordapp\.com/invite/[a-zA-Z0-9]+'
        )
        self.spam_words = ['spam', 'scam', 'free nitro', 'free money', 'click here', 'nitro gratuit']

    # ------------------------------------------------------------------
    # Cache blacklist
    # ------------------------------------------------------------------

    def get_blacklist(self, guild_id: int) -> list[str]:
        if guild_id not in self._blacklist_cache:
            self._blacklist_cache[guild_id] = get_blacklist_words(guild_id)
        return self._blacklist_cache[guild_id]

    def invalidate_cache(self, guild_id: int):
        self._blacklist_cache.pop(guild_id, None)

    # ------------------------------------------------------------------
    # Listener principal
    # ------------------------------------------------------------------

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
        await self._check_caps(message)
        await self._check_file_flood(message)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if before.content != after.content:
            await self.on_message(after)

    # ------------------------------------------------------------------
    # Détections
    # ------------------------------------------------------------------

    async def _check_spam(self, message):
        uid = message.author.id
        now = time.time()
        cfg = get_automod_config(message.guild.id)
        threshold = cfg['spam_threshold']
        interval = cfg['spam_interval']

        self.spam_tracker[uid].append(now)
        while self.spam_tracker[uid] and now - self.spam_tracker[uid][0] > interval:
            self.spam_tracker[uid].popleft()

        if len(self.spam_tracker[uid]) >= threshold:
            self.spam_tracker[uid].clear()
            await self._delete_message(message)
            await self._apply_violation(message, "Spam de messages", points=2)
            return

        if self.last_messages[uid] == message.content and len(message.content) > 10:
            await self._delete_message(message)
            await self._apply_violation(message, "Messages répétés identiques", points=2)

        self.last_messages[uid] = message.content

    async def _check_mention_spam(self, message):
        cfg = get_automod_config(message.guild.id)
        count = len(message.mentions) + len(message.role_mentions)
        if count >= cfg['max_mentions']:
            await self._delete_message(message)
            await self._apply_violation(message, f"Spam de mentions ({count} mentions)", points=3)

    async def _check_discord_invites(self, message):
        if self.invite_pattern.search(message.content):
            await self._delete_message(message)
            await self._apply_violation(message, "Lien d'invitation Discord non autorisé", points=1)

    async def _check_suspicious_content(self, message):
        content_lower = message.content.lower()
        for word in self.spam_words:
            if word in content_lower:
                await self._delete_message(message)
                await self._apply_violation(message, f"Contenu suspect : « {word} »", points=3)
                return

    async def _check_blacklist(self, message):
        words = self.get_blacklist(message.guild.id)
        content_lower = message.content.lower()
        for word in words:
            if word in content_lower:
                await self._delete_message(message)
                await self._apply_violation(message, f"Mot interdit : « {word} »", points=2)
                return

    async def _check_caps(self, message):
        cfg = get_automod_config(message.guild.id)
        if not cfg['caps_detection']:
            return
        text = message.content
        letters = [c for c in text if c.isalpha()]
        if len(letters) < cfg['caps_min_length']:
            return
        caps_ratio = sum(1 for c in letters if c.isupper()) / len(letters) * 100
        if caps_ratio >= cfg['caps_percent']:
            await self._delete_message(message)
            await self._apply_violation(message, f"Abus de majuscules ({int(caps_ratio)}%)", points=1)

    async def _check_file_flood(self, message):
        if not message.attachments:
            return
        cfg = get_automod_config(message.guild.id)
        uid = message.author.id
        now = time.time()
        interval = cfg['file_flood_interval']
        limit = cfg['file_flood_limit']

        for _ in message.attachments:
            self.file_tracker[uid].append(now)

        while self.file_tracker[uid] and now - self.file_tracker[uid][0] > interval:
            self.file_tracker[uid].popleft()

        if len(self.file_tracker[uid]) >= limit:
            self.file_tracker[uid].clear()
            await self._delete_message(message)
            await self._apply_violation(message, f"Flood de fichiers ({len(message.attachments)} fichiers)", points=2)

    # ------------------------------------------------------------------
    # Système de points de violation
    # ------------------------------------------------------------------

    async def _apply_violation(self, message, reason: str, points: int):
        guild = message.guild
        member = message.author
        cfg = get_automod_config(guild.id)

        total = add_violation_points(guild.id, member.id, points)

        if total >= cfg['pts_ban']:
            await self._action_tempban(message, reason, cfg['pts_ban_duration'], total)
        elif total >= cfg['pts_kick']:
            await self._action_kick(message, reason, total)
        elif total >= cfg['pts_mute']:
            await self._action_mute(message, reason, cfg['pts_mute_duration'], total)
        elif total >= cfg['pts_warn']:
            await self._action_warn(message, reason, total)
        else:
            # Simple notification, pas d'action
            await self._notify(message, reason, points, total)

    async def _notify(self, message, reason: str, points: int, total: int):
        embed = discord.Embed(
            title="⚠️ Avertissement Auto-Mod",
            description=f"{message.author.mention}, respectez les règles du serveur !",
            color=COLORS['warning']
        )
        embed.add_field(name="Violation", value=reason, inline=True)
        embed.add_field(name="Points", value=f"+{points} → **{total}** pts", inline=True)
        embed.set_footer(text="Système d'auto-modération")
        msg = await message.channel.send(embed=embed)
        await msg.delete(delay=12)

    async def _action_warn(self, message, reason: str, total: int):
        add_warning(message.guild.id, message.author.id, self.bot.user.id, f"[Auto-Mod] {reason}")
        add_sanction(message.guild.id, message.author.id, self.bot.user.id, 'warn', f"[Auto-Mod] {reason}")
        warnings = get_warnings(message.guild.id, message.author.id)

        embed = discord.Embed(
            title="🤖 Auto-Mod — Avertissement",
            description=f"{message.author.mention} a reçu un avertissement automatique.",
            color=COLORS['warning']
        )
        embed.add_field(name="Raison", value=reason, inline=True)
        embed.add_field(name="Points accumulés", value=f"**{total}** pts", inline=True)
        embed.add_field(name="Avertissements", value=f"{len(warnings)}/{MAX_WARNINGS}", inline=True)
        embed.set_footer(text="Système d'auto-modération")
        msg = await message.channel.send(embed=embed)
        await msg.delete(delay=15)

        try:
            dm = discord.Embed(
                title="Avertissement automatique reçu",
                description=f"Vous avez reçu un avertissement dans **{message.guild.name}**.",
                color=COLORS['warning']
            )
            dm.add_field(name="Raison", value=reason)
            dm.add_field(name="Points accumulés", value=f"{total} pts")
            await message.author.send(embed=dm)
        except discord.Forbidden:
            pass

    async def _action_mute(self, message, reason: str, duration: int, total: int):
        try:
            mute_role = await ensure_mute_role(message.guild)
            if mute_role in message.author.roles:
                return
            await message.author.add_roles(mute_role, reason=f"Auto-Mod : {reason}")
            unmute_at = datetime.utcnow() + timedelta(seconds=duration)
            add_mute(message.guild.id, message.author.id, self.bot.user.id, f"[Auto-Mod] {reason}", unmute_at)
            add_sanction(message.guild.id, message.author.id, self.bot.user.id, 'mute', f"[Auto-Mod] {reason}", format_duration(duration))
            reset_violation_points(message.guild.id, message.author.id)

            embed = discord.Embed(
                title="🤖 Auto-Mod — Mute Temporaire",
                description=f"{message.author.mention} a été rendu muet automatiquement.",
                color=COLORS['warning']
            )
            embed.add_field(name="Raison", value=reason, inline=True)
            embed.add_field(name="Durée", value=format_duration(duration), inline=True)
            embed.add_field(name="Points accumulés", value=f"**{total}** pts", inline=True)
            embed.set_footer(text="Système d'auto-modération • Points réinitialisés")
            msg = await message.channel.send(embed=embed)
            await msg.delete(delay=15)

            async def _unmute():
                await asyncio.sleep(duration)
                try:
                    if mute_role in message.author.roles:
                        await message.author.remove_roles(mute_role, reason="Auto-unmute expiré")
                    remove_mute(message.guild.id, message.author.id)
                except (discord.Forbidden, discord.NotFound):
                    pass

            self.bot.loop.create_task(_unmute())
        except discord.Forbidden:
            pass

    async def _action_kick(self, message, reason: str, total: int):
        try:
            dm = discord.Embed(
                title="Vous avez été expulsé automatiquement",
                description=f"Vous avez été expulsé de **{message.guild.name}** par le système d'auto-modération.",
                color=COLORS['error']
            )
            dm.add_field(name="Raison", value=reason)
            try:
                await message.author.send(embed=dm)
            except discord.Forbidden:
                pass

            await message.author.kick(reason=f"Auto-Mod : {reason} ({total} pts)")
            add_sanction(message.guild.id, message.author.id, self.bot.user.id, 'kick', f"[Auto-Mod] {reason}")
            reset_violation_points(message.guild.id, message.author.id)

            embed = discord.Embed(
                title="🤖 Auto-Mod — Expulsion",
                description=f"**{message.author}** a été expulsé automatiquement.",
                color=COLORS['error']
            )
            embed.add_field(name="Raison", value=reason, inline=True)
            embed.add_field(name="Points accumulés", value=f"**{total}** pts", inline=True)
            embed.set_footer(text="Système d'auto-modération • Points réinitialisés")
            msg = await message.channel.send(embed=embed)
            await msg.delete(delay=15)
        except discord.Forbidden:
            pass

    async def _action_tempban(self, message, reason: str, duration: int, total: int):
        try:
            dm = discord.Embed(
                title="Vous avez été banni temporairement",
                description=f"Vous avez été banni de **{message.guild.name}** par le système d'auto-modération.",
                color=COLORS['error']
            )
            dm.add_field(name="Raison", value=reason)
            dm.add_field(name="Durée", value=format_duration(duration))
            try:
                await message.author.send(embed=dm)
            except discord.Forbidden:
                pass

            await message.author.ban(reason=f"Auto-Mod : {reason} ({total} pts)", delete_message_days=0)
            from utils.database import add_tempban
            unban_at = datetime.utcnow() + timedelta(seconds=duration)
            add_tempban(message.guild.id, message.author.id, self.bot.user.id, f"[Auto-Mod] {reason}", unban_at)
            add_sanction(message.guild.id, message.author.id, self.bot.user.id, 'tempban', f"[Auto-Mod] {reason}", format_duration(duration))
            reset_violation_points(message.guild.id, message.author.id)

            embed = discord.Embed(
                title="🤖 Auto-Mod — Bannissement Temporaire",
                description=f"**{message.author}** a été banni temporairement.",
                color=COLORS['error']
            )
            embed.add_field(name="Raison", value=reason, inline=True)
            embed.add_field(name="Durée", value=format_duration(duration), inline=True)
            embed.add_field(name="Points accumulés", value=f"**{total}** pts", inline=True)
            embed.set_footer(text="Système d'auto-modération • Points réinitialisés")
            msg = await message.channel.send(embed=embed)
            await msg.delete(delay=15)
        except discord.Forbidden:
            pass

    # ------------------------------------------------------------------
    # Utilitaire
    # ------------------------------------------------------------------

    async def _delete_message(self, message):
        try:
            await message.delete()
        except (discord.Forbidden, discord.NotFound):
            pass


async def setup(bot):
    await bot.add_cog(AutoMod(bot))
