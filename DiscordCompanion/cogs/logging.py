import discord
from discord.ext import commands
from datetime import datetime
from config import COLORS, LOG_CHANNEL_NAME
from utils.database import get_guild_settings, update_guild_settings


class Logging(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def get_log_channel(self, guild):
        log_channel = discord.utils.get(guild.channels, name=LOG_CHANNEL_NAME)
        if not log_channel:
            settings = get_guild_settings(guild.id)
            if settings and settings[0]:
                log_channel = guild.get_channel(settings[0])
        return log_channel

    async def send_log(self, guild, embed):
        log_channel = self.get_log_channel(guild)
        if log_channel:
            try:
                await log_channel.send(embed=embed)
            except discord.Forbidden:
                pass

    # ------------------------------------------------------------------
    # Membre rejoint
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_member_join(self, member):
        # Attribution automatique du rôle Membre
        role_status = "Rôle 'Membre' introuvable"
        try:
            membre_role = discord.utils.get(member.guild.roles, name="Membre")
            if membre_role:
                await member.add_roles(membre_role, reason="Attribution automatique du rôle Membre")
                role_status = f"Rôle **{membre_role.name}** assigné automatiquement"
        except discord.Forbidden:
            role_status = "Permission insuffisante pour assigner des rôles"
        except Exception as e:
            role_status = f"Erreur lors de l'attribution du rôle : {e}"

        # Message de bienvenue personnalisé
        settings = get_guild_settings(member.guild.id)
        if settings and settings[5]:  # welcome_channel_id
            welcome_channel = member.guild.get_channel(settings[5])
            if welcome_channel:
                welcome_msg = settings[6] or "Bienvenue sur **{server}**, {mention} ! 🎉"
                welcome_msg = (
                    welcome_msg
                    .replace("{mention}", member.mention)
                    .replace("{server}", member.guild.name)
                    .replace("{count}", str(member.guild.member_count))
                )
                try:
                    welcome_embed = discord.Embed(
                        title="👋 Bienvenue !",
                        description=welcome_msg,
                        color=COLORS['success'],
                        timestamp=datetime.utcnow()
                    )
                    welcome_embed.set_thumbnail(url=member.display_avatar.url)
                    await welcome_channel.send(embed=welcome_embed)
                except discord.Forbidden:
                    pass

        # Log d'arrivée
        embed = discord.Embed(
            title="📥 Membre Rejoint",
            description=f"{member.mention} a rejoint le serveur",
            color=COLORS['success'],
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Utilisateur", value=f"{member} (ID : {member.id})", inline=True)
        embed.add_field(name="Compte Créé le", value=member.created_at.strftime("%Y-%m-%d %H:%M:%S"), inline=True)
        embed.add_field(name="Nombre de Membres", value=str(member.guild.member_count), inline=True)
        embed.add_field(name="Attribution de Rôle", value=role_status, inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)
        await self.send_log(member.guild, embed)

    # ------------------------------------------------------------------
    # Membre parti
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        embed = discord.Embed(
            title="📤 Membre Parti",
            description=f"{member.mention} a quitté le serveur",
            color=COLORS['error'],
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Utilisateur", value=f"{member} (ID : {member.id})", inline=True)
        embed.add_field(name="Rejoint le", value=member.joined_at.strftime("%Y-%m-%d %H:%M:%S") if member.joined_at else "Inconnu", inline=True)
        embed.add_field(name="Nombre de Membres", value=str(member.guild.member_count), inline=True)
        embed.set_thumbnail(url=member.display_avatar.url)
        await self.send_log(member.guild, embed)

    # ------------------------------------------------------------------
    # Message supprimé
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if message.author.bot or not message.guild:
            return

        embed = discord.Embed(
            title="🗑️ Message Supprimé",
            description=f"Message de {message.author.mention} supprimé dans {message.channel.mention}",
            color=COLORS['error'],
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Auteur", value=f"{message.author} (ID : {message.author.id})", inline=True)
        embed.add_field(name="Salon", value=message.channel.mention, inline=True)
        embed.add_field(name="ID Message", value=str(message.id), inline=True)

        if message.content:
            content = message.content[:1000] + "..." if len(message.content) > 1000 else message.content
            embed.add_field(name="Contenu", value=f"```{content}```", inline=False)

        if message.attachments:
            attachments = "\n".join(att.filename for att in message.attachments)
            embed.add_field(name="Pièces jointes", value=attachments, inline=False)

        await self.send_log(message.guild, embed)

    # ------------------------------------------------------------------
    # Message modifié
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if before.author.bot or not before.guild or before.content == after.content:
            return

        embed = discord.Embed(
            title="✏️ Message Modifié",
            description=f"Message de {before.author.mention} modifié dans {before.channel.mention}",
            color=COLORS['warning'],
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Auteur", value=f"{before.author} (ID : {before.author.id})", inline=True)
        embed.add_field(name="Salon", value=before.channel.mention, inline=True)
        embed.add_field(name="ID Message", value=str(before.id), inline=True)

        if before.content:
            before_content = before.content[:500] + "..." if len(before.content) > 500 else before.content
            embed.add_field(name="Avant", value=f"```{before_content}```", inline=False)

        if after.content:
            after_content = after.content[:500] + "..." if len(after.content) > 500 else after.content
            embed.add_field(name="Après", value=f"```{after_content}```", inline=False)

        await self.send_log(before.guild, embed)

    # ------------------------------------------------------------------
    # Membre banni
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        reason = "Aucune raison fournie"
        moderator = None
        try:
            async for entry in guild.audit_logs(action=discord.AuditLogAction.ban, limit=1):
                if entry.target.id == user.id:
                    reason = entry.reason or "Aucune raison fournie"
                    moderator = entry.user
                    break
        except discord.Forbidden:
            pass

        embed = discord.Embed(
            title="🔨 Membre Banni",
            description=f"{user.mention} a été banni du serveur",
            color=COLORS['error'],
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Utilisateur", value=f"{user} (ID : {user.id})", inline=True)
        embed.add_field(name="Modérateur", value=moderator.mention if moderator else "Inconnu", inline=True)
        embed.add_field(name="Raison", value=reason, inline=False)
        embed.set_thumbnail(url=user.display_avatar.url)
        await self.send_log(guild, embed)

    # ------------------------------------------------------------------
    # Membre débanni
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        reason = "Aucune raison fournie"
        moderator = None
        try:
            async for entry in guild.audit_logs(action=discord.AuditLogAction.unban, limit=1):
                if entry.target.id == user.id:
                    reason = entry.reason or "Aucune raison fournie"
                    moderator = entry.user
                    break
        except discord.Forbidden:
            pass

        embed = discord.Embed(
            title="✅ Membre Débanni",
            description=f"{user.mention} a été débanni du serveur",
            color=COLORS['success'],
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Utilisateur", value=f"{user} (ID : {user.id})", inline=True)
        embed.add_field(name="Modérateur", value=moderator.mention if moderator else "Inconnu", inline=True)
        embed.add_field(name="Raison", value=reason, inline=False)
        embed.set_thumbnail(url=user.display_avatar.url)
        await self.send_log(guild, embed)

    # ------------------------------------------------------------------
    # Logs de rôles
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if before.roles == after.roles:
            return

        added = [r for r in after.roles if r not in before.roles]
        removed = [r for r in before.roles if r not in after.roles]

        if not added and not removed:
            return

        embed = discord.Embed(
            title="🏷️ Rôles Modifiés",
            description=f"Les rôles de {after.mention} ont été modifiés",
            color=COLORS['info'],
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Membre", value=f"{after} (ID : {after.id})", inline=True)

        if added:
            embed.add_field(name="Rôles Ajoutés", value=" ".join(r.mention for r in added), inline=False)
        if removed:
            embed.add_field(name="Rôles Retirés", value=" ".join(r.mention for r in removed), inline=False)

        await self.send_log(after.guild, embed)

    # ------------------------------------------------------------------
    # /setlogchannel
    # ------------------------------------------------------------------

    @discord.app_commands.command(name="setlogchannel", description="Définir le salon des logs de modération")
    @discord.app_commands.describe(channel="Le salon à utiliser pour les logs")
    async def setlogchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Vous devez être administrateur pour définir le salon de logs !", ephemeral=True)
            return

        update_guild_settings(interaction.guild.id, log_channel_id=channel.id)

        embed = discord.Embed(
            title="✅ Salon de Logs Défini",
            description=f"Les logs de modération seront envoyés dans {channel.mention}",
            color=COLORS['success']
        )
        await interaction.response.send_message(embed=embed)

        test_embed = discord.Embed(
            title="📋 Système de Logs Actif",
            description="Ce salon a été défini comme salon de logs de modération.",
            color=COLORS['info'],
            timestamp=datetime.utcnow()
        )
        test_embed.add_field(name="Défini par", value=interaction.user.mention, inline=True)
        await channel.send(embed=test_embed)


async def setup(bot):
    await bot.add_cog(Logging(bot))
