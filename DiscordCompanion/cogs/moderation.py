import discord
from discord.ext import commands, tasks
from discord import app_commands
from utils.permissions import ensure_mute_role
from utils.database import (
    add_warning, get_warnings, clear_warnings,
    add_mute, remove_mute, get_active_timed_mutes,
    add_tempban, deactivate_tempban, get_active_tempbans,
    add_sanction, get_sanctions,
    add_blacklist_word, remove_blacklist_word, get_blacklist_words,
    update_guild_settings, get_guild_settings,
    parse_duration, format_duration,
)
from config import COLORS, MAX_WARNINGS
from datetime import datetime, timedelta
import asyncio


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.check_expired_punishments.start()

    async def cog_unload(self):
        self.check_expired_punishments.cancel()

    # ------------------------------------------------------------------
    # Background task — punishments expirées
    # ------------------------------------------------------------------

    @tasks.loop(minutes=1)
    async def check_expired_punishments(self):
        now = datetime.utcnow()

        # Tempbans expirés
        for guild_id, user_id, unban_at_str in get_active_tempbans():
            try:
                unban_at = datetime.fromisoformat(unban_at_str)
                if now >= unban_at:
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

        # Mutes temporaires expirés
        mute_role_cache = {}
        for guild_id, user_id, unmute_at_str in get_active_timed_mutes():
            try:
                unmute_at = datetime.fromisoformat(unmute_at_str)
                if now >= unmute_at:
                    guild = self.bot.get_guild(guild_id)
                    if guild:
                        member = guild.get_member(user_id)
                        if member:
                            if guild_id not in mute_role_cache:
                                mute_role_cache[guild_id] = await ensure_mute_role(guild)
                            mute_role = mute_role_cache[guild_id]
                            if mute_role in member.roles:
                                await member.remove_roles(mute_role, reason="Mute temporaire expiré automatiquement")
                    remove_mute(guild_id, user_id)
            except Exception:
                pass

    @check_expired_punishments.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------
    # /kick
    # ------------------------------------------------------------------

    @app_commands.command(name="kick", description="Expulser un membre du serveur")
    @app_commands.describe(member="Le membre à expulser", raison="Raison de l'expulsion")
    async def kick(self, interaction: discord.Interaction, member: discord.Member, raison: str = "Aucune raison fournie"):
        if not interaction.user.guild_permissions.kick_members:
            await interaction.response.send_message("❌ Vous n'avez pas la permission d'expulser des membres !", ephemeral=True)
            return
        if not interaction.guild.me.guild_permissions.kick_members:
            await interaction.response.send_message("❌ Je n'ai pas la permission d'expulser des membres !", ephemeral=True)
            return
        if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
            await interaction.response.send_message("❌ Vous ne pouvez pas expulser quelqu'un avec un rôle supérieur ou égal !", ephemeral=True)
            return
        if member.top_role >= interaction.guild.me.top_role:
            await interaction.response.send_message("❌ Je ne peux pas expulser quelqu'un avec un rôle supérieur ou égal au mien !", ephemeral=True)
            return
        try:
            try:
                dm = discord.Embed(title="Vous avez été expulsé", description=f"Vous avez été expulsé de **{interaction.guild.name}**", color=COLORS['warning'])
                dm.add_field(name="Raison", value=raison, inline=False)
                dm.add_field(name="Modérateur", value=interaction.user.mention, inline=False)
                await member.send(embed=dm)
            except discord.Forbidden:
                pass

            await member.kick(reason=f"Expulsé par {interaction.user} | {raison}")
            add_sanction(interaction.guild.id, member.id, interaction.user.id, 'kick', raison)

            embed = discord.Embed(title="✅ Membre Expulsé", description=f"**{member}** a été expulsé", color=COLORS['success'])
            embed.add_field(name="Modérateur", value=interaction.user.mention, inline=True)
            embed.add_field(name="Raison", value=raison, inline=True)
            embed.set_footer(text=f"ID Utilisateur : {member.id}")
            await interaction.response.send_message(embed=embed)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Je n'ai pas la permission d'expulser ce membre !", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Une erreur s'est produite : {e}", ephemeral=True)

    # ------------------------------------------------------------------
    # /ban
    # ------------------------------------------------------------------

    @app_commands.command(name="ban", description="Bannir un membre du serveur")
    @app_commands.describe(member="Le membre à bannir", raison="Raison du bannissement", supprimer_jours="Jours de messages à supprimer (0-7)")
    async def ban(self, interaction: discord.Interaction, member: discord.Member, raison: str = "Aucune raison fournie", supprimer_jours: int = 0):
        if not interaction.user.guild_permissions.ban_members:
            await interaction.response.send_message("❌ Vous n'avez pas la permission de bannir des membres !", ephemeral=True)
            return
        if not interaction.guild.me.guild_permissions.ban_members:
            await interaction.response.send_message("❌ Je n'ai pas la permission de bannir des membres !", ephemeral=True)
            return
        if supprimer_jours < 0 or supprimer_jours > 7:
            await interaction.response.send_message("❌ Les jours de suppression doivent être entre 0 et 7 !", ephemeral=True)
            return
        if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
            await interaction.response.send_message("❌ Vous ne pouvez pas bannir quelqu'un avec un rôle supérieur ou égal !", ephemeral=True)
            return
        if member.top_role >= interaction.guild.me.top_role:
            await interaction.response.send_message("❌ Je ne peux pas bannir quelqu'un avec un rôle supérieur ou égal au mien !", ephemeral=True)
            return
        try:
            try:
                dm = discord.Embed(title="Vous avez été banni", description=f"Vous avez été banni de **{interaction.guild.name}**", color=COLORS['error'])
                dm.add_field(name="Raison", value=raison, inline=False)
                dm.add_field(name="Modérateur", value=interaction.user.mention, inline=False)
                await member.send(embed=dm)
            except discord.Forbidden:
                pass

            await member.ban(reason=f"Banni par {interaction.user} | {raison}", delete_message_days=supprimer_jours)
            add_sanction(interaction.guild.id, member.id, interaction.user.id, 'ban', raison)

            embed = discord.Embed(title="🔨 Membre Banni", description=f"**{member}** a été banni", color=COLORS['error'])
            embed.add_field(name="Modérateur", value=interaction.user.mention, inline=True)
            embed.add_field(name="Raison", value=raison, inline=True)
            embed.add_field(name="Messages Supprimés", value=f"{supprimer_jours} jours", inline=True)
            embed.set_footer(text=f"ID Utilisateur : {member.id}")
            await interaction.response.send_message(embed=embed)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Je n'ai pas la permission de bannir ce membre !", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Une erreur s'est produite : {e}", ephemeral=True)

    # ------------------------------------------------------------------
    # /tempban
    # ------------------------------------------------------------------

    @app_commands.command(name="tempban", description="Bannir temporairement un membre du serveur")
    @app_commands.describe(member="Le membre à bannir", duree="Durée (ex: 10m, 2h, 1d)", raison="Raison du bannissement")
    async def tempban(self, interaction: discord.Interaction, member: discord.Member, duree: str, raison: str = "Aucune raison fournie"):
        if not interaction.user.guild_permissions.ban_members:
            await interaction.response.send_message("❌ Vous n'avez pas la permission de bannir des membres !", ephemeral=True)
            return
        if not interaction.guild.me.guild_permissions.ban_members:
            await interaction.response.send_message("❌ Je n'ai pas la permission de bannir des membres !", ephemeral=True)
            return
        if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
            await interaction.response.send_message("❌ Vous ne pouvez pas bannir quelqu'un avec un rôle supérieur ou égal !", ephemeral=True)
            return

        seconds = parse_duration(duree)
        if seconds is None:
            await interaction.response.send_message("❌ Format de durée invalide ! Exemples valides : `10m`, `2h`, `1d`, `30s`", ephemeral=True)
            return

        unban_at = datetime.utcnow() + timedelta(seconds=seconds)
        duree_lisible = format_duration(seconds)

        try:
            try:
                dm = discord.Embed(title="Vous avez été banni temporairement", description=f"Vous avez été banni de **{interaction.guild.name}**", color=COLORS['error'])
                dm.add_field(name="Durée", value=duree_lisible, inline=False)
                dm.add_field(name="Raison", value=raison, inline=False)
                dm.add_field(name="Modérateur", value=interaction.user.mention, inline=False)
                await member.send(embed=dm)
            except discord.Forbidden:
                pass

            await member.ban(reason=f"Tempban ({duree_lisible}) par {interaction.user} | {raison}")
            add_tempban(interaction.guild.id, member.id, interaction.user.id, raison, unban_at)
            add_sanction(interaction.guild.id, member.id, interaction.user.id, 'tempban', raison, duree)

            embed = discord.Embed(title="⏱️ Membre Banni Temporairement", description=f"**{member}** a été banni temporairement", color=COLORS['error'])
            embed.add_field(name="Modérateur", value=interaction.user.mention, inline=True)
            embed.add_field(name="Durée", value=duree_lisible, inline=True)
            embed.add_field(name="Raison", value=raison, inline=True)
            embed.add_field(name="Débannissement le", value=f"<t:{int(unban_at.timestamp())}:F>", inline=False)
            embed.set_footer(text=f"ID Utilisateur : {member.id}")
            await interaction.response.send_message(embed=embed)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Je n'ai pas la permission de bannir ce membre !", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Une erreur s'est produite : {e}", ephemeral=True)

    # ------------------------------------------------------------------
    # /unban
    # ------------------------------------------------------------------

    @app_commands.command(name="unban", description="Débannir un utilisateur du serveur")
    @app_commands.describe(user_id="L'ID de l'utilisateur à débannir", raison="Raison du débannissement")
    async def unban(self, interaction: discord.Interaction, user_id: str, raison: str = "Aucune raison fournie"):
        if not interaction.user.guild_permissions.ban_members:
            await interaction.response.send_message("❌ Vous n'avez pas la permission de débannir des membres !", ephemeral=True)
            return
        if not interaction.guild.me.guild_permissions.ban_members:
            await interaction.response.send_message("❌ Je n'ai pas la permission de débannir des membres !", ephemeral=True)
            return
        try:
            uid = int(user_id)
        except ValueError:
            await interaction.response.send_message("❌ ID utilisateur invalide !", ephemeral=True)
            return
        try:
            bans = [e async for e in interaction.guild.bans(limit=2000)]
            banned_user = next((e.user for e in bans if e.user.id == uid), None)
            if not banned_user:
                await interaction.response.send_message("❌ Cet utilisateur n'est pas banni !", ephemeral=True)
                return

            await interaction.guild.unban(banned_user, reason=f"Débanni par {interaction.user} | {raison}")
            deactivate_tempban(interaction.guild.id, uid)
            add_sanction(interaction.guild.id, uid, interaction.user.id, 'unban', raison)

            embed = discord.Embed(title="✅ Membre Débanni", description=f"**{banned_user}** a été débanni", color=COLORS['success'])
            embed.add_field(name="Modérateur", value=interaction.user.mention, inline=True)
            embed.add_field(name="Raison", value=raison, inline=True)
            embed.set_footer(text=f"ID Utilisateur : {banned_user.id}")
            await interaction.response.send_message(embed=embed)
        except discord.NotFound:
            await interaction.response.send_message("❌ Utilisateur introuvable ou non banni !", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Je n'ai pas la permission de débannir des membres !", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Une erreur s'est produite : {e}", ephemeral=True)

    # ------------------------------------------------------------------
    # /mute
    # ------------------------------------------------------------------

    @app_commands.command(name="mute", description="Rendre muet un membre")
    @app_commands.describe(member="Le membre à rendre muet", duree="Durée optionnelle (ex: 10m, 2h, 1d)", raison="Raison du mute")
    async def mute(self, interaction: discord.Interaction, member: discord.Member, duree: str = None, raison: str = "Aucune raison fournie"):
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("❌ Vous n'avez pas la permission de rendre muet des membres !", ephemeral=True)
            return
        if not interaction.guild.me.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ Je n'ai pas la permission de gérer les rôles !", ephemeral=True)
            return
        if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
            await interaction.response.send_message("❌ Vous ne pouvez pas rendre muet quelqu'un avec un rôle supérieur ou égal !", ephemeral=True)
            return

        seconds = None
        unmute_at = None
        duree_lisible = "Permanent"

        if duree:
            seconds = parse_duration(duree)
            if seconds is None:
                await interaction.response.send_message("❌ Format de durée invalide ! Exemples valides : `10m`, `2h`, `1d`, `30s`", ephemeral=True)
                return
            unmute_at = datetime.utcnow() + timedelta(seconds=seconds)
            duree_lisible = format_duration(seconds)

        try:
            mute_role = await ensure_mute_role(interaction.guild)
            if mute_role in member.roles:
                await interaction.response.send_message("❌ Ce membre est déjà muet !", ephemeral=True)
                return

            await member.add_roles(mute_role, reason=f"Rendu muet par {interaction.user} | {raison}")
            add_mute(interaction.guild.id, member.id, interaction.user.id, raison, unmute_at)
            add_sanction(interaction.guild.id, member.id, interaction.user.id, 'mute', raison, duree)

            embed = discord.Embed(title="🔇 Membre Rendu Muet", description=f"**{member}** a été rendu muet", color=COLORS['warning'])
            embed.add_field(name="Modérateur", value=interaction.user.mention, inline=True)
            embed.add_field(name="Durée", value=duree_lisible, inline=True)
            embed.add_field(name="Raison", value=raison, inline=True)
            if unmute_at:
                embed.add_field(name="Unmute le", value=f"<t:{int(unmute_at.timestamp())}:F>", inline=False)
            embed.set_footer(text=f"ID Utilisateur : {member.id}")
            await interaction.response.send_message(embed=embed)

            # Schedule auto-unmute via asyncio task if duration provided
            if seconds:
                async def _auto_unmute():
                    await asyncio.sleep(seconds)
                    try:
                        if mute_role in member.roles:
                            await member.remove_roles(mute_role, reason="Mute temporaire expiré")
                        remove_mute(interaction.guild.id, member.id)
                    except (discord.Forbidden, discord.NotFound):
                        pass
                self.bot.loop.create_task(_auto_unmute())

        except discord.Forbidden:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Je n'ai pas la permission de rendre muet ce membre !", ephemeral=True)
        except Exception as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ Une erreur s'est produite : {e}", ephemeral=True)

    # ------------------------------------------------------------------
    # /unmute
    # ------------------------------------------------------------------

    @app_commands.command(name="unmute", description="Retirer le mute d'un membre")
    @app_commands.describe(member="Le membre à unmute", raison="Raison de l'unmute")
    async def unmute(self, interaction: discord.Interaction, member: discord.Member, raison: str = "Aucune raison fournie"):
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("❌ Vous n'avez pas la permission de retirer le mute des membres !", ephemeral=True)
            return
        if not interaction.guild.me.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ Je n'ai pas la permission de gérer les rôles !", ephemeral=True)
            return
        try:
            mute_role = await ensure_mute_role(interaction.guild)
            if mute_role not in member.roles:
                await interaction.response.send_message("❌ Ce membre n'est pas muet !", ephemeral=True)
                return
            await member.remove_roles(mute_role, reason=f"Unmute par {interaction.user} | {raison}")
            remove_mute(interaction.guild.id, member.id)
            add_sanction(interaction.guild.id, member.id, interaction.user.id, 'unmute', raison)

            embed = discord.Embed(title="🔊 Membre Unmute", description=f"**{member}** n'est plus muet", color=COLORS['success'])
            embed.add_field(name="Modérateur", value=interaction.user.mention, inline=True)
            embed.add_field(name="Raison", value=raison, inline=True)
            embed.set_footer(text=f"ID Utilisateur : {member.id}")
            await interaction.response.send_message(embed=embed)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Je n'ai pas la permission de retirer le mute de ce membre !", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Une erreur s'est produite : {e}", ephemeral=True)

    # ------------------------------------------------------------------
    # /warn
    # ------------------------------------------------------------------

    @app_commands.command(name="warn", description="Avertir un membre")
    @app_commands.describe(member="Le membre à avertir", raison="Raison de l'avertissement")
    async def warn(self, interaction: discord.Interaction, member: discord.Member, raison: str = "Aucune raison fournie"):
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("❌ Vous n'avez pas la permission d'avertir des membres !", ephemeral=True)
            return

        add_warning(interaction.guild.id, member.id, interaction.user.id, raison)
        add_sanction(interaction.guild.id, member.id, interaction.user.id, 'warn', raison)
        warnings = get_warnings(interaction.guild.id, member.id)
        warning_count = len(warnings)

        embed = discord.Embed(title="⚠️ Membre Averti", description=f"**{member}** a été averti", color=COLORS['warning'])
        embed.add_field(name="Modérateur", value=interaction.user.mention, inline=True)
        embed.add_field(name="Raison", value=raison, inline=True)
        embed.add_field(name="Total Avertissements", value=f"{warning_count}/{MAX_WARNINGS}", inline=True)
        embed.set_footer(text=f"ID Utilisateur : {member.id}")

        if warning_count >= MAX_WARNINGS:
            try:
                mute_role = await ensure_mute_role(interaction.guild)
                if mute_role not in member.roles:
                    await member.add_roles(mute_role, reason="Auto-mute : Nombre maximum d'avertissements atteint")
                    embed.add_field(name="Action Automatique", value="🔇 Auto-mute pour avoir atteint le maximum d'avertissements", inline=False)
            except discord.Forbidden:
                pass

        await interaction.response.send_message(embed=embed)

        try:
            dm = discord.Embed(title="Vous avez été averti", description=f"Vous avez reçu un avertissement dans **{interaction.guild.name}**", color=COLORS['warning'])
            dm.add_field(name="Raison", value=raison, inline=False)
            dm.add_field(name="Avertissements", value=f"{warning_count}/{MAX_WARNINGS}", inline=False)
            await member.send(embed=dm)
        except discord.Forbidden:
            pass

    # ------------------------------------------------------------------
    # /warnings
    # ------------------------------------------------------------------

    @app_commands.command(name="warnings", description="Voir les avertissements d'un membre")
    @app_commands.describe(member="Le membre dont voir les avertissements")
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        warnings = get_warnings(interaction.guild.id, member.id)

        if not warnings:
            embed = discord.Embed(title="✅ Aucun Avertissement", description=f"**{member}** n'a aucun avertissement", color=COLORS['success'])
        else:
            embed = discord.Embed(title=f"⚠️ Avertissements de {member}", description=f"Total : {len(warnings)} avertissement(s)", color=COLORS['warning'])
            for i, w in enumerate(warnings[:10], 1):
                moderator = interaction.guild.get_member(w[1])
                mod_name = moderator.mention if moderator else f"<@{w[1]}>"
                embed.add_field(name=f"Avertissement #{i}", value=f"**Raison :** {w[2]}\n**Modérateur :** {mod_name}\n**Date :** {w[3]}", inline=False)

        embed.set_footer(text=f"ID Utilisateur : {member.id}")
        await interaction.response.send_message(embed=embed)

    # ------------------------------------------------------------------
    # /clearwarnings
    # ------------------------------------------------------------------

    @app_commands.command(name="clearwarnings", description="Effacer tous les avertissements d'un membre")
    @app_commands.describe(member="Le membre dont effacer les avertissements")
    async def clearwarnings(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("❌ Vous n'avez pas la permission d'effacer les avertissements !", ephemeral=True)
            return

        warnings = get_warnings(interaction.guild.id, member.id)
        if not warnings:
            await interaction.response.send_message(f"❌ **{member}** n'a aucun avertissement à effacer !", ephemeral=True)
            return

        clear_warnings(interaction.guild.id, member.id)

        embed = discord.Embed(title="✅ Avertissements Effacés", description=f"Tous les avertissements de **{member}** ont été effacés", color=COLORS['success'])
        embed.add_field(name="Modérateur", value=interaction.user.mention, inline=True)
        embed.add_field(name="Avertissements Effacés", value=str(len(warnings)), inline=True)
        embed.set_footer(text=f"ID Utilisateur : {member.id}")
        await interaction.response.send_message(embed=embed)

    # ------------------------------------------------------------------
    # /purge
    # ------------------------------------------------------------------

    @app_commands.command(name="purge", description="Supprimer plusieurs messages d'un coup")
    @app_commands.describe(nombre="Nombre de messages à supprimer (1-100)", membre="Ne supprimer que les messages de ce membre")
    async def purge(self, interaction: discord.Interaction, nombre: int, membre: discord.Member = None):
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("❌ Vous n'avez pas la permission de gérer les messages !", ephemeral=True)
            return
        if not interaction.guild.me.guild_permissions.manage_messages:
            await interaction.response.send_message("❌ Je n'ai pas la permission de gérer les messages !", ephemeral=True)
            return
        if nombre < 1 or nombre > 100:
            await interaction.response.send_message("❌ Le nombre doit être entre 1 et 100 !", ephemeral=True)
            return

        await interaction.response.defer()
        try:
            if membre:
                deleted = await interaction.channel.purge(limit=nombre, check=lambda m: m.author == membre)
            else:
                deleted = await interaction.channel.purge(limit=nombre)

            embed = discord.Embed(title="🗑️ Messages Supprimés", description=f"**{len(deleted)}** message(s) supprimé(s)", color=COLORS['success'])
            embed.add_field(name="Modérateur", value=interaction.user.mention, inline=True)
            if membre:
                embed.add_field(name="Membre Ciblé", value=membre.mention, inline=True)
            embed.add_field(name="Salon", value=interaction.channel.mention, inline=True)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ Je n'ai pas la permission de supprimer des messages !", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Une erreur s'est produite : {e}", ephemeral=True)

    # ------------------------------------------------------------------
    # /slowmode
    # ------------------------------------------------------------------

    @app_commands.command(name="slowmode", description="Activer ou désactiver le mode lent sur un salon")
    @app_commands.describe(secondes="Délai en secondes (0 pour désactiver, max 21600)", salon="Salon concerné (défaut : salon actuel)")
    async def slowmode(self, interaction: discord.Interaction, secondes: int = 0, salon: discord.TextChannel = None):
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("❌ Vous n'avez pas la permission de gérer les salons !", ephemeral=True)
            return
        if secondes < 0 or secondes > 21600:
            await interaction.response.send_message("❌ La valeur doit être entre 0 et 21600 secondes (6 heures) !", ephemeral=True)
            return

        target = salon or interaction.channel
        await target.edit(slowmode_delay=secondes)

        if secondes == 0:
            embed = discord.Embed(title="✅ Mode Lent Désactivé", description=f"Le mode lent a été désactivé dans {target.mention}", color=COLORS['success'])
        else:
            embed = discord.Embed(title="🐢 Mode Lent Activé", description=f"Le mode lent a été activé dans {target.mention}", color=COLORS['info'])
            embed.add_field(name="Délai", value=format_duration(secondes), inline=True)

        embed.add_field(name="Modérateur", value=interaction.user.mention, inline=True)
        await interaction.response.send_message(embed=embed)

    # ------------------------------------------------------------------
    # /userinfo
    # ------------------------------------------------------------------

    @app_commands.command(name="userinfo", description="Afficher les informations complètes d'un membre")
    @app_commands.describe(member="Le membre à inspecter (défaut : vous-même)")
    async def userinfo(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        sanctions = get_sanctions(interaction.guild.id, member.id)

        roles = [r.mention for r in reversed(member.roles) if r != interaction.guild.default_role]
        roles_str = " ".join(roles[:10]) if roles else "Aucun rôle"
        if len(member.roles) - 1 > 10:
            roles_str += f" *+{len(member.roles) - 11} autres*"

        embed = discord.Embed(title=f"👤 Informations sur {member}", color=member.color if member.color.value else COLORS['info'])
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Nom d'utilisateur", value=str(member), inline=True)
        embed.add_field(name="Pseudonyme", value=member.display_name, inline=True)
        embed.add_field(name="ID", value=str(member.id), inline=True)
        embed.add_field(name="Compte créé le", value=f"<t:{int(member.created_at.timestamp())}:D>", inline=True)
        embed.add_field(name="Rejoint le serveur", value=f"<t:{int(member.joined_at.timestamp())}:D>" if member.joined_at else "Inconnu", inline=True)
        embed.add_field(name="Bot", value="Oui" if member.bot else "Non", inline=True)
        embed.add_field(name=f"Rôles ({len(member.roles) - 1})", value=roles_str, inline=False)
        embed.add_field(name="Sanctions enregistrées", value=str(len(sanctions)), inline=True)
        if member.premium_since:
            embed.add_field(name="Booste depuis", value=f"<t:{int(member.premium_since.timestamp())}:D>", inline=True)
        embed.set_footer(text=f"ID : {member.id}")
        await interaction.response.send_message(embed=embed)

    # ------------------------------------------------------------------
    # /serverinfo
    # ------------------------------------------------------------------

    @app_commands.command(name="serverinfo", description="Afficher les informations du serveur")
    async def serverinfo(self, interaction: discord.Interaction):
        guild = interaction.guild
        embed = discord.Embed(title=f"🏠 Informations sur {guild.name}", color=COLORS['info'])
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(name="Propriétaire", value=guild.owner.mention if guild.owner else "Inconnu", inline=True)
        embed.add_field(name="ID", value=str(guild.id), inline=True)
        embed.add_field(name="Créé le", value=f"<t:{int(guild.created_at.timestamp())}:D>", inline=True)
        embed.add_field(name="Membres", value=str(guild.member_count), inline=True)
        embed.add_field(name="Salons", value=str(len(guild.channels)), inline=True)
        embed.add_field(name="Rôles", value=str(len(guild.roles)), inline=True)
        embed.add_field(name="Boosts", value=str(guild.premium_subscription_count), inline=True)
        embed.add_field(name="Niveau de boost", value=str(guild.premium_tier), inline=True)
        embed.add_field(name="Vérification", value=str(guild.verification_level).capitalize(), inline=True)
        await interaction.response.send_message(embed=embed)

    # ------------------------------------------------------------------
    # /historique
    # ------------------------------------------------------------------

    @app_commands.command(name="historique", description="Voir l'historique des sanctions d'un membre")
    @app_commands.describe(member="Le membre dont voir l'historique")
    async def historique(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("❌ Vous n'avez pas la permission de consulter l'historique des sanctions !", ephemeral=True)
            return

        sanctions = get_sanctions(interaction.guild.id, member.id)

        if not sanctions:
            embed = discord.Embed(title="✅ Aucune Sanction", description=f"**{member}** n'a aucune sanction enregistrée", color=COLORS['success'])
        else:
            action_emojis = {
                'kick': '👢', 'ban': '🔨', 'tempban': '⏱️',
                'mute': '🔇', 'unmute': '🔊', 'warn': '⚠️', 'unban': '✅'
            }
            embed = discord.Embed(title=f"📋 Historique de {member}", description=f"Total : {len(sanctions)} sanction(s)", color=COLORS['warning'])
            for i, (action, mod_id, reason, duration, timestamp) in enumerate(sanctions[:15], 1):
                emoji = action_emojis.get(action, '🔹')
                mod = interaction.guild.get_member(mod_id)
                mod_name = mod.mention if mod else f"<@{mod_id}>"
                dur_str = f" ({duration})" if duration else ""
                embed.add_field(
                    name=f"{emoji} {action.capitalize()}{dur_str} — #{i}",
                    value=f"**Raison :** {reason or 'Aucune'}\n**Modérateur :** {mod_name}\n**Date :** {timestamp}",
                    inline=False
                )

        embed.set_footer(text=f"ID Utilisateur : {member.id}")
        await interaction.response.send_message(embed=embed)

    # ------------------------------------------------------------------
    # /regles + /setregles
    # ------------------------------------------------------------------

    @app_commands.command(name="regles", description="Afficher les règles du serveur")
    async def regles(self, interaction: discord.Interaction):
        settings = get_guild_settings(interaction.guild.id)
        rules_text = settings[4] if settings else None

        if not rules_text:
            await interaction.response.send_message("❌ Aucune règle définie. Un administrateur peut les configurer avec `/setregles`.", ephemeral=True)
            return

        embed = discord.Embed(title=f"📜 Règles de {interaction.guild.name}", description=rules_text, color=COLORS['info'])
        embed.set_footer(text="Merci de respecter ces règles !")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="setregles", description="Définir les règles du serveur")
    @app_commands.describe(texte="Le texte des règles (supporte le markdown)")
    async def setregles(self, interaction: discord.Interaction, texte: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Vous devez être administrateur pour définir les règles !", ephemeral=True)
            return

        update_guild_settings(interaction.guild.id, rules_text=texte)

        embed = discord.Embed(title="✅ Règles Mises à Jour", description="Les règles du serveur ont été mises à jour.", color=COLORS['success'])
        embed.add_field(name="Aperçu", value=texte[:500] + ("..." if len(texte) > 500 else ""), inline=False)
        await interaction.response.send_message(embed=embed)

    # ------------------------------------------------------------------
    # /blacklist
    # ------------------------------------------------------------------

    blacklist_group = app_commands.Group(name="blacklist", description="Gérer la liste noire de mots")

    @blacklist_group.command(name="ajouter", description="Ajouter un mot à la liste noire")
    @app_commands.describe(mot="Le mot à interdire")
    async def blacklist_add(self, interaction: discord.Interaction, mot: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Vous devez être administrateur pour gérer la liste noire !", ephemeral=True)
            return
        add_blacklist_word(interaction.guild.id, mot, interaction.user.id)
        await interaction.response.send_message(f"✅ Le mot **{mot}** a été ajouté à la liste noire.", ephemeral=True)

    @blacklist_group.command(name="retirer", description="Retirer un mot de la liste noire")
    @app_commands.describe(mot="Le mot à retirer")
    async def blacklist_remove(self, interaction: discord.Interaction, mot: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Vous devez être administrateur pour gérer la liste noire !", ephemeral=True)
            return
        if remove_blacklist_word(interaction.guild.id, mot):
            await interaction.response.send_message(f"✅ Le mot **{mot}** a été retiré de la liste noire.", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ Le mot **{mot}** n'est pas dans la liste noire.", ephemeral=True)

    @blacklist_group.command(name="liste", description="Voir les mots de la liste noire")
    async def blacklist_list(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("❌ Vous n'avez pas la permission de consulter la liste noire !", ephemeral=True)
            return
        words = get_blacklist_words(interaction.guild.id)
        if not words:
            await interaction.response.send_message("✅ La liste noire est vide.", ephemeral=True)
            return
        embed = discord.Embed(title="🚫 Liste Noire de Mots", description="\n".join(f"• {w}" for w in words), color=COLORS['error'])
        embed.set_footer(text=f"{len(words)} mot(s) interdit(s)")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------
    # /setwelcome
    # ------------------------------------------------------------------

    @app_commands.command(name="setwelcome", description="Configurer le message de bienvenue")
    @app_commands.describe(salon="Le salon de bienvenue", message="Message personnalisé (utilisez {mention} et {server})")
    async def setwelcome(self, interaction: discord.Interaction, salon: discord.TextChannel, message: str = None):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Vous devez être administrateur pour configurer le message de bienvenue !", ephemeral=True)
            return

        update_guild_settings(interaction.guild.id, welcome_channel_id=salon.id, welcome_message=message)

        embed = discord.Embed(title="✅ Message de Bienvenue Configuré", color=COLORS['success'])
        embed.add_field(name="Salon", value=salon.mention, inline=True)
        default_msg = "Bienvenue sur **{server}**, {mention} ! 🎉"
        embed.add_field(name="Message", value=message or f"*(Par défaut)* {default_msg}", inline=False)
        embed.add_field(name="Variables disponibles", value="`{mention}` → mention du membre\n`{server}` → nom du serveur\n`{count}` → nombre de membres", inline=False)
        await interaction.response.send_message(embed=embed)

    # ------------------------------------------------------------------
    # /modhelp
    # ------------------------------------------------------------------

    @app_commands.command(name="modhelp", description="Afficher toutes les commandes de modération")
    async def modhelp(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🛡️ Commandes de Modération", color=COLORS['info'])

        embed.add_field(name="⚔️ Modération de Base", value=(
            "`/kick` — Expulser un membre\n"
            "`/ban` — Bannir un membre\n"
            "`/tempban` — Bannissement temporaire (ex: `1h`, `2d`)\n"
            "`/unban` — Débannir via ID\n"
            "`/mute` — Rendre muet (optionnel : durée)\n"
            "`/unmute` — Retirer le mute"
        ), inline=False)

        embed.add_field(name="⚠️ Système d'Avertissements", value=(
            "`/warn` — Avertir un membre\n"
            "`/warnings` — Voir les avertissements\n"
            "`/clearwarnings` — Effacer les avertissements"
        ), inline=False)

        embed.add_field(name="🔧 Gestion des Messages", value=(
            "`/purge` — Supprimer jusqu'à 100 messages\n"
            "`/slowmode` — Mode lent sur un salon"
        ), inline=False)

        embed.add_field(name="📊 Informations", value=(
            "`/userinfo` — Infos complètes sur un membre\n"
            "`/serverinfo` — Infos sur le serveur\n"
            "`/historique` — Historique des sanctions\n"
            "`/regles` — Afficher les règles"
        ), inline=False)

        embed.add_field(name="⚙️ Configuration (Admin)", value=(
            "`/setlogchannel` — Définir le salon de logs\n"
            "`/setregles` — Définir les règles\n"
            "`/setwelcome` — Message de bienvenue\n"
            "`/blacklist ajouter/retirer/liste` — Gérer la liste noire"
        ), inline=False)

        embed.add_field(name="ℹ️ Notes", value=(
            "• La plupart des commandes requièrent les permissions appropriées\n"
            "• Le bot respecte la hiérarchie des rôles\n"
            "• L'auto-modération fonctionne en arrière-plan\n"
            "• Formats de durée : `30s`, `10m`, `2h`, `1d`"
        ), inline=False)

        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Moderation(bot))
