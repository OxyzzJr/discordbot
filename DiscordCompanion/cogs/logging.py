import discord
from discord.ext import commands
from datetime import datetime
from config import COLORS, LOG_CHANNEL_NAME
from utils.database import get_guild_settings, update_guild_settings

class Logging(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    def get_log_channel(self, guild):
        """Get the designated log channel for the guild"""
        # Try to find channel by name first
        log_channel = discord.utils.get(guild.channels, name=LOG_CHANNEL_NAME)
        
        if not log_channel:
            # Check database for custom log channel
            settings = get_guild_settings(guild.id)
            if settings and settings[0]:  # log_channel_id
                log_channel = guild.get_channel(settings[0])
        
        return log_channel
    
    async def send_log(self, guild, embed):
        """Send a log message to the designated log channel"""
        log_channel = self.get_log_channel(guild)
        
        if log_channel:
            try:
                await log_channel.send(embed=embed)
            except discord.Forbidden:
                pass  # No permission to send messages
    
    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Log when a member joins and assign default role"""
        # Try to assign "Membre" role automatically
        try:
            membre_role = discord.utils.get(member.guild.roles, name="Membre")
            if membre_role:
                await member.add_roles(membre_role, reason="Attribution automatique du rôle Membre")
                role_assigned = True
                role_status = f"Rôle **{membre_role.name}** assigné automatiquement"
            else:
                role_assigned = False
                role_status = "Rôle 'Membre' introuvable"
        except discord.Forbidden:
            role_assigned = False
            role_status = "Permission insuffisante pour assigner des rôles"
        except Exception as e:
            role_assigned = False
            role_status = f"Erreur lors de l'attribution du rôle: {str(e)}"
        
        embed = discord.Embed(
            title="📥 Membre Rejoint",
            description=f"{member.mention} a rejoint le serveur",
            color=COLORS['success'],
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Utilisateur", value=f"{member} (ID: {member.id})", inline=True)
        embed.add_field(name="Compte Créé", value=member.created_at.strftime("%Y-%m-%d %H:%M:%S"), inline=True)
        embed.add_field(name="Nombre de Membres", value=str(member.guild.member_count), inline=True)
        embed.add_field(name="Attribution de Rôle", value=role_status, inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)
        
        await self.send_log(member.guild, embed)
    
    @commands.Cog.listener()
    async def on_member_remove(self, member):
        """Log when a member leaves"""
        embed = discord.Embed(
            title="📤 Member Left",
            description=f"{member.mention} left the server",
            color=COLORS['error'],
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="User", value=f"{member} (ID: {member.id})", inline=True)
        embed.add_field(name="Joined At", value=member.joined_at.strftime("%Y-%m-%d %H:%M:%S") if member.joined_at else "Unknown", inline=True)
        embed.add_field(name="Member Count", value=str(member.guild.member_count), inline=True)
        embed.set_thumbnail(url=member.display_avatar.url)
        
        await self.send_log(member.guild, embed)
    
    @commands.Cog.listener()
    async def on_message_delete(self, message):
        """Log when a message is deleted"""
        # Ignore bot messages and DMs
        if message.author.bot or not message.guild:
            return
        
        embed = discord.Embed(
            title="🗑️ Message Deleted",
            description=f"Message by {message.author.mention} deleted in {message.channel.mention}",
            color=COLORS['error'],
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Author", value=f"{message.author} (ID: {message.author.id})", inline=True)
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        embed.add_field(name="Message ID", value=message.id, inline=True)
        
        if message.content:
            content = message.content[:1000] + "..." if len(message.content) > 1000 else message.content
            embed.add_field(name="Content", value=f"```{content}```", inline=False)
        
        if message.attachments:
            attachments = "\n".join([att.filename for att in message.attachments])
            embed.add_field(name="Attachments", value=attachments, inline=False)
        
        await self.send_log(message.guild, embed)
    
    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        """Log when a message is edited"""
        # Ignore bot messages, DMs, and if content didn't change
        if before.author.bot or not before.guild or before.content == after.content:
            return
        
        embed = discord.Embed(
            title="✏️ Message Edited",
            description=f"Message by {before.author.mention} edited in {before.channel.mention}",
            color=COLORS['warning'],
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Author", value=f"{before.author} (ID: {before.author.id})", inline=True)
        embed.add_field(name="Channel", value=before.channel.mention, inline=True)
        embed.add_field(name="Message ID", value=before.id, inline=True)
        
        if before.content:
            before_content = before.content[:500] + "..." if len(before.content) > 500 else before.content
            embed.add_field(name="Before", value=f"```{before_content}```", inline=False)
        
        if after.content:
            after_content = after.content[:500] + "..." if len(after.content) > 500 else after.content
            embed.add_field(name="After", value=f"```{after_content}```", inline=False)
        
        await self.send_log(before.guild, embed)
    
    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        """Log when a member is banned"""
        # Try to get ban reason from audit log
        reason = "No reason provided"
        moderator = None
        
        try:
            async for entry in guild.audit_logs(action=discord.AuditLogAction.ban, limit=1):
                if entry.target.id == user.id:
                    reason = entry.reason or "No reason provided"
                    moderator = entry.user
                    break
        except discord.Forbidden:
            pass
        
        embed = discord.Embed(
            title="🔨 Member Banned",
            description=f"{user.mention} was banned from the server",
            color=COLORS['error'],
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="User", value=f"{user} (ID: {user.id})", inline=True)
        embed.add_field(name="Moderator", value=moderator.mention if moderator else "Unknown", inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_thumbnail(url=user.display_avatar.url)
        
        await self.send_log(guild, embed)
    
    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        """Log when a member is unbanned"""
        # Try to get unban reason from audit log
        reason = "No reason provided"
        moderator = None
        
        try:
            async for entry in guild.audit_logs(action=discord.AuditLogAction.unban, limit=1):
                if entry.target.id == user.id:
                    reason = entry.reason or "No reason provided"
                    moderator = entry.user
                    break
        except discord.Forbidden:
            pass
        
        embed = discord.Embed(
            title="✅ Member Unbanned",
            description=f"{user.mention} was unbanned from the server",
            color=COLORS['success'],
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="User", value=f"{user} (ID: {user.id})", inline=True)
        embed.add_field(name="Moderator", value=moderator.mention if moderator else "Unknown", inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_thumbnail(url=user.display_avatar.url)
        
        await self.send_log(guild, embed)
    
    @discord.app_commands.command(name="setlogchannel", description="Set the moderation log channel")
    @discord.app_commands.describe(channel="The channel to use for moderation logs")
    async def setlogchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Set the log channel for the guild"""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need administrator permissions to set the log channel!", ephemeral=True)
            return
        
        # Update guild settings
        update_guild_settings(interaction.guild.id, log_channel_id=channel.id)
        
        embed = discord.Embed(
            title="✅ Log Channel Set",
            description=f"Moderation logs will now be sent to {channel.mention}",
            color=COLORS['success']
        )
        
        await interaction.response.send_message(embed=embed)
        
        # Send a test log message
        test_embed = discord.Embed(
            title="📋 Logging System Active",
            description="This channel has been set as the moderation log channel.",
            color=COLORS['info'],
            timestamp=datetime.utcnow()
        )
        test_embed.add_field(name="Set by", value=interaction.user.mention, inline=True)
        
        await channel.send(embed=test_embed)

async def setup(bot):
    await bot.add_cog(Logging(bot))
