import discord
from discord.ext import commands
from discord import app_commands
import logging

logger = logging.getLogger(__name__)

AUTOROLE_NAME = "Membre"


class AutoRole(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        role = discord.utils.get(member.guild.roles, name=AUTOROLE_NAME)
        if role is None:
            logger.warning(
                f"[AutoRole] Rôle '{AUTOROLE_NAME}' introuvable sur {member.guild.name}. "
                "Crée-le ou utilise /autorole set."
            )
            return
        try:
            await member.add_roles(role, reason="Auto-attribution rôle Membre")
            logger.info(f"[AutoRole] Rôle '{AUTOROLE_NAME}' attribué à {member} ({member.guild.name})")
        except discord.Forbidden:
            logger.error(
                f"[AutoRole] Permission refusée pour attribuer '{AUTOROLE_NAME}' à {member}. "
                "Vérifie que le bot est au-dessus du rôle dans la hiérarchie."
            )
        except discord.HTTPException as e:
            logger.error(f"[AutoRole] Erreur HTTP lors de l'attribution du rôle : {e}")

    # ---------- slash commands ----------

    @app_commands.command(name="autorole_create", description="Crée le rôle 'Membre' s'il n'existe pas encore")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def autorole_create(self, interaction: discord.Interaction):
        existing = discord.utils.get(interaction.guild.roles, name=AUTOROLE_NAME)
        if existing:
            await interaction.response.send_message(
                f"✅ Le rôle **{AUTOROLE_NAME}** existe déjà.", ephemeral=True
            )
            return
        try:
            role = await interaction.guild.create_role(
                name=AUTOROLE_NAME,
                reason=f"Créé par {interaction.user} via /autorole_create",
            )
            await interaction.response.send_message(
                f"✅ Rôle **{role.name}** créé avec succès. Il sera attribué automatiquement aux nouveaux membres.",
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Je n'ai pas la permission de créer des rôles.", ephemeral=True
            )

    @autorole_create.error
    async def autorole_create_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ Tu n'as pas la permission de gérer les rôles.", ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoRole(bot))
