import discord
from discord.ext import commands, tasks
from discord import app_commands
from utils.permissions import ensure_mute_role
from utils.database import (
    add_warning, get_warnings, clear_warnings,
    add_mute, remove_mute, get_active_timed_mutes,
    add_tempban, deactivate_tempban, get_active_tempbans,
    add_sanction, get_sanctions, get_case, edit_case_reason,
    add_blacklist_word, remove_blacklist_word, get_blacklist_words,
    update_guild_settings, get_guild_settings,
    get_automod_config, update_automod_config,
    get_violation_points, reset_violation_points,
    parse_duration, format_duration,
)
from utils.ui import PaginationView, ConfirmView, build_pages
from config import COLORS, MAX_WARNINGS
from datetime import datetime, timedelta
import asyncio


ACTION_EMOJIS = {
    'kick': '👢', 'ban': '🔨', 'tempban': '⏱️',
    'mute': '🔇', 'unmute': '🔊', 'warn': '⚠️', 'unban': '✅',
}


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.check_expired_punishments.start()

    async def cog_unload(self):
        self.check_expired_punishments.cancel()

    # ------------------------------------------------------------------
    # Background task
    # ------------------------------------------------------------------

    @tasks.loop(minutes=1)
    async def check_expired_punishments(self):
        now = datetime.utcnow()

        for guild_id, user_id, unban_at_str in get_active_tempbans():
            try:
                if now >= datetime.fromisoformat(unban_at_str):
                    guild = self.bot.get_guild(guild_id)
                    if guild:
                        try:
                            user = await self.bot.fetch_user(user_id)
                            await guild.unban(user, reason="Tempban expiré automatiquement")
                        except (discord.NotFound, discord.Forbidden):
                            pass
                    deactivate_tempban(guild_id, user_id)
            except Exception:
                pass

        _mute_roles: dict[int, discord.Role] = {}
        for guild_id, user_id, unmute_at_str in get_active_timed_mutes():
            try:
                if now >= datetime.fromisoformat(unmute_at_str):
                    guild = self.bot.get_guild(guild_id)
                    if guild:
                        member = guild.get_member(user_id)
                        if member:
                            if guild_id not in _mute_roles:
                                _mute_roles[guild_id] = await ensure_mute_role(guild)
                            r = _mute_roles[guild_id]
                            if r in member.roles:
                                await member.remove_roles(r, reason="Mute temporaire expiré")
                    remove_mute(guild_id, user_id)
            except Exception:
                pass

    @check_expired_punishments.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _case_footer(self, case_id: int, member_id: int) -> str:
        return f"Case #{case_id} • ID : {member_id}"

    async def _send_dm(self, member: discord.Member, embed: discord.Embed):
        try:
            await member.send(embed=embed)
        except discord.Forbidden:
            pass

    async def _confirm_action(self, interaction: discord.Interaction, preview_embed: discord.Embed) -> bool:
        """Affiche un embed de confirmation et retourne True si confirmé."""
        view = ConfirmView(interaction.user.id)
        await interaction.response.send_message(embed=preview_embed, view=view, ephemeral=True)
        await view.wait()
        if not view.value:
            annule = discord.Embed(title="❌ Action Annulée", color=COLORS['error'])
            await interaction.edit_original_response(embed=annule, view=None)
        return bool(view.value)

    # ------------------------------------------------------------------
    # /kick
    # ------------------------------------------------------------------

    @app_commands.command(name="kick", description="Expulser un membre du serveur")
    @app_commands.describe(member="Le membre à expulser", raison="Raison de l'expulsion")
    async def kick(self, interaction: discord.Interaction, member: discord.Member, raison: str = "Aucune raison fournie"):
        if not interaction.user.guild_permissions.kick_members:
            return await interaction.response.send_message("❌ Vous n'avez pas la permission d'expulser des membres !", ephemeral=True)
        if not interaction.guild.me.guild_permissions.kick_members:
            return await interaction.response.send_message("❌ Je n'ai pas la permission d'expulser des membres !", ephemeral=True)
        if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
            return await interaction.response.send_message("❌ Rôle supérieur ou égal — action impossible !", ephemeral=True)
        if member.top_role >= interaction.guild.me.top_role:
            return await interaction.response.send_message("❌ Je ne peux pas agir sur ce membre (rôle supérieur au mien) !", ephemeral=True)

        preview = discord.Embed(
            title="👢 Confirmer l'Expulsion",
            description=f"Vous êtes sur le point d'expulser **{member}**.",
            color=COLORS['warning']
        )
        preview.add_field(name="Raison", value=raison)
        if not await self._confirm_action(interaction, preview):
            return

        try:
            await self._send_dm(member, discord.Embed(
                title="Vous avez été expulsé",
                description=f"Vous avez été expulsé de **{interaction.guild.name}**",
                color=COLORS['warning']
            ).add_field(name="Raison", value=raison).add_field(name="Modérateur", value=str(interaction.user)))

            await member.kick(reason=f"Expulsé par {interaction.user} | {raison}")
            case_id = add_sanction(interaction.guild.id, member.id, interaction.user.id, 'kick', raison)

            embed = discord.Embed(title="✅ Membre Expulsé", description=f"**{member}** a été expulsé.", color=COLORS['success'])
            embed.add_field(name="Modérateur", value=interaction.user.mention, inline=True)
            embed.add_field(name="Raison", value=raison, inline=True)
            embed.set_footer(text=self._case_footer(case_id, member.id))
            await interaction.edit_original_response(embed=embed, view=None)
        except discord.Forbidden:
            await interaction.edit_original_response(embed=discord.Embed(title="❌ Permission refusée", color=COLORS['error']), view=None)

    # ------------------------------------------------------------------
    # /ban
    # ------------------------------------------------------------------

    @app_commands.command(name="ban", description="Bannir un membre du serveur")
    @app_commands.describe(member="Le membre à bannir", raison="Raison du bannissement", supprimer_jours="Jours de messages à supprimer (0-7)")
    async def ban(self, interaction: discord.Interaction, member: discord.Member, raison: str = "Aucune raison fournie", supprimer_jours: int = 0):
        if not interaction.user.guild_permissions.ban_members:
            return await interaction.response.send_message("❌ Vous n'avez pas la permission de bannir des membres !", ephemeral=True)
        if not interaction.guild.me.guild_permissions.ban_members:
            return await interaction.response.send_message("❌ Je n'ai pas la permission de bannir des membres !", ephemeral=True)
        if not 0 <= supprimer_jours <= 7:
            return await interaction.response.send_message("❌ Les jours doivent être entre 0 et 7 !", ephemeral=True)
        if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
            return await interaction.response.send_message("❌ Rôle supérieur ou égal — action impossible !", ephemeral=True)
        if member.top_role >= interaction.guild.me.top_role:
            return await interaction.response.send_message("❌ Je ne peux pas agir sur ce membre !", ephemeral=True)

        preview = discord.Embed(title="🔨 Confirmer le Bannissement", description=f"Vous êtes sur le point de bannir **{member}**.", color=COLORS['error'])
        preview.add_field(name="Raison", value=raison)
        preview.add_field(name="Messages supprimés", value=f"{supprimer_jours} jours")
        if not await self._confirm_action(interaction, preview):
            return

        try:
            dm = discord.Embed(title="Vous avez été banni", description=f"Vous avez été banni de **{interaction.guild.name}**", color=COLORS['error'])
            dm.add_field(name="Raison", value=raison)
            dm.add_field(name="Modérateur", value=str(interaction.user))
            await self._send_dm(member, dm)

            await member.ban(reason=f"Banni par {interaction.user} | {raison}", delete_message_days=supprimer_jours)
            case_id = add_sanction(interaction.guild.id, member.id, interaction.user.id, 'ban', raison)

            embed = discord.Embed(title="🔨 Membre Banni", description=f"**{member}** a été banni.", color=COLORS['error'])
            embed.add_field(name="Modérateur", value=interaction.user.mention, inline=True)
            embed.add_field(name="Raison", value=raison, inline=True)
            embed.add_field(name="Messages Supprimés", value=f"{supprimer_jours} jours", inline=True)
            embed.set_footer(text=self._case_footer(case_id, member.id))
            await interaction.edit_original_response(embed=embed, view=None)
        except discord.Forbidden:
            await interaction.edit_original_response(embed=discord.Embed(title="❌ Permission refusée", color=COLORS['error']), view=None)

    # ------------------------------------------------------------------
    # /tempban
    # ------------------------------------------------------------------

    @app_commands.command(name="tempban", description="Bannir temporairement un membre")
    @app_commands.describe(member="Le membre à bannir", duree="Durée (ex: 10m, 2h, 1d)", raison="Raison")
    async def tempban(self, interaction: discord.Interaction, member: discord.Member, duree: str, raison: str = "Aucune raison fournie"):
        if not interaction.user.guild_permissions.ban_members:
            return await interaction.response.send_message("❌ Vous n'avez pas la permission de bannir des membres !", ephemeral=True)
        if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
            return await interaction.response.send_message("❌ Rôle supérieur ou égal — action impossible !", ephemeral=True)

        seconds = parse_duration(duree)
        if seconds is None:
            return await interaction.response.send_message("❌ Format invalide. Exemples : `10m`, `2h`, `1d`", ephemeral=True)

        unban_at = datetime.utcnow() + timedelta(seconds=seconds)
        duree_lisible = format_duration(seconds)

        preview = discord.Embed(title="⏱️ Confirmer le Bannissement Temporaire", description=f"Bannir **{member}** pendant **{duree_lisible}** ?", color=COLORS['error'])
        preview.add_field(name="Raison", value=raison)
        if not await self._confirm_action(interaction, preview):
            return

        try:
            dm = discord.Embed(title="Vous avez été banni temporairement", description=f"Banni de **{interaction.guild.name}** pendant **{duree_lisible}**.", color=COLORS['error'])
            dm.add_field(name="Raison", value=raison)
            await self._send_dm(member, dm)

            await member.ban(reason=f"Tempban ({duree_lisible}) par {interaction.user} | {raison}")
            add_tempban(interaction.guild.id, member.id, interaction.user.id, raison, unban_at)
            case_id = add_sanction(interaction.guild.id, member.id, interaction.user.id, 'tempban', raison, duree)

            embed = discord.Embed(title="⏱️ Membre Banni Temporairement", description=f"**{member}** banni pour **{duree_lisible}**.", color=COLORS['error'])
            embed.add_field(name="Modérateur", value=interaction.user.mention, inline=True)
            embed.add_field(name="Durée", value=duree_lisible, inline=True)
            embed.add_field(name="Raison", value=raison, inline=True)
            embed.add_field(name="Débannissement le", value=f"<t:{int(unban_at.timestamp())}:F>", inline=False)
            embed.set_footer(text=self._case_footer(case_id, member.id))
            await interaction.edit_original_response(embed=embed, view=None)
        except discord.Forbidden:
            await interaction.edit_original_response(embed=discord.Embed(title="❌ Permission refusée", color=COLORS['error']), view=None)

    # ------------------------------------------------------------------
    # /unban
    # ------------------------------------------------------------------

    @app_commands.command(name="unban", description="Débannir un utilisateur du serveur")
    @app_commands.describe(user_id="L'ID de l'utilisateur à débannir", raison="Raison")
    async def unban(self, interaction: discord.Interaction, user_id: str, raison: str = "Aucune raison fournie"):
        if not interaction.user.guild_permissions.ban_members:
            return await interaction.response.send_message("❌ Vous n'avez pas la permission de débannir !", ephemeral=True)
        try:
            uid = int(user_id)
        except ValueError:
            return await interaction.response.send_message("❌ ID invalide !", ephemeral=True)
        try:
            bans = [e async for e in interaction.guild.bans(limit=2000)]
            banned_user = next((e.user for e in bans if e.user.id == uid), None)
            if not banned_user:
                return await interaction.response.send_message("❌ Cet utilisateur n'est pas banni !", ephemeral=True)

            await interaction.guild.unban(banned_user, reason=f"Débanni par {interaction.user} | {raison}")
            deactivate_tempban(interaction.guild.id, uid)
            case_id = add_sanction(interaction.guild.id, uid, interaction.user.id, 'unban', raison)

            embed = discord.Embed(title="✅ Membre Débanni", description=f"**{banned_user}** a été débanni.", color=COLORS['success'])
            embed.add_field(name="Modérateur", value=interaction.user.mention, inline=True)
            embed.add_field(name="Raison", value=raison, inline=True)
            embed.set_footer(text=self._case_footer(case_id, uid))
            await interaction.response.send_message(embed=embed)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Permission refusée !", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Erreur : {e}", ephemeral=True)

    # ------------------------------------------------------------------
    # /mute
    # ------------------------------------------------------------------

    @app_commands.command(name="mute", description="Rendre muet un membre")
    @app_commands.describe(member="Le membre à rendre muet", duree="Durée optionnelle (ex: 10m, 2h)", raison="Raison")
    async def mute(self, interaction: discord.Interaction, member: discord.Member, duree: str = None, raison: str = "Aucune raison fournie"):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Permission insuffisante !", ephemeral=True)
        if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
            return await interaction.response.send_message("❌ Rôle supérieur ou égal — action impossible !", ephemeral=True)

        seconds = None
        unmute_at = None
        duree_lisible = "Permanent"
        if duree:
            seconds = parse_duration(duree)
            if seconds is None:
                return await interaction.response.send_message("❌ Format invalide. Exemples : `10m`, `2h`, `1d`", ephemeral=True)
            unmute_at = datetime.utcnow() + timedelta(seconds=seconds)
            duree_lisible = format_duration(seconds)

        try:
            mute_role = await ensure_mute_role(interaction.guild)
            if mute_role in member.roles:
                return await interaction.response.send_message("❌ Ce membre est déjà muet !", ephemeral=True)

            await member.add_roles(mute_role, reason=f"Mute par {interaction.user} | {raison}")
            add_mute(interaction.guild.id, member.id, interaction.user.id, raison, unmute_at)
            case_id = add_sanction(interaction.guild.id, member.id, interaction.user.id, 'mute', raison, duree)

            embed = discord.Embed(title="🔇 Membre Rendu Muet", description=f"**{member}** est maintenant muet.", color=COLORS['warning'])
            embed.add_field(name="Modérateur", value=interaction.user.mention, inline=True)
            embed.add_field(name="Durée", value=duree_lisible, inline=True)
            embed.add_field(name="Raison", value=raison, inline=True)
            if unmute_at:
                embed.add_field(name="Unmute le", value=f"<t:{int(unmute_at.timestamp())}:F>", inline=False)
            embed.set_footer(text=self._case_footer(case_id, member.id))
            await interaction.response.send_message(embed=embed)

            if seconds:
                async def _unmute():
                    await asyncio.sleep(seconds)
                    try:
                        if mute_role in member.roles:
                            await member.remove_roles(mute_role, reason="Mute temporaire expiré")
                        remove_mute(interaction.guild.id, member.id)
                    except (discord.Forbidden, discord.NotFound):
                        pass
                self.bot.loop.create_task(_unmute())
        except discord.Forbidden:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Permission refusée !", ephemeral=True)

    # ------------------------------------------------------------------
    # /unmute
    # ------------------------------------------------------------------

    @app_commands.command(name="unmute", description="Retirer le mute d'un membre")
    @app_commands.describe(member="Le membre à unmute", raison="Raison")
    async def unmute(self, interaction: discord.Interaction, member: discord.Member, raison: str = "Aucune raison fournie"):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Permission insuffisante !", ephemeral=True)
        try:
            mute_role = await ensure_mute_role(interaction.guild)
            if mute_role not in member.roles:
                return await interaction.response.send_message("❌ Ce membre n'est pas muet !", ephemeral=True)

            await member.remove_roles(mute_role, reason=f"Unmute par {interaction.user} | {raison}")
            remove_mute(interaction.guild.id, member.id)
            case_id = add_sanction(interaction.guild.id, member.id, interaction.user.id, 'unmute', raison)

            embed = discord.Embed(title="🔊 Membre Unmute", description=f"**{member}** n'est plus muet.", color=COLORS['success'])
            embed.add_field(name="Modérateur", value=interaction.user.mention, inline=True)
            embed.add_field(name="Raison", value=raison, inline=True)
            embed.set_footer(text=self._case_footer(case_id, member.id))
            await interaction.response.send_message(embed=embed)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Permission refusée !", ephemeral=True)

    # ------------------------------------------------------------------
    # /warn
    # ------------------------------------------------------------------

    @app_commands.command(name="warn", description="Avertir un membre")
    @app_commands.describe(member="Le membre à avertir", raison="Raison")
    async def warn(self, interaction: discord.Interaction, member: discord.Member, raison: str = "Aucune raison fournie"):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Permission insuffisante !", ephemeral=True)

        add_warning(interaction.guild.id, member.id, interaction.user.id, raison)
        case_id = add_sanction(interaction.guild.id, member.id, interaction.user.id, 'warn', raison)
        warnings = get_warnings(interaction.guild.id, member.id)
        count = len(warnings)

        embed = discord.Embed(title="⚠️ Membre Averti", description=f"**{member}** a été averti.", color=COLORS['warning'])
        embed.add_field(name="Modérateur", value=interaction.user.mention, inline=True)
        embed.add_field(name="Raison", value=raison, inline=True)
        embed.add_field(name="Total", value=f"{count}/{MAX_WARNINGS}", inline=True)
        embed.set_footer(text=self._case_footer(case_id, member.id))

        if count >= MAX_WARNINGS:
            try:
                mute_role = await ensure_mute_role(interaction.guild)
                if mute_role not in member.roles:
                    await member.add_roles(mute_role, reason="Auto-mute : max avertissements atteint")
                    embed.add_field(name="Action Automatique", value="🔇 Auto-mute déclenché", inline=False)
            except discord.Forbidden:
                pass

        await interaction.response.send_message(embed=embed)
        await self._send_dm(member, discord.Embed(
            title="Vous avez été averti",
            description=f"Avertissement dans **{interaction.guild.name}**",
            color=COLORS['warning']
        ).add_field(name="Raison", value=raison).add_field(name="Avertissements", value=f"{count}/{MAX_WARNINGS}"))

    # ------------------------------------------------------------------
    # /warnings
    # ------------------------------------------------------------------

    @app_commands.command(name="warnings", description="Voir les avertissements d'un membre")
    @app_commands.describe(member="Le membre concerné")
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        warns = get_warnings(interaction.guild.id, member.id)
        if not warns:
            embed = discord.Embed(title="✅ Aucun Avertissement", description=f"**{member}** n'a aucun avertissement.", color=COLORS['success'])
            embed.set_footer(text=f"ID : {member.id}")
            return await interaction.response.send_message(embed=embed)

        def fmt(i, w):
            mod = interaction.guild.get_member(w[1])
            mod_str = mod.mention if mod else f"<@{w[1]}>"
            return f"Avertissement #{i}", f"**Raison :** {w[2]}\n**Modérateur :** {mod_str}\n**Date :** {w[3]}"

        pages = build_pages(warns, f"⚠️ Avertissements de {member}", COLORS['warning'], per_page=5, entry_formatter=fmt)
        for p in pages:
            p.description = f"Total : **{len(warns)}** avertissement(s)"
            p.set_footer(text=f"ID : {member.id} • Page {{page}}/{len(pages)}")

        if len(pages) == 1:
            return await interaction.response.send_message(embed=pages[0])

        view = PaginationView(pages, author_id=interaction.user.id)
        await interaction.response.send_message(embed=pages[0], view=view)
        view.message = await interaction.original_response()

    # ------------------------------------------------------------------
    # /clearwarnings
    # ------------------------------------------------------------------

    @app_commands.command(name="clearwarnings", description="Effacer tous les avertissements d'un membre")
    @app_commands.describe(member="Le membre concerné")
    async def clearwarnings(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Permission insuffisante !", ephemeral=True)
        warns = get_warnings(interaction.guild.id, member.id)
        if not warns:
            return await interaction.response.send_message(f"❌ **{member}** n'a aucun avertissement.", ephemeral=True)
        clear_warnings(interaction.guild.id, member.id)
        embed = discord.Embed(title="✅ Avertissements Effacés", description=f"**{len(warns)}** avertissement(s) effacé(s) pour **{member}**.", color=COLORS['success'])
        embed.add_field(name="Modérateur", value=interaction.user.mention)
        embed.set_footer(text=f"ID : {member.id}")
        await interaction.response.send_message(embed=embed)

    # ------------------------------------------------------------------
    # /purge
    # ------------------------------------------------------------------

    @app_commands.command(name="purge", description="Supprimer plusieurs messages d'un coup")
    @app_commands.describe(nombre="Nombre de messages (1-100)", membre="Ne supprimer que les messages de ce membre")
    async def purge(self, interaction: discord.Interaction, nombre: int, membre: discord.Member = None):
        # Defer en premier — les vérifications viennent ensuite via followup
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.followup.send("❌ Permission insuffisante !", ephemeral=True)
        if not 1 <= nombre <= 100:
            return await interaction.followup.send("❌ Le nombre doit être entre 1 et 100 !", ephemeral=True)
        try:
            check = (lambda m: m.author == membre) if membre else None
            deleted = await interaction.channel.purge(limit=nombre, check=check)
            embed = discord.Embed(title="🗑️ Messages Supprimés", description=f"**{len(deleted)}** message(s) supprimé(s).", color=COLORS['success'])
            embed.add_field(name="Modérateur", value=interaction.user.mention, inline=True)
            if membre:
                embed.add_field(name="Membre ciblé", value=membre.mention, inline=True)
            embed.add_field(name="Salon", value=interaction.channel.mention, inline=True)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ Permission refusée !", ephemeral=True)

    # ------------------------------------------------------------------
    # /slowmode
    # ------------------------------------------------------------------

    @app_commands.command(name="slowmode", description="Activer ou désactiver le mode lent sur un salon")
    @app_commands.describe(secondes="Délai en secondes (0 = désactiver, max 21600)", salon="Salon (défaut : actuel)")
    async def slowmode(self, interaction: discord.Interaction, secondes: int = 0, salon: discord.TextChannel = None):
        if not interaction.user.guild_permissions.manage_channels:
            return await interaction.response.send_message("❌ Permission insuffisante !", ephemeral=True)
        if not 0 <= secondes <= 21600:
            return await interaction.response.send_message("❌ Valeur entre 0 et 21600 secondes.", ephemeral=True)
        target = salon or interaction.channel
        await target.edit(slowmode_delay=secondes)
        if secondes == 0:
            embed = discord.Embed(title="✅ Mode Lent Désactivé", description=f"Mode lent désactivé dans {target.mention}.", color=COLORS['success'])
        else:
            embed = discord.Embed(title="🐢 Mode Lent Activé", description=f"Mode lent activé dans {target.mention}.", color=COLORS['info'])
            embed.add_field(name="Délai", value=format_duration(secondes))
        embed.add_field(name="Modérateur", value=interaction.user.mention)
        await interaction.response.send_message(embed=embed)

    # ------------------------------------------------------------------
    # /userinfo
    # ------------------------------------------------------------------

    @app_commands.command(name="userinfo", description="Informations complètes sur un membre")
    @app_commands.describe(member="Le membre à inspecter (défaut : vous-même)")
    async def userinfo(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        sanctions = get_sanctions(interaction.guild.id, member.id)
        pts = get_violation_points(interaction.guild.id, member.id)

        roles = [r.mention for r in reversed(member.roles) if r != interaction.guild.default_role]
        roles_str = " ".join(roles[:10]) + (f" *+{len(roles) - 10} autres*" if len(roles) > 10 else "") if roles else "Aucun rôle"

        embed = discord.Embed(title=f"👤 Profil de {member}", color=member.color if member.color.value else COLORS['info'])
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Nom d'utilisateur", value=str(member), inline=True)
        embed.add_field(name="Pseudonyme", value=member.display_name, inline=True)
        embed.add_field(name="ID", value=str(member.id), inline=True)
        embed.add_field(name="Compte créé le", value=f"<t:{int(member.created_at.timestamp())}:D>", inline=True)
        embed.add_field(name="Rejoint le", value=f"<t:{int(member.joined_at.timestamp())}:D>" if member.joined_at else "Inconnu", inline=True)
        embed.add_field(name="Bot", value="Oui" if member.bot else "Non", inline=True)
        embed.add_field(name=f"Rôles ({len(member.roles) - 1})", value=roles_str, inline=False)
        embed.add_field(name="Sanctions enregistrées", value=str(len(sanctions)), inline=True)
        embed.add_field(name="Points auto-mod", value=str(pts), inline=True)
        if member.premium_since:
            embed.add_field(name="Boost depuis", value=f"<t:{int(member.premium_since.timestamp())}:D>", inline=True)
        embed.set_footer(text=f"ID : {member.id}")
        await interaction.response.send_message(embed=embed)

    # ------------------------------------------------------------------
    # /serverinfo
    # ------------------------------------------------------------------

    @app_commands.command(name="serverinfo", description="Informations sur le serveur")
    async def serverinfo(self, interaction: discord.Interaction):
        g = interaction.guild
        embed = discord.Embed(title=f"🏠 {g.name}", color=COLORS['info'])
        if g.icon:
            embed.set_thumbnail(url=g.icon.url)
        embed.add_field(name="Propriétaire", value=g.owner.mention if g.owner else "Inconnu", inline=True)
        embed.add_field(name="ID", value=str(g.id), inline=True)
        embed.add_field(name="Créé le", value=f"<t:{int(g.created_at.timestamp())}:D>", inline=True)
        embed.add_field(name="Membres", value=str(g.member_count), inline=True)
        embed.add_field(name="Salons", value=str(len(g.channels)), inline=True)
        embed.add_field(name="Rôles", value=str(len(g.roles)), inline=True)
        embed.add_field(name="Boosts", value=str(g.premium_subscription_count), inline=True)
        embed.add_field(name="Niveau de boost", value=str(g.premium_tier), inline=True)
        embed.add_field(name="Vérification", value=str(g.verification_level).capitalize(), inline=True)
        await interaction.response.send_message(embed=embed)

    # ------------------------------------------------------------------
    # /historique
    # ------------------------------------------------------------------

    @app_commands.command(name="historique", description="Historique des sanctions d'un membre")
    @app_commands.describe(member="Le membre concerné")
    async def historique(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Permission insuffisante !", ephemeral=True)

        sanctions = get_sanctions(interaction.guild.id, member.id)
        if not sanctions:
            embed = discord.Embed(title="✅ Aucune Sanction", description=f"**{member}** n'a aucune sanction.", color=COLORS['success'])
            embed.set_footer(text=f"ID : {member.id}")
            return await interaction.response.send_message(embed=embed)

        def fmt(i, s):
            case_id, action, mod_id, reason, duration, timestamp = s
            emoji = ACTION_EMOJIS.get(action, '🔹')
            mod = interaction.guild.get_member(mod_id)
            mod_str = mod.mention if mod else f"<@{mod_id}>"
            dur = f" ({duration})" if duration else ""
            return (
                f"{emoji} Case #{case_id} — {action.capitalize()}{dur}",
                f"**Raison :** {reason or 'Aucune'}\n**Modérateur :** {mod_str}\n**Date :** {timestamp}"
            )

        pages = build_pages(sanctions, f"📋 Historique de {member}", COLORS['warning'], per_page=5, entry_formatter=fmt)
        for p in pages:
            p.description = f"Total : **{len(sanctions)}** sanction(s)"
            p.set_thumbnail(url=member.display_avatar.url)

        if len(pages) == 1:
            return await interaction.response.send_message(embed=pages[0])

        view = PaginationView(pages, author_id=interaction.user.id)
        await interaction.response.send_message(embed=pages[0], view=view)
        view.message = await interaction.original_response()

    # ------------------------------------------------------------------
    # /case + /editcase
    # ------------------------------------------------------------------

    @app_commands.command(name="case", description="Consulter un case de modération")
    @app_commands.describe(numero="Numéro du case")
    async def case(self, interaction: discord.Interaction, numero: int):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Permission insuffisante !", ephemeral=True)

        row = get_case(interaction.guild.id, numero)
        if not row:
            return await interaction.response.send_message(f"❌ Case #{numero} introuvable.", ephemeral=True)

        case_id, user_id, mod_id, action, reason, duration, timestamp = row
        emoji = ACTION_EMOJIS.get(action, '🔹')
        mod = interaction.guild.get_member(mod_id)
        user = interaction.guild.get_member(user_id)

        embed = discord.Embed(
            title=f"{emoji} Case #{case_id} — {action.capitalize()}",
            color=COLORS['warning']
        )
        embed.add_field(name="Membre", value=user.mention if user else f"<@{user_id}>", inline=True)
        embed.add_field(name="Modérateur", value=mod.mention if mod else f"<@{mod_id}>", inline=True)
        if duration:
            embed.add_field(name="Durée", value=duration, inline=True)
        embed.add_field(name="Raison", value=reason or "Aucune", inline=False)
        embed.add_field(name="Date", value=timestamp, inline=False)
        embed.set_footer(text=f"Case #{case_id} • Utilisez /editcase {case_id} pour modifier la raison")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="editcase", description="Modifier la raison d'un case")
    @app_commands.describe(numero="Numéro du case", nouvelle_raison="Nouvelle raison")
    async def editcase(self, interaction: discord.Interaction, numero: int, nouvelle_raison: str):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Permission insuffisante !", ephemeral=True)

        if edit_case_reason(interaction.guild.id, numero, nouvelle_raison):
            embed = discord.Embed(title="✅ Case Modifié", description=f"La raison du case **#{numero}** a été mise à jour.", color=COLORS['success'])
            embed.add_field(name="Nouvelle raison", value=nouvelle_raison)
            embed.add_field(name="Modifié par", value=interaction.user.mention)
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message(f"❌ Case #{numero} introuvable.", ephemeral=True)

    # ------------------------------------------------------------------
    # /regles + /setregles
    # ------------------------------------------------------------------

    @app_commands.command(name="regles", description="Afficher les règles du serveur")
    async def regles(self, interaction: discord.Interaction):
        settings = get_guild_settings(interaction.guild.id)
        rules_text = settings[4] if settings else None
        if not rules_text:
            return await interaction.response.send_message("❌ Aucune règle définie. Un administrateur peut les configurer avec `/setregles`.", ephemeral=True)
        embed = discord.Embed(title=f"📜 Règles de {interaction.guild.name}", description=rules_text, color=COLORS['info'])
        embed.set_footer(text="Merci de respecter ces règles !")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="setregles", description="Définir les règles du serveur")
    @app_commands.describe(texte="Texte des règles (markdown supporté)")
    async def setregles(self, interaction: discord.Interaction, texte: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Administrateur requis !", ephemeral=True)
        update_guild_settings(interaction.guild.id, rules_text=texte)
        embed = discord.Embed(title="✅ Règles Mises à Jour", color=COLORS['success'])
        embed.add_field(name="Aperçu", value=texte[:500] + ("..." if len(texte) > 500 else ""))
        await interaction.response.send_message(embed=embed)

    # ------------------------------------------------------------------
    # /blacklist
    # ------------------------------------------------------------------

    blacklist_group = app_commands.Group(name="blacklist", description="Gérer la liste noire de mots")

    @blacklist_group.command(name="ajouter", description="Ajouter un mot à la liste noire")
    @app_commands.describe(mot="Le mot à interdire")
    async def blacklist_add(self, interaction: discord.Interaction, mot: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Administrateur requis !", ephemeral=True)
        add_blacklist_word(interaction.guild.id, mot, interaction.user.id)
        automod = self.bot.get_cog('AutoMod')
        if automod:
            automod.invalidate_cache(interaction.guild.id)
        await interaction.response.send_message(f"✅ Le mot **{mot}** a été ajouté à la liste noire.", ephemeral=True)

    @blacklist_group.command(name="retirer", description="Retirer un mot de la liste noire")
    @app_commands.describe(mot="Le mot à retirer")
    async def blacklist_remove(self, interaction: discord.Interaction, mot: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Administrateur requis !", ephemeral=True)
        if remove_blacklist_word(interaction.guild.id, mot):
            automod = self.bot.get_cog('AutoMod')
            if automod:
                automod.invalidate_cache(interaction.guild.id)
            await interaction.response.send_message(f"✅ Le mot **{mot}** a été retiré de la liste noire.", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ Le mot **{mot}** n'est pas dans la liste noire.", ephemeral=True)

    @blacklist_group.command(name="liste", description="Voir les mots de la liste noire")
    async def blacklist_list(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Permission insuffisante !", ephemeral=True)
        words = get_blacklist_words(interaction.guild.id)
        if not words:
            return await interaction.response.send_message("✅ La liste noire est vide.", ephemeral=True)
        embed = discord.Embed(title="🚫 Liste Noire", description="\n".join(f"• `{w}`" for w in words), color=COLORS['error'])
        embed.set_footer(text=f"{len(words)} mot(s) interdit(s)")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------
    # /automod
    # ------------------------------------------------------------------

    automod_group = app_commands.Group(name="automod", description="Configuration de l'auto-modération")

    @automod_group.command(name="config", description="Voir la configuration de l'auto-modération")
    async def automod_config(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ Permission insuffisante !", ephemeral=True)

        cfg = get_automod_config(interaction.guild.id)
        embed = discord.Embed(title="⚙️ Configuration Auto-Modération", color=COLORS['info'])
        embed.add_field(name="🔍 Détection spam", value=f"Seuil : **{cfg['spam_threshold']}** msgs / **{cfg['spam_interval']}**s", inline=True)
        embed.add_field(name="📢 Mentions max", value=f"**{cfg['max_mentions']}** mentions", inline=True)
        embed.add_field(name="🔠 Majuscules", value=f"{'✅ Actif' if cfg['caps_detection'] else '❌ Inactif'} — **{cfg['caps_percent']}**% min **{cfg['caps_min_length']}** lettres", inline=True)
        embed.add_field(name="📎 Flood de fichiers", value=f"**{cfg['file_flood_limit']}** fichiers / **{cfg['file_flood_interval']}**s", inline=True)
        embed.add_field(name="⚠️ Seuils de sanction", value=(
            f"Avertissement : **{cfg['pts_warn']}** pts\n"
            f"Mute ({format_duration(cfg['pts_mute_duration'])}) : **{cfg['pts_mute']}** pts\n"
            f"Expulsion : **{cfg['pts_kick']}** pts\n"
            f"Tempban ({format_duration(cfg['pts_ban_duration'])}) : **{cfg['pts_ban']}** pts"
        ), inline=False)
        embed.set_footer(text="Utilisez /automod set <paramètre> <valeur> pour modifier")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @automod_group.command(name="set", description="Modifier un paramètre de l'auto-modération")
    @app_commands.describe(
        parametre="Paramètre à modifier",
        valeur="Nouvelle valeur (nombre entier)"
    )
    @app_commands.choices(parametre=[
        app_commands.Choice(name="Seuil spam (messages)", value="spam_threshold"),
        app_commands.Choice(name="Intervalle spam (secondes)", value="spam_interval"),
        app_commands.Choice(name="Mentions max", value="max_mentions"),
        app_commands.Choice(name="Détection majuscules (0/1)", value="caps_detection"),
        app_commands.Choice(name="Seuil majuscules (%)", value="caps_percent"),
        app_commands.Choice(name="Limite fichiers flood", value="file_flood_limit"),
        app_commands.Choice(name="Points → avertissement", value="pts_warn"),
        app_commands.Choice(name="Points → mute", value="pts_mute"),
        app_commands.Choice(name="Durée mute auto (secondes)", value="pts_mute_duration"),
        app_commands.Choice(name="Points → expulsion", value="pts_kick"),
        app_commands.Choice(name="Points → tempban", value="pts_ban"),
        app_commands.Choice(name="Durée tempban auto (secondes)", value="pts_ban_duration"),
    ])
    async def automod_set(self, interaction: discord.Interaction, parametre: str, valeur: int):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Administrateur requis !", ephemeral=True)
        update_automod_config(interaction.guild.id, **{parametre: valeur})
        await interaction.response.send_message(f"✅ `{parametre}` mis à jour → **{valeur}**", ephemeral=True)

    @automod_group.command(name="resetpoints", description="Réinitialiser les points d'infraction d'un membre")
    @app_commands.describe(member="Le membre concerné")
    async def automod_reset(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Permission insuffisante !", ephemeral=True)
        reset_violation_points(interaction.guild.id, member.id)
        await interaction.response.send_message(f"✅ Points d'infraction de **{member}** réinitialisés.", ephemeral=True)

    # ------------------------------------------------------------------
    # /setwelcome
    # ------------------------------------------------------------------

    @app_commands.command(name="setwelcome", description="Configurer le message de bienvenue")
    @app_commands.describe(salon="Salon de bienvenue", message="Message ({mention}, {server}, {count})")
    async def setwelcome(self, interaction: discord.Interaction, salon: discord.TextChannel, message: str = None):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Administrateur requis !", ephemeral=True)
        update_guild_settings(interaction.guild.id, welcome_channel_id=salon.id, welcome_message=message)
        embed = discord.Embed(title="✅ Message de Bienvenue Configuré", color=COLORS['success'])
        embed.add_field(name="Salon", value=salon.mention)
        embed.add_field(name="Message", value=message or "*(Par défaut)* Bienvenue sur **{server}**, {mention} ! 🎉")
        embed.add_field(name="Variables", value="`{mention}` `{server}` `{count}`", inline=False)
        await interaction.response.send_message(embed=embed)

    # ------------------------------------------------------------------
    # /modhelp
    # ------------------------------------------------------------------

    @app_commands.command(name="modhelp", description="Afficher toutes les commandes de modération")
    async def modhelp(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🛡️ Commandes de Modération", color=COLORS['info'])
        embed.add_field(name="⚔️ Sanctions", value=(
            "`/kick` — Expulser\n`/ban` — Bannir\n`/tempban` — Bannissement temporaire\n"
            "`/unban` — Débannir\n`/mute [durée]` — Rendre muet\n`/unmute` — Retirer le mute"
        ), inline=False)
        embed.add_field(name="⚠️ Avertissements", value=(
            "`/warn` — Avertir\n`/warnings` — Voir les avertissements\n`/clearwarnings` — Effacer"
        ), inline=False)
        embed.add_field(name="📋 Cases", value=(
            "`/case <numéro>` — Consulter un case\n`/editcase <numéro> <raison>` — Modifier la raison"
        ), inline=False)
        embed.add_field(name="🔧 Messages", value=(
            "`/purge` — Supprimer des messages\n`/slowmode` — Mode lent"
        ), inline=False)
        embed.add_field(name="📊 Infos", value=(
            "`/userinfo` — Profil d'un membre\n`/serverinfo` — Infos du serveur\n"
            "`/historique` — Historique des sanctions\n`/regles` — Règles du serveur"
        ), inline=False)
        embed.add_field(name="⚙️ Config (Admin)", value=(
            "`/setlogchannel` — Salon de logs\n`/setregles` — Règles\n`/setwelcome` — Bienvenue\n"
            "`/blacklist ajouter/retirer/liste` — Liste noire\n"
            "`/automod config` — Voir la config auto-mod\n"
            "`/automod set` — Modifier un paramètre\n"
            "`/automod resetpoints` — Réinitialiser les points d'un membre"
        ), inline=False)
        embed.set_footer(text="Formats de durée acceptés : 30s • 10m • 2h • 1d")
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Moderation(bot))
