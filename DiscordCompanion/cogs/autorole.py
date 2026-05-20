import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime
import logging

from utils.database import get_guild_settings, update_guild_settings
from config import COLORS

logger = logging.getLogger(__name__)

ROLE_SOUMISES = "soumises"


class ShabView(discord.ui.View):

    def __init__(self, member: discord.Member):
        super().__init__(timeout=None)
        self.member = member

    @discord.ui.button(label="✅ Oui", style=discord.ButtonStyle.danger, custom_id="shab_oui")
    async def oui(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message(
                "❌ Tu n'as pas la permission de gérer les rôles.", ephemeral=True
            )
            return

        member = interaction.guild.get_member(self.member.id)
        if member is None:
            await interaction.response.send_message(
                "❌ Le membre a quitté le serveur.", ephemeral=True
            )
            self._disable_all()
            await interaction.message.edit(view=self)
            return

        role = discord.utils.get(interaction.guild.roles, name=ROLE_SOUMISES)
        if role is None:
            await interaction.response.send_message(
                f"❌ Le rôle **{ROLE_SOUMISES}** est introuvable. Crée-le d'abord avec `/autorole_create_soumises`.",
                ephemeral=True,
            )
            return

        try:
            await member.add_roles(role, reason=f"Shab confirmé par {interaction.user}")
            logger.info(f"[AutoRole] Rôle '{ROLE_SOUMISES}' attribué à {member} par {interaction.user}")
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Je n'ai pas la permission d'attribuer ce rôle (vérifie la hiérarchie).", ephemeral=True
            )
            return

        self._disable_all()
        embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
        embed.color = COLORS['error']
        embed.set_footer(text=f"✅ Rôle '{ROLE_SOUMISES}' attribué par {interaction.user} • {datetime.utcnow().strftime('%H:%M:%S')}")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="❌ Non", style=discord.ButtonStyle.success, custom_id="shab_non")
    async def non(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message(
                "❌ Tu n'as pas la permission de gérer les rôles.", ephemeral=True
            )
            return

        self._disable_all()
        embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
        embed.color = COLORS['success']
        embed.set_footer(text=f"✅ Confirmé : pas un shab — {interaction.user} • {datetime.utcnow().strftime('%H:%M:%S')}")
        await interaction.response.edit_message(embed=embed, view=self)

    def _disable_all(self):
        for item in self.children:
            item.disabled = True


class AutoRole(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _get_mod_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        settings = get_guild_settings(guild.id)
        if settings and len(settings) > 7 and settings[7]:
            return guild.get_channel(settings[7])
        return None

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        mod_channel = self._get_mod_channel(member.guild)
        if mod_channel is None:
            logger.warning(
                f"[AutoRole] Aucun salon modérateur défini pour {member.guild.name}. "
                "Utilise /setmodchannel pour en définir un."
            )
            return

        embed = discord.Embed(
            title="🔎 Nouveau membre — Vérification",
            description=(
                f"{member.mention} vient de rejoindre le serveur.\n\n"
                f"**Est-ce que c'est un shab ?**"
            ),
            color=COLORS['warning'],
            timestamp=datetime.utcnow(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Utilisateur", value=f"{member} (ID : {member.id})", inline=True)
        embed.add_field(
            name="Compte créé le",
            value=member.created_at.strftime("%d/%m/%Y %H:%M"),
            inline=True,
        )

        try:
            await mod_channel.send(embed=embed, view=ShabView(member))
        except discord.Forbidden:
            logger.error(f"[AutoRole] Permission refusée pour écrire dans {mod_channel.name}")

    @app_commands.command(
        name="setmodchannel",
        description="Définir le salon modérateur où arrivent les vérifications de nouveaux membres",
    )
    @app_commands.describe(channel="Le salon modérateur (accès réservé au staff)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setmodchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        update_guild_settings(interaction.guild.id, mod_channel_id=channel.id)
        embed = discord.Embed(
            title="✅ Salon modérateur défini",
            description=f"Les vérifications de nouveaux membres seront envoyées dans {channel.mention}.",
            color=COLORS['success'],
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

        confirm = discord.Embed(
            title="🔒 Salon modérateur actif",
            description="Ce salon recevra désormais les alertes de vérification des nouveaux membres.",
            color=COLORS['info'],
            timestamp=datetime.utcnow(),
        )
        confirm.add_field(name="Configuré par", value=interaction.user.mention)
        await channel.send(embed=confirm)

    @setmodchannel.error
    async def setmodchannel_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ Tu dois être administrateur pour configurer ce salon.", ephemeral=True
            )

    @app_commands.command(
        name="autorole_create_soumises",
        description="Crée le rôle 'soumises' s'il n'existe pas encore",
    )
    @app_commands.checks.has_permissions(manage_roles=True)
    async def autorole_create_soumises(self, interaction: discord.Interaction):
        existing = discord.utils.get(interaction.guild.roles, name=ROLE_SOUMISES)
        if existing:
            await interaction.response.send_message(
                f"✅ Le rôle **{ROLE_SOUMISES}** existe déjà.", ephemeral=True
            )
            return
        try:
            role = await interaction.guild.create_role(
                name=ROLE_SOUMISES,
                reason=f"Créé par {interaction.user} via /autorole_create_soumises",
            )
            await interaction.response.send_message(
                f"✅ Rôle **{role.name}** créé avec succès.", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Je n'ai pas la permission de créer des rôles.", ephemeral=True
            )

    @autorole_create_soumises.error
    async def autorole_create_soumises_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ Tu n'as pas la permission de gérer les rôles.", ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoRole(bot))
