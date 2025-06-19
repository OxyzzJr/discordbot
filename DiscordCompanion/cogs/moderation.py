import discord
from discord.ext import commands
from discord import app_commands
from utils.permissions import has_mod_permissions, has_ban_permissions, check_hierarchy, ensure_mute_role
from utils.database import add_warning, get_warnings, clear_warnings, add_mute, remove_mute
from config import COLORS, MAX_WARNINGS
from datetime import datetime, timedelta

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="kick", description="Expulser un membre du serveur")
    @app_commands.describe(member="Le membre à expulser", reason="Raison de l'expulsion")
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Aucune raison fournie"):
        """Kick a member from the server"""
        if not interaction.user.guild_permissions.kick_members:
            await interaction.response.send_message("❌ Vous n'avez pas la permission d'expulser des membres !", ephemeral=True)
            return
        
        if not interaction.guild.me.guild_permissions.kick_members:
            await interaction.response.send_message("❌ Je n'ai pas la permission d'expulser des membres !", ephemeral=True)
            return
        
        # Check hierarchy
        if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
            await interaction.response.send_message("❌ Vous ne pouvez pas expulser quelqu'un avec un rôle supérieur ou égal !", ephemeral=True)
            return
        
        if member.top_role >= interaction.guild.me.top_role:
            await interaction.response.send_message("❌ Je ne peux pas expulser quelqu'un avec un rôle supérieur ou égal au mien !", ephemeral=True)
            return
        
        try:
            # Send DM to user before kicking
            try:
                dm_embed = discord.Embed(
                    title="Vous avez été expulsé",
                    description=f"Vous avez été expulsé de **{interaction.guild.name}**",
                    color=COLORS['warning']
                )
                dm_embed.add_field(name="Raison", value=reason, inline=False)
                dm_embed.add_field(name="Modérateur", value=interaction.user.mention, inline=False)
                await member.send(embed=dm_embed)
            except discord.Forbidden:
                pass  # User has DMs disabled
            
            await member.kick(reason=f"Expulsé par {interaction.user} | {reason}")
            
            embed = discord.Embed(
                title="✅ Membre Expulsé",
                description=f"**{member}** a été expulsé",
                color=COLORS['success']
            )
            embed.add_field(name="Modérateur", value=interaction.user.mention, inline=True)
            embed.add_field(name="Raison", value=reason, inline=True)
            embed.set_footer(text=f"ID Utilisateur: {member.id}")
            
            await interaction.response.send_message(embed=embed)
            
        except discord.Forbidden:
            await interaction.response.send_message("❌ Je n'ai pas la permission d'expulser ce membre !", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Une erreur s'est produite: {str(e)}", ephemeral=True)

    @app_commands.command(name="ban", description="Bannir un membre du serveur")
    @app_commands.describe(member="Le membre à bannir", reason="Raison du bannissement", delete_days="Jours de messages à supprimer (0-7)")
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Aucune raison fournie", delete_days: int = 0):
        """Ban a member from the server"""
        if not interaction.user.guild_permissions.ban_members:
            await interaction.response.send_message("❌ Vous n'avez pas la permission de bannir des membres !", ephemeral=True)
            return
        
        if not interaction.guild.me.guild_permissions.ban_members:
            await interaction.response.send_message("❌ Je n'ai pas la permission de bannir des membres !", ephemeral=True)
            return
        
        if delete_days < 0 or delete_days > 7:
            await interaction.response.send_message("❌ Les jours de suppression doivent être entre 0 et 7 !", ephemeral=True)
            return
        
        # Check hierarchy
        if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
            await interaction.response.send_message("❌ Vous ne pouvez pas bannir quelqu'un avec un rôle supérieur ou égal !", ephemeral=True)
            return
        
        if member.top_role >= interaction.guild.me.top_role:
            await interaction.response.send_message("❌ Je ne peux pas bannir quelqu'un avec un rôle supérieur ou égal au mien !", ephemeral=True)
            return
        
        try:
            # Send DM to user before banning
            try:
                dm_embed = discord.Embed(
                    title="Vous avez été banni",
                    description=f"Vous avez été banni de **{interaction.guild.name}**",
                    color=COLORS['error']
                )
                dm_embed.add_field(name="Raison", value=reason, inline=False)
                dm_embed.add_field(name="Modérateur", value=interaction.user.mention, inline=False)
                await member.send(embed=dm_embed)
            except discord.Forbidden:
                pass  # User has DMs disabled
            
            await member.ban(reason=f"Banni par {interaction.user} | {reason}", delete_message_days=delete_days)
            
            embed = discord.Embed(
                title="🔨 Membre Banni",
                description=f"**{member}** a été banni",
                color=COLORS['error']
            )
            embed.add_field(name="Modérateur", value=interaction.user.mention, inline=True)
            embed.add_field(name="Raison", value=reason, inline=True)
            embed.add_field(name="Messages Supprimés", value=f"{delete_days} jours", inline=True)
            embed.set_footer(text=f"ID Utilisateur: {member.id}")
            
            await interaction.response.send_message(embed=embed)
            
        except discord.Forbidden:
            await interaction.response.send_message("❌ Je n'ai pas la permission de bannir ce membre !", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Une erreur s'est produite: {str(e)}", ephemeral=True)

    @app_commands.command(name="unban", description="Unban a user from the server")
    @app_commands.describe(user_id="The ID of the user to unban", reason="Reason for the unban")
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: str = "No reason provided"):
        """Unban a user from the server"""
        if not interaction.user.guild_permissions.ban_members:
            await interaction.response.send_message("❌ You don't have permission to unban members!", ephemeral=True)
            return
        
        if not interaction.guild.me.guild_permissions.ban_members:
            await interaction.response.send_message("❌ I don't have permission to unban members!", ephemeral=True)
            return
        
        try:
            user_id = int(user_id)
        except ValueError:
            await interaction.response.send_message("❌ Invalid user ID provided!", ephemeral=True)
            return
        
        try:
            # Check if user is banned
            banned_users = [ban_entry async for ban_entry in interaction.guild.bans(limit=2000)]
            banned_user = None
            
            for ban_entry in banned_users:
                if ban_entry.user.id == user_id:
                    banned_user = ban_entry.user
                    break
            
            if not banned_user:
                await interaction.response.send_message("❌ This user is not banned!", ephemeral=True)
                return
            
            await interaction.guild.unban(banned_user, reason=f"Unbanned by {interaction.user} | {reason}")
            
            embed = discord.Embed(
                title="✅ Member Unbanned",
                description=f"**{banned_user}** has been unbanned",
                color=COLORS['success']
            )
            embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
            embed.add_field(name="Reason", value=reason, inline=True)
            embed.set_footer(text=f"User ID: {banned_user.id}")
            
            await interaction.response.send_message(embed=embed)
            
        except discord.NotFound:
            await interaction.response.send_message("❌ User not found or not banned!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to unban members!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ An error occurred: {str(e)}", ephemeral=True)

    @app_commands.command(name="mute", description="Rendre muet un membre")
    @app_commands.describe(member="Le membre à rendre muet", reason="Raison du mute")
    async def mute(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Aucune raison fournie"):
        """Mute a member"""
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("❌ Vous n'avez pas la permission de rendre muet des membres !", ephemeral=True)
            return
        
        if not interaction.guild.me.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ Je n'ai pas la permission de gérer les rôles !", ephemeral=True)
            return
        
        # Check hierarchy
        if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
            await interaction.response.send_message("❌ Vous ne pouvez pas rendre muet quelqu'un avec un rôle supérieur ou égal !", ephemeral=True)
            return
        
        try:
            mute_role = await ensure_mute_role(interaction.guild)
            
            if mute_role in member.roles:
                await interaction.response.send_message("❌ Ce membre est déjà muet !", ephemeral=True)
                return
            
            await member.add_roles(mute_role, reason=f"Rendu muet par {interaction.user} | {reason}")
            add_mute(interaction.guild.id, member.id, interaction.user.id, reason)
            
            embed = discord.Embed(
                title="🔇 Membre Rendu Muet",
                description=f"**{member}** a été rendu muet",
                color=COLORS['warning']
            )
            embed.add_field(name="Modérateur", value=interaction.user.mention, inline=True)
            embed.add_field(name="Raison", value=reason, inline=True)
            embed.set_footer(text=f"ID Utilisateur: {member.id}")
            
            await interaction.response.send_message(embed=embed)
            
        except discord.Forbidden:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Je n'ai pas la permission de rendre muet ce membre !", ephemeral=True)
        except Exception as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ Une erreur s'est produite: {str(e)}", ephemeral=True)

    @app_commands.command(name="unmute", description="Retirer le mute d'un membre")
    @app_commands.describe(member="Le membre à unmute", reason="Raison de l'unmute")
    async def unmute(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Aucune raison fournie"):
        """Unmute a member"""
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
            
            await member.remove_roles(mute_role, reason=f"Unmute par {interaction.user} | {reason}")
            remove_mute(interaction.guild.id, member.id)
            
            embed = discord.Embed(
                title="🔊 Membre Unmute",
                description=f"**{member}** n'est plus muet",
                color=COLORS['success']
            )
            embed.add_field(name="Modérateur", value=interaction.user.mention, inline=True)
            embed.add_field(name="Raison", value=reason, inline=True)
            embed.set_footer(text=f"ID Utilisateur: {member.id}")
            
            await interaction.response.send_message(embed=embed)
            
        except discord.Forbidden:
            await interaction.response.send_message("❌ Je n'ai pas la permission de retirer le mute de ce membre !", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Une erreur s'est produite: {str(e)}", ephemeral=True)

    @app_commands.command(name="warn", description="Avertir un membre")
    @app_commands.describe(member="Le membre à avertir", reason="Raison de l'avertissement")
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Aucune raison fournie"):
        """Warn a member"""
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("❌ Vous n'avez pas la permission d'avertir des membres !", ephemeral=True)
            return
        
        add_warning(interaction.guild.id, member.id, interaction.user.id, reason)
        warnings = get_warnings(interaction.guild.id, member.id)
        warning_count = len(warnings)
        
        embed = discord.Embed(
            title="⚠️ Membre Averti",
            description=f"**{member}** a été averti",
            color=COLORS['warning']
        )
        embed.add_field(name="Modérateur", value=interaction.user.mention, inline=True)
        embed.add_field(name="Raison", value=reason, inline=True)
        embed.add_field(name="Total Avertissements", value=f"{warning_count}/{MAX_WARNINGS}", inline=True)
        embed.set_footer(text=f"ID Utilisateur: {member.id}")
        
        # Auto-action based on warning count
        if warning_count >= MAX_WARNINGS:
            try:
                # Auto-mute after max warnings
                mute_role = await ensure_mute_role(interaction.guild)
                if mute_role not in member.roles:
                    await member.add_roles(mute_role, reason="Auto-mute: Nombre maximum d'avertissements atteint")
                    embed.add_field(name="Action Automatique", value="🔇 Auto-mute pour avoir atteint le maximum d'avertissements", inline=False)
            except discord.Forbidden:
                pass
        
        await interaction.response.send_message(embed=embed)
        
        # Send DM to warned user
        try:
            dm_embed = discord.Embed(
                title="Vous avez été averti",
                description=f"Vous avez reçu un avertissement dans **{interaction.guild.name}**",
                color=COLORS['warning']
            )
            dm_embed.add_field(name="Raison", value=reason, inline=False)
            dm_embed.add_field(name="Avertissements", value=f"{warning_count}/{MAX_WARNINGS}", inline=False)
            await member.send(embed=dm_embed)
        except discord.Forbidden:
            pass

    @app_commands.command(name="warnings", description="View warnings for a member")
    @app_commands.describe(member="The member to check warnings for")
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        """View warnings for a member"""
        warnings = get_warnings(interaction.guild.id, member.id)
        
        if not warnings:
            embed = discord.Embed(
                title="✅ No Warnings",
                description=f"**{member}** has no warnings",
                color=COLORS['success']
            )
        else:
            embed = discord.Embed(
                title=f"⚠️ Warnings for {member}",
                description=f"Total warnings: {len(warnings)}",
                color=COLORS['warning']
            )
            
            for i, warning in enumerate(warnings[:10], 1):  # Show last 10 warnings
                moderator = interaction.guild.get_member(warning[1])
                mod_name = moderator.mention if moderator else f"<@{warning[1]}>"
                
                embed.add_field(
                    name=f"Warning #{i}",
                    value=f"**Reason:** {warning[2]}\n**Moderator:** {mod_name}\n**Date:** {warning[3]}",
                    inline=False
                )
        
        embed.set_footer(text=f"User ID: {member.id}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="clearwarnings", description="Clear all warnings for a member")
    @app_commands.describe(member="The member to clear warnings for")
    async def clearwarnings(self, interaction: discord.Interaction, member: discord.Member):
        """Clear all warnings for a member"""
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("❌ You don't have permission to clear warnings!", ephemeral=True)
            return
        
        warnings = get_warnings(interaction.guild.id, member.id)
        
        if not warnings:
            await interaction.response.send_message(f"❌ **{member}** has no warnings to clear!", ephemeral=True)
            return
        
        clear_warnings(interaction.guild.id, member.id)
        
        embed = discord.Embed(
            title="✅ Warnings Cleared",
            description=f"All warnings for **{member}** have been cleared",
            color=COLORS['success']
        )
        embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="Warnings Cleared", value=str(len(warnings)), inline=True)
        embed.set_footer(text=f"User ID: {member.id}")
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="purge", description="Delete multiple messages")
    @app_commands.describe(amount="Number of messages to delete (1-100)", user="Only delete messages from this user")
    async def purge(self, interaction: discord.Interaction, amount: int, user: discord.Member = None):
        """Delete multiple messages"""
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("❌ You don't have permission to manage messages!", ephemeral=True)
            return
        
        if not interaction.guild.me.guild_permissions.manage_messages:
            await interaction.response.send_message("❌ I don't have permission to manage messages!", ephemeral=True)
            return
        
        if amount < 1 or amount > 100:
            await interaction.response.send_message("❌ Amount must be between 1 and 100!", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        try:
            if user:
                def check(message):
                    return message.author == user
                deleted = await interaction.channel.purge(limit=amount, check=check)
            else:
                deleted = await interaction.channel.purge(limit=amount)
            
            embed = discord.Embed(
                title="🗑️ Messages Purged",
                description=f"Deleted **{len(deleted)}** messages",
                color=COLORS['success']
            )
            embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
            if user:
                embed.add_field(name="Target User", value=user.mention, inline=True)
            embed.add_field(name="Channel", value=interaction.channel.mention, inline=True)
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except discord.Forbidden:
            await interaction.followup.send("❌ I don't have permission to delete messages!", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ An error occurred: {str(e)}", ephemeral=True)

    @app_commands.command(name="modhelp", description="Show all moderation commands")
    async def modhelp(self, interaction: discord.Interaction):
        """Show help for moderation commands"""
        embed = discord.Embed(
            title="🛡️ Moderation Commands",
            description="Here are all available moderation commands:",
            color=COLORS['info']
        )
        
        commands_list = [
            ("**Basic Moderation**", ""),
            ("`/kick`", "Kick a member from the server"),
            ("`/ban`", "Ban a member from the server"),
            ("`/unban`", "Unban a user using their ID"),
            ("`/mute`", "Mute a member (prevents them from talking)"),
            ("`/unmute`", "Remove mute from a member"),
            ("", ""),
            ("**Warning System**", ""),
            ("`/warn`", "Give a warning to a member"),
            ("`/warnings`", "View warnings for a member"),
            ("`/clearwarnings`", "Clear all warnings for a member"),
            ("", ""),
            ("**Message Management**", ""),
            ("`/purge`", "Delete multiple messages at once"),
            ("", ""),
            ("**Auto-Moderation**", ""),
            ("Spam Detection", "Automatically detects and handles spam"),
            ("Mention Spam", "Prevents excessive mention spam"),
        ]
        
        description = ""
        for cmd, desc in commands_list:
            if desc:
                description += f"{cmd} - {desc}\n"
            else:
                description += f"**{cmd}**\n"
        
        embed.description = description
        
        embed.add_field(
            name="ℹ️ Notes",
            value="• Most commands require appropriate permissions\n• The bot respects role hierarchy\n• Auto-moderation runs in the background",
            inline=False
        )
        
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(Moderation(bot))
