import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone
import logging as pylogging

from utils.database import get_guild_settings
from config import COLORS

log = pylogging.getLogger(__name__)

C_JOIN    = 0x57F287
C_LEAVE   = 0xED4245
C_BAN     = 0xED4245
C_UNBAN   = 0xFEE75C
C_VOICE   = 0x5865F2
C_WARN    = 0xFFA500
C_DELETE  = 0xFFA500
C_EDIT    = 0xFEE75C
C_ROLE    = 0xEB459E
C_CHANNEL = 0x57F287
C_SERVER  = 0x5865F2
C_TIMEOUT = 0xED4245
C_INFO    = 0x5865F2


class EventLogger(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _mod_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        settings = get_guild_settings(guild.id)
        if settings and len(settings) > 7 and settings[7]:
            return guild.get_channel(settings[7])
        return None

    async def _log(self, guild: discord.Guild, embed: discord.Embed, content: str = None):
        ch = self._mod_channel(guild)
        if not ch:
            return
        try:
            await ch.send(content=content, embed=embed)
        except discord.Forbidden:
            pass

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _ts(dt: datetime) -> str:
        if dt is None:
            return "Inconnu"
        return f"<t:{int(dt.timestamp())}:R>"

    async def _audit(self, guild: discord.Guild, action, target_id: int = None, delay: float = 10):
        try:
            async for entry in guild.audit_logs(action=action, limit=5):
                if (self._now() - entry.created_at).total_seconds() > delay:
                    break
                if target_id is None or entry.target.id == target_id:
                    return entry
        except discord.Forbidden:
            pass
        return None

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild

        try:
            membre_role = discord.utils.get(guild.roles, name="Membre")
            if membre_role:
                await member.add_roles(membre_role, reason="Auto-attribution rôle Membre")
        except discord.Forbidden:
            pass

        settings = get_guild_settings(guild.id)
        if settings and len(settings) > 5 and settings[5]:
            welcome_channel = guild.get_channel(settings[5])
            if welcome_channel:
                msg = (settings[6] or "Bienvenue sur **{server}**, {mention} ! 🎉") \
                    .replace("{mention}", member.mention) \
                    .replace("{server}", guild.name) \
                    .replace("{count}", str(guild.member_count))
                try:
                    await welcome_channel.send(embed=discord.Embed(
                        title="👋 Bienvenue !",
                        description=msg,
                        color=C_JOIN,
                        timestamp=self._now()
                    ).set_thumbnail(url=member.display_avatar.url))
                except discord.Forbidden:
                    pass

        age_days = (self._now() - member.created_at).days
        embed = discord.Embed(
            title="📥  Nouveau Membre",
            description=f"{member.mention} vient de rejoindre le serveur.",
            color=C_JOIN,
            timestamp=self._now()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="👤 Utilisateur", value=f"`{member}` — ID `{member.id}`", inline=False)
        embed.add_field(name="📅 Compte créé", value=self._ts(member.created_at),      inline=True)
        embed.add_field(name="👥 Membre nº",   value=f"`{guild.member_count}`",        inline=True)

        if age_days < 7:
            embed.add_field(
                name="⚠️  Compte récent !",
                value=f"Ce compte n'a que **{age_days} jour{'s' if age_days != 1 else ''}**.",
                inline=False
            )

        embed.set_footer(text=f"ID : {member.id}")
        await self._log(guild, embed, content="@here")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        entry = await self._audit(member.guild, discord.AuditLogAction.kick, member.id)

        if entry:
            embed = discord.Embed(
                title="👢  Membre Expulsé (Kick)",
                description=f"{member.mention} a été expulsé.",
                color=C_BAN,
                timestamp=self._now()
            )
            embed.add_field(name="👤 Utilisateur", value=f"`{member}` — ID `{member.id}`", inline=False)
            embed.add_field(name="🛡️ Modérateur",  value=entry.user.mention,               inline=True)
            embed.add_field(name="📋 Raison",       value=entry.reason or "Aucune raison", inline=True)
        else:
            roles = [r.mention for r in member.roles if r.name != "@everyone"]
            embed = discord.Embed(
                title="📤  Membre Parti",
                description=f"{member.mention} a quitté le serveur.",
                color=C_LEAVE,
                timestamp=self._now()
            )
            embed.add_field(name="👤 Utilisateur", value=f"`{member}` — ID `{member.id}`",   inline=False)
            embed.add_field(name="📅 Arrivé",      value=self._ts(member.joined_at),         inline=True)
            embed.add_field(name="👥 Membres",     value=f"`{member.guild.member_count}`",   inline=True)
            if roles:
                embed.add_field(name="🏷️ Rôles", value=" ".join(roles)[:1024], inline=False)

        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"ID : {member.id}")
        await self._log(member.guild, embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        entry = await self._audit(guild, discord.AuditLogAction.ban, user.id)

        embed = discord.Embed(
            title="🔨  Membre Banni",
            description=f"{user.mention} a été banni du serveur.",
            color=C_BAN,
            timestamp=self._now()
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="👤 Utilisateur", value=f"`{user}` — ID `{user.id}`",                  inline=False)
        embed.add_field(name="🛡️ Modérateur",  value=entry.user.mention if entry else "Inconnu",    inline=True)
        embed.add_field(name="📋 Raison",       value=(entry.reason if entry else None) or "Aucune", inline=True)
        embed.set_footer(text=f"ID : {user.id}")
        await self._log(guild, embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        entry = await self._audit(guild, discord.AuditLogAction.unban, user.id)

        embed = discord.Embed(
            title="✅  Membre Débanni",
            description=f"{user.mention} a été débanni.",
            color=C_UNBAN,
            timestamp=self._now()
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="👤 Utilisateur", value=f"`{user}` — ID `{user.id}`",              inline=False)
        embed.add_field(name="🛡️ Modérateur",  value=entry.user.mention if entry else "Inconnu", inline=True)
        embed.set_footer(text=f"ID : {user.id}")
        await self._log(guild, embed)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        guild = after.guild

        if before.timed_out_until != after.timed_out_until:
            if after.timed_out_until:
                entry = await self._audit(guild, discord.AuditLogAction.member_update, after.id)
                embed = discord.Embed(
                    title="⏱️  Timeout Appliqué",
                    description=f"{after.mention} a reçu un timeout.",
                    color=C_TIMEOUT,
                    timestamp=self._now()
                )
                embed.add_field(name="👤 Membre",      value=f"`{after}`",                                      inline=True)
                embed.add_field(name="🛡️ Modérateur", value=entry.user.mention if entry else "Inconnu",        inline=True)
                embed.add_field(name="⏰ Expire",      value=self._ts(after.timed_out_until),                  inline=True)
                embed.add_field(name="📋 Raison",      value=(entry.reason if entry else None) or "Aucune",    inline=False)
            else:
                embed = discord.Embed(
                    title="✅  Timeout Levé",
                    description=f"Le timeout de {after.mention} a été levé.",
                    color=C_UNBAN,
                    timestamp=self._now()
                )
                embed.add_field(name="👤 Membre", value=f"`{after}`", inline=True)

            embed.set_footer(text=f"ID : {after.id}")
            await self._log(guild, embed)
            return

        if before.nick != after.nick:
            embed = discord.Embed(
                title="✏️  Pseudo Modifié",
                description=f"Le pseudo de {after.mention} a changé.",
                color=C_EDIT,
                timestamp=self._now()
            )
            embed.add_field(name="Avant", value=f"`{before.nick or before.name}`", inline=True)
            embed.add_field(name="Après", value=f"`{after.nick or after.name}`",   inline=True)
            embed.set_footer(text=f"ID : {after.id}")
            await self._log(guild, embed)

        added   = [r for r in after.roles  if r not in before.roles]
        removed = [r for r in before.roles if r not in after.roles]
        if added or removed:
            entry = await self._audit(guild, discord.AuditLogAction.member_role_update, after.id)
            embed = discord.Embed(
                title="🏷️  Rôles Modifiés",
                description=f"Les rôles de {after.mention} ont changé.",
                color=C_ROLE,
                timestamp=self._now()
            )
            embed.add_field(name="👤 Membre", value=f"`{after}`", inline=True)
            if entry:
                embed.add_field(name="🛡️ Par", value=entry.user.mention, inline=True)
            if added:
                embed.add_field(name="✅ Ajoutés",  value=" ".join(r.mention for r in added),   inline=False)
            if removed:
                embed.add_field(name="❌ Retirés", value=" ".join(r.mention for r in removed), inline=False)
            embed.set_footer(text=f"ID : {after.id}")
            await self._log(guild, embed)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState
    ):
        guild = member.guild

        # ── Changements de salon ──────────────────────────────────────────────
        if before.channel is None and after.channel is not None:
            embed = discord.Embed(
                title="🔊  Rejoint un Vocal",
                description=f"{member.mention} a rejoint un salon vocal.",
                color=C_JOIN,
                timestamp=self._now()
            )
            embed.add_field(name="👤 Membre", value=f"`{member}`",         inline=True)
            embed.add_field(name="📢 Salon",  value=after.channel.mention, inline=True)
            embed.set_footer(text=f"ID : {member.id}")
            await self._log(guild, embed)

        elif before.channel is not None and after.channel is None:
            entry = await self._audit(guild, discord.AuditLogAction.member_disconnect, delay=5)
            if entry:
                embed = discord.Embed(
                    title="🔇  Expulsé du Vocal",
                    description=f"{member.mention} a été déconnecté de force d'un salon vocal.",
                    color=C_BAN,
                    timestamp=self._now()
                )
                embed.add_field(name="👤 Membre",      value=f"`{member}`",          inline=True)
                embed.add_field(name="📢 Salon",       value=before.channel.mention, inline=True)
                embed.add_field(name="🛡️ Modérateur", value=entry.user.mention,     inline=True)
            else:
                embed = discord.Embed(
                    title="🔇  Quitté un Vocal",
                    description=f"{member.mention} a quitté un salon vocal.",
                    color=C_LEAVE,
                    timestamp=self._now()
                )
                embed.add_field(name="👤 Membre", value=f"`{member}`",          inline=True)
                embed.add_field(name="📢 Salon",  value=before.channel.mention, inline=True)
            embed.set_footer(text=f"ID : {member.id}")
            await self._log(guild, embed)

        elif (
            before.channel is not None
            and after.channel is not None
            and before.channel != after.channel
        ):
            entry = await self._audit(guild, discord.AuditLogAction.member_move, delay=5)
            if entry:
                embed = discord.Embed(
                    title="🔀  Déplacé par un Modérateur",
                    description=f"{member.mention} a été déplacé dans un autre salon vocal.",
                    color=C_WARN,
                    timestamp=self._now()
                )
                embed.add_field(name="👤 Membre",       value=f"`{member}`",          inline=True)
                embed.add_field(name="📢 Avant",        value=before.channel.mention, inline=True)
                embed.add_field(name="📢 Après",        value=after.channel.mention,  inline=True)
                embed.add_field(name="🛡️ Déplacé par", value=entry.user.mention,     inline=True)
            else:
                embed = discord.Embed(
                    title="🔀  Changé de Vocal",
                    description=f"{member.mention} a changé de salon vocal par lui-même.",
                    color=C_VOICE,
                    timestamp=self._now()
                )
                embed.add_field(name="👤 Membre", value=f"`{member}`",          inline=True)
                embed.add_field(name="📢 Avant",  value=before.channel.mention, inline=True)
                embed.add_field(name="📢 Après",  value=after.channel.mention,  inline=True)
            embed.set_footer(text=f"ID : {member.id}")
            await self._log(guild, embed)

        # ── Changements d'état (même salon) ──────────────────────────────────
        elif before.channel == after.channel and after.channel is not None:

            # Mute serveur (par un modo)
            if before.mute != after.mute:
                embed = discord.Embed(
                    title=f"🔇  {'Muté' if after.mute else 'Démuté'} (serveur)",
                    description=f"{member.mention} a été **{'muté' if after.mute else 'démuté'}** par le serveur.",
                    color=C_WARN,
                    timestamp=self._now()
                )
                embed.add_field(name="👤 Membre", value=f"`{member}`",         inline=True)
                embed.add_field(name="📢 Salon",  value=after.channel.mention, inline=True)
                embed.set_footer(text=f"ID : {member.id}")
                await self._log(guild, embed)

            # Sourdine serveur (par un modo)
            if before.deaf != after.deaf:
                embed = discord.Embed(
                    title=f"🙉  {'Sourdine' if after.deaf else 'Sourdine Levée'} (serveur)",
                    description=f"{member.mention} a été **{'mis en sourdine' if after.deaf else 'retiré de la sourdine'}** par le serveur.",
                    color=C_WARN,
                    timestamp=self._now()
                )
                embed.add_field(name="👤 Membre", value=f"`{member}`",         inline=True)
                embed.add_field(name="📢 Salon",  value=after.channel.mention, inline=True)
                embed.set_footer(text=f"ID : {member.id}")
                await self._log(guild, embed)

            # Self-mute (se mute soi-même)
            if before.self_mute != after.self_mute:
                embed = discord.Embed(
                    title=f"🎙️  {'Muté' if after.self_mute else 'Démuté'} (soi-même)",
                    description=f"{member.mention} s'est **{'mis en sourdine micro' if after.self_mute else 'démuté'}**.",
                    color=C_WARN if after.self_mute else C_JOIN,
                    timestamp=self._now()
                )
                embed.add_field(name="👤 Membre", value=f"`{member}`",         inline=True)
                embed.add_field(name="📢 Salon",  value=after.channel.mention, inline=True)
                embed.set_footer(text=f"ID : {member.id}")
                await self._log(guild, embed)

            # Self-deaf (se met en sourdine soi-même)
            if before.self_deaf != after.self_deaf:
                embed = discord.Embed(
                    title=f"🔈  {'Sourdine' if after.self_deaf else 'Sourdine Levée'} (soi-même)",
                    description=f"{member.mention} s'est **{'mis en sourdine' if after.self_deaf else 'retiré de la sourdine'}**.",
                    color=C_WARN if after.self_deaf else C_JOIN,
                    timestamp=self._now()
                )
                embed.add_field(name="👤 Membre", value=f"`{member}`",         inline=True)
                embed.add_field(name="📢 Salon",  value=after.channel.mention, inline=True)
                embed.set_footer(text=f"ID : {member.id}")
                await self._log(guild, embed)

            # Stream démarré / arrêté
            if before.self_stream != after.self_stream:
                embed = discord.Embed(
                    title=f"📺  Stream {'Démarré' if after.self_stream else 'Terminé'}",
                    description=f"{member.mention} a **{'lancé' if after.self_stream else 'arrêté'}** son stream.",
                    color=C_VOICE,
                    timestamp=self._now()
                )
                embed.add_field(name="👤 Membre", value=f"`{member}`",         inline=True)
                embed.add_field(name="📢 Salon",  value=after.channel.mention, inline=True)
                embed.set_footer(text=f"ID : {member.id}")
                await self._log(guild, embed)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        embed = discord.Embed(
            title="🗑️  Message Supprimé",
            description=f"Message de {message.author.mention} supprimé dans {message.channel.mention}",
            color=C_DELETE,
            timestamp=self._now()
        )
        embed.add_field(name="👤 Auteur", value=f"`{message.author}` — ID `{message.author.id}`", inline=False)
        embed.add_field(name="📝 Salon",  value=message.channel.mention,                          inline=True)

        if message.content:
            content = message.content[:1020] + ("…" if len(message.content) > 1020 else "")
            embed.add_field(name="💬 Contenu", value=f"```{content}```", inline=False)

        if message.attachments:
            embed.add_field(
                name="📎 Pièces jointes",
                value="\n".join(f"`{a.filename}`" for a in message.attachments),
                inline=False
            )

        embed.set_footer(text=f"ID message : {message.id}")
        await self._log(message.guild, embed)

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: list[discord.Message]):
        if not messages or not messages[0].guild:
            return
        guild   = messages[0].guild
        channel = messages[0].channel

        embed = discord.Embed(
            title="🗑️  Suppression Massive",
            description=f"**{len(messages)}** messages supprimés en masse dans {channel.mention}.",
            color=C_BAN,
            timestamp=self._now()
        )
        embed.add_field(name="📝 Salon",  value=channel.mention,    inline=True)
        embed.add_field(name="📊 Nombre", value=str(len(messages)), inline=True)
        await self._log(guild, embed)

    _CHANNEL_TYPES = {
        discord.TextChannel:     "📝 Textuel",
        discord.VoiceChannel:    "🔊 Vocal",
        discord.CategoryChannel: "📁 Catégorie",
        discord.StageChannel:    "🎙️ Scène",
        discord.ForumChannel:    "💬 Forum",
        discord.Thread:          "🧵 Thread",
    }

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        entry   = await self._audit(channel.guild, discord.AuditLogAction.channel_create, channel.id)
        ch_type = self._CHANNEL_TYPES.get(type(channel), "Salon")
        mention = channel.mention if hasattr(channel, 'mention') else f"`#{channel.name}`"

        embed = discord.Embed(
            title=f"✅  Salon Créé — {ch_type}",
            description=f"Le salon {mention} a été créé.",
            color=C_CHANNEL,
            timestamp=self._now()
        )
        embed.add_field(name="📝 Nom",      value=f"`{channel.name}`",                        inline=True)
        embed.add_field(name="🛡️ Créé par", value=entry.user.mention if entry else "Inconnu", inline=True)
        embed.set_footer(text=f"ID : {channel.id}")
        await self._log(channel.guild, embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        entry = await self._audit(channel.guild, discord.AuditLogAction.channel_delete)

        embed = discord.Embed(
            title="❌  Salon Supprimé",
            description=f"Le salon **#{channel.name}** a été supprimé.",
            color=C_BAN,
            timestamp=self._now()
        )
        embed.add_field(name="📝 Nom",          value=f"`{channel.name}`",                        inline=True)
        embed.add_field(name="🛡️ Supprimé par", value=entry.user.mention if entry else "Inconnu", inline=True)
        embed.set_footer(text=f"ID : {channel.id}")
        await self._log(channel.guild, embed)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        changes = []
        if before.name != after.name:
            changes.append(f"**Nom** : `{before.name}` → `{after.name}`")
        if hasattr(before, 'topic') and before.topic != after.topic:
            changes.append(f"**Description** : `{before.topic or '—'}` → `{after.topic or '—'}`")
        if hasattr(before, 'nsfw') and before.nsfw != after.nsfw:
            changes.append(f"**NSFW** : `{before.nsfw}` → `{after.nsfw}`")
        if hasattr(before, 'slowmode_delay') and before.slowmode_delay != after.slowmode_delay:
            changes.append(f"**Slowmode** : `{before.slowmode_delay}s` → `{after.slowmode_delay}s`")
        if not changes:
            return

        mention = after.mention if hasattr(after, 'mention') else f"`#{after.name}`"
        embed = discord.Embed(
            title="✏️  Salon Modifié",
            description=f"Le salon {mention} a été modifié.",
            color=C_EDIT,
            timestamp=self._now()
        )
        embed.add_field(name="🔄 Modifications", value="\n".join(changes), inline=False)
        embed.set_footer(text=f"ID : {after.id}")
        await self._log(after.guild, embed)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        entry = await self._audit(role.guild, discord.AuditLogAction.role_create, role.id)
        embed = discord.Embed(
            title="✅  Rôle Créé",
            description=f"Le rôle {role.mention} a été créé.",
            color=C_ROLE,
            timestamp=self._now()
        )
        embed.add_field(name="🏷️ Nom",      value=f"`{role.name}`",                           inline=True)
        embed.add_field(name="🎨 Couleur",   value=str(role.color),                            inline=True)
        embed.add_field(name="🛡️ Créé par", value=entry.user.mention if entry else "Inconnu", inline=True)
        embed.set_footer(text=f"ID : {role.id}")
        await self._log(role.guild, embed)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        entry = await self._audit(role.guild, discord.AuditLogAction.role_delete)
        embed = discord.Embed(
            title="❌  Rôle Supprimé",
            description=f"Le rôle **{role.name}** a été supprimé.",
            color=C_BAN,
            timestamp=self._now()
        )
        embed.add_field(name="🏷️ Nom",          value=f"`{role.name}`",                           inline=True)
        embed.add_field(name="🛡️ Supprimé par", value=entry.user.mention if entry else "Inconnu", inline=True)
        embed.set_footer(text=f"ID : {role.id}")
        await self._log(role.guild, embed)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        changes = []
        if before.name != after.name:
            changes.append(f"**Nom** : `{before.name}` → `{after.name}`")
        if before.color != after.color:
            changes.append(f"**Couleur** : `{before.color}` → `{after.color}`")
        if before.hoist != after.hoist:
            changes.append(f"**Affiché séparément** : `{before.hoist}` → `{after.hoist}`")
        if before.mentionable != after.mentionable:
            changes.append(f"**Mentionnable** : `{before.mentionable}` → `{after.mentionable}`")
        if before.permissions != after.permissions:
            changes.append("**Permissions** modifiées")
        if not changes:
            return

        embed = discord.Embed(
            title="✏️  Rôle Modifié",
            description=f"Le rôle {after.mention} a été modifié.",
            color=C_ROLE,
            timestamp=self._now()
        )
        embed.add_field(name="🔄 Modifications", value="\n".join(changes), inline=False)
        embed.set_footer(text=f"ID : {after.id}")
        await self._log(after.guild, embed)

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        changes = []
        if before.name != after.name:
            changes.append(f"**Nom** : `{before.name}` → `{after.name}`")
        if before.icon != after.icon:
            changes.append("**Icône** modifiée")
        if before.banner != after.banner:
            changes.append("**Bannière** modifiée")
        if before.verification_level != after.verification_level:
            changes.append(f"**Vérification** : `{before.verification_level}` → `{after.verification_level}`")
        if before.explicit_content_filter != after.explicit_content_filter:
            changes.append(f"**Filtre contenu** : `{before.explicit_content_filter}` → `{after.explicit_content_filter}`")
        if not changes:
            return

        embed = discord.Embed(
            title="⚙️  Serveur Modifié",
            description=f"Le serveur **{after.name}** a été mis à jour.",
            color=C_SERVER,
            timestamp=self._now()
        )
        embed.add_field(name="🔄 Modifications", value="\n".join(changes), inline=False)
        await self._log(after, embed)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        embed = discord.Embed(
            title="🔗  Invitation Créée",
            color=C_INFO,
            timestamp=self._now()
        )
        embed.add_field(name="🔑 Code",              value=f"`{invite.code}`",                                     inline=True)
        embed.add_field(name="👤 Créée par",         value=invite.inviter.mention if invite.inviter else "Inconnu", inline=True)
        embed.add_field(name="📢 Salon",             value=invite.channel.mention if invite.channel else "Inconnu", inline=True)
        embed.add_field(name="⏰ Expire",            value=self._ts(invite.expires_at) if invite.expires_at else "Jamais", inline=True)
        embed.add_field(name="🔢 Utilisations max",  value=str(invite.max_uses) if invite.max_uses else "∞",        inline=True)
        await self._log(invite.guild, embed)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        embed = discord.Embed(
            title="🔗  Invitation Supprimée",
            description=f"L'invitation `{invite.code}` a été révoquée.",
            color=C_LEAVE,
            timestamp=self._now()
        )
        embed.add_field(name="🔑 Code",  value=f"`{invite.code}`",                                     inline=True)
        embed.add_field(name="📢 Salon", value=invite.channel.mention if invite.channel else "Inconnu", inline=True)
        await self._log(invite.guild, embed)

    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild: discord.Guild, before, after):
        added   = [e for e in after  if e not in before]
        removed = [e for e in before if e not in after]
        if not added and not removed:
            return

        embed = discord.Embed(title="😀  Emojis Modifiés", color=C_INFO, timestamp=self._now())
        if added:
            embed.add_field(name="✅ Ajoutés",   value=" ".join(str(e) for e in added[:20]),            inline=False)
        if removed:
            embed.add_field(name="❌ Supprimés", value=" ".join(f"`:{e.name}:`" for e in removed[:20]), inline=False)
        await self._log(guild, embed)

    @commands.Cog.listener()
    async def on_guild_stickers_update(self, guild: discord.Guild, before, after):
        added   = [s for s in after  if s not in before]
        removed = [s for s in before if s not in after]
        if not added and not removed:
            return

        embed = discord.Embed(title="🎭  Stickers Modifiés", color=C_INFO, timestamp=self._now())
        if added:
            embed.add_field(name="✅ Ajoutés",   value="\n".join(f"`{s.name}`" for s in added[:20]),   inline=False)
        if removed:
            embed.add_field(name="❌ Supprimés", value="\n".join(f"`{s.name}`" for s in removed[:20]), inline=False)
        await self._log(guild, embed)

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        embed = discord.Embed(
            title="🧵  Thread Créé",
            description=f"Un nouveau thread a été créé dans {thread.parent.mention if thread.parent else 'un salon'}.",
            color=C_CHANNEL,
            timestamp=self._now()
        )
        embed.add_field(name="📝 Thread",   value=thread.mention,                                      inline=True)
        embed.add_field(name="👤 Créé par", value=thread.owner.mention if thread.owner else "Inconnu", inline=True)
        embed.set_footer(text=f"ID : {thread.id}")
        await self._log(thread.guild, embed)

    @commands.Cog.listener()
    async def on_thread_delete(self, thread: discord.Thread):
        embed = discord.Embed(
            title="🧵  Thread Supprimé",
            description=f"Le thread **{thread.name}** a été supprimé.",
            color=C_BAN,
            timestamp=self._now()
        )
        embed.add_field(name="📝 Nom", value=f"`{thread.name}`", inline=True)
        embed.set_footer(text=f"ID : {thread.id}")
        await self._log(thread.guild, embed)

    @app_commands.command(
        name="setlogchannel",
        description="(Obsolète) Utilise /setmodchannel — définit le salon de logs"
    )
    @app_commands.describe(channel="Le salon à utiliser pour les logs")
    @app_commands.checks.has_permissions(administrator=True)
    async def setlogchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        from utils.database import update_guild_settings
        update_guild_settings(interaction.guild.id, mod_channel_id=channel.id)
        embed = discord.Embed(
            title="✅  Salon de Logs Défini",
            description=f"Tous les logs seront envoyés dans {channel.mention}.\n*(Équivalent à `/setmodchannel`)*",
            color=COLORS['success']
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @setlogchannel.error
    async def setlogchannel_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ Tu dois être administrateur.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(EventLogger(bot))
