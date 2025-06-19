import discord
from discord.ext import commands
from functools import wraps

def has_mod_permissions():
    """Decorator to check if user has moderation permissions"""
    def predicate(ctx):
        if ctx.author.guild_permissions.manage_messages or ctx.author.guild_permissions.kick_members:
            return True
        return False
    return commands.check(predicate)

def has_admin_permissions():
    """Decorator to check if user has admin permissions"""
    def predicate(ctx):
        if ctx.author.guild_permissions.administrator:
            return True
        return False
    return commands.check(predicate)

def has_ban_permissions():
    """Decorator to check if user has ban permissions"""
    def predicate(ctx):
        if ctx.author.guild_permissions.ban_members:
            return True
        return False
    return commands.check(predicate)

async def check_hierarchy(ctx, target_member):
    """Check if the command invoker and bot can act on the target member"""
    if target_member == ctx.author:
        await ctx.send("❌ You cannot use this command on yourself!")
        return False
    
    if target_member == ctx.guild.owner:
        await ctx.send("❌ You cannot use this command on the server owner!")
        return False
    
    if target_member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
        await ctx.send("❌ You cannot use this command on someone with a higher or equal role!")
        return False
    
    if target_member.top_role >= ctx.guild.me.top_role:
        await ctx.send("❌ I cannot act on someone with a higher or equal role than me!")
        return False
    
    return True

async def ensure_mute_role(guild):
    """Ensure mute role exists and has proper permissions"""
    from config import MUTE_ROLE_NAME
    
    mute_role = discord.utils.get(guild.roles, name=MUTE_ROLE_NAME)
    
    if not mute_role:
        # Create mute role
        mute_role = await guild.create_role(
            name=MUTE_ROLE_NAME,
            color=discord.Color.dark_gray(),
            reason="Automatic mute role creation"
        )
        
        # Set permissions for all channels
        for channel in guild.channels:
            try:
                if isinstance(channel, discord.TextChannel):
                    await channel.set_permissions(
                        mute_role,
                        send_messages=False,
                        add_reactions=False,
                        send_messages_in_threads=False,
                        create_public_threads=False,
                        create_private_threads=False
                    )
                elif isinstance(channel, discord.VoiceChannel):
                    await channel.set_permissions(
                        mute_role,
                        speak=False,
                        stream=False,
                        use_voice_activation=False
                    )
            except discord.Forbidden:
                continue
    
    return mute_role
