import discord
from discord.ext import commands
from collections import defaultdict, deque
import time
import re
from config import SPAM_THRESHOLD, SPAM_INTERVAL, MAX_MENTIONS, COLORS
from utils.permissions import ensure_mute_role

class AutoMod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.spam_tracker = defaultdict(lambda: deque())
        self.last_messages = defaultdict(str)
        
        # Regex patterns for auto-moderation
        self.invite_pattern = re.compile(r'discord\.gg/[a-zA-Z0-9]+|discord\.com/invite/[a-zA-Z0-9]+|discordapp\.com/invite/[a-zA-Z0-9]+')
        self.spam_words = ['spam', 'scam', 'free nitro', 'free money', 'click here']
        
    @commands.Cog.listener()
    async def on_message(self, message):
        # Ignore bot messages and DMs
        if message.author.bot or not message.guild:
            return
        
        # Skip if user has manage messages permission
        if message.author.guild_permissions.manage_messages:
            return
        
        # Check for spam
        await self._check_spam(message)
        
        # Check for excessive mentions
        await self._check_mention_spam(message)
        
        # Check for Discord invites
        await self._check_discord_invites(message)
        
        # Check for suspicious content
        await self._check_suspicious_content(message)
    
    async def _check_spam(self, message):
        """Check for message spam"""
        user_id = message.author.id
        current_time = time.time()
        
        # Add current message time to tracker
        self.spam_tracker[user_id].append(current_time)
        
        # Remove old messages outside the time window
        while self.spam_tracker[user_id] and current_time - self.spam_tracker[user_id][0] > SPAM_INTERVAL:
            self.spam_tracker[user_id].popleft()
        
        # Check if user exceeded spam threshold
        if len(self.spam_tracker[user_id]) >= SPAM_THRESHOLD:
            await self._handle_spam_violation(message, "Message spam detected")
            # Clear the tracker for this user
            self.spam_tracker[user_id].clear()
        
        # Check for repeated messages
        if self.last_messages[user_id] == message.content and len(message.content) > 10:
            await self._handle_spam_violation(message, "Repeated message spam")
        
        self.last_messages[user_id] = message.content
    
    async def _check_mention_spam(self, message):
        """Check for excessive mentions"""
        mention_count = len(message.mentions) + len(message.role_mentions)
        
        if mention_count >= MAX_MENTIONS:
            await self._handle_spam_violation(message, f"Excessive mentions ({mention_count} mentions)")
    
    async def _check_discord_invites(self, message):
        """Check for Discord invite links"""
        if self.invite_pattern.search(message.content):
            # Check if user has permission to post invites
            if not message.author.guild_permissions.manage_messages:
                try:
                    await message.delete()
                    
                    embed = discord.Embed(
                        title="🔗 Lien d'Invitation Supprimé",
                        description=f"{message.author.mention}, les liens d'invitation Discord ne sont pas autorisés !",
                        color=COLORS['warning']
                    )
                    
                    warning_msg = await message.channel.send(embed=embed)
                    
                    # Delete the warning message after 10 seconds
                    await warning_msg.delete(delay=10)
                    
                except discord.Forbidden:
                    pass
    
    async def _check_suspicious_content(self, message):
        """Check for suspicious/scam content"""
        content_lower = message.content.lower()
        
        for spam_word in self.spam_words:
            if spam_word in content_lower:
                await self._handle_spam_violation(message, f"Suspicious content detected: {spam_word}")
                break
    
    async def _handle_spam_violation(self, message, reason):
        """Handle spam violations"""
        try:
            # Delete the spam message
            await message.delete()
            
            # Try to mute the user
            try:
                mute_role = await ensure_mute_role(message.guild)
                if mute_role not in message.author.roles:
                    await message.author.add_roles(mute_role, reason=f"Auto-mod: {reason}")
                    
                    embed = discord.Embed(
                        title="🤖 Auto-Moderation Action",
                        description=f"{message.author.mention} has been temporarily muted",
                        color=COLORS['warning']
                    )
                    embed.add_field(name="Reason", value=reason, inline=True)
                    embed.add_field(name="Action", value="Temporary mute", inline=True)
                    embed.set_footer(text="Auto-moderation system")
                    
                    # Send notification and delete after 15 seconds
                    notification = await message.channel.send(embed=embed)
                    await notification.delete(delay=15)
                    
                    # Auto-unmute after 5 minutes
                    await self._schedule_auto_unmute(message.author, mute_role, 300)  # 5 minutes
                    
            except discord.Forbidden:
                # If can't mute, just send a warning
                embed = discord.Embed(
                    title="⚠️ Auto-Moderation Warning",
                    description=f"{message.author.mention}, please follow the server rules!",
                    color=COLORS['warning']
                )
                embed.add_field(name="Violation", value=reason, inline=True)
                
                warning_msg = await message.channel.send(embed=embed)
                await warning_msg.delete(delay=10)
                
        except discord.Forbidden:
            pass  # Can't delete message or take action
    
    async def _schedule_auto_unmute(self, member, mute_role, delay):
        """Schedule automatic unmute after a delay"""
        import asyncio
        
        async def auto_unmute():
            await asyncio.sleep(delay)
            try:
                if mute_role in member.roles:
                    await member.remove_roles(mute_role, reason="Auto-unmute: Temporary mute expired")
            except (discord.Forbidden, discord.NotFound):
                pass
        
        # Create task for auto-unmute
        self.bot.loop.create_task(auto_unmute())
    
    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        """Check edited messages for violations"""
        # Only check if content actually changed
        if before.content != after.content:
            await self.on_message(after)

async def setup(bot):
    await bot.add_cog(AutoMod(bot))
