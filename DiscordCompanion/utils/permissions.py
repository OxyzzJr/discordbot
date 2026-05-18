import discord
from discord.ext import commands


def has_mod_permissions():
    """Vérifie si l'utilisateur a des permissions de modération."""
    def predicate(ctx):
        return ctx.author.guild_permissions.manage_messages or ctx.author.guild_permissions.kick_members
    return commands.check(predicate)


def has_admin_permissions():
    """Vérifie si l'utilisateur est administrateur."""
    def predicate(ctx):
        return ctx.author.guild_permissions.administrator
    return commands.check(predicate)


def has_ban_permissions():
    """Vérifie si l'utilisateur peut bannir."""
    def predicate(ctx):
        return ctx.author.guild_permissions.ban_members
    return commands.check(predicate)


async def check_hierarchy(ctx, target_member):
    """Vérifie que le modérateur et le bot peuvent agir sur la cible."""
    if target_member == ctx.author:
        await ctx.send("❌ Vous ne pouvez pas utiliser cette commande sur vous-même !")
        return False
    if target_member == ctx.guild.owner:
        await ctx.send("❌ Vous ne pouvez pas utiliser cette commande sur le propriétaire du serveur !")
        return False
    if target_member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
        await ctx.send("❌ Vous ne pouvez pas agir sur quelqu'un avec un rôle supérieur ou égal !")
        return False
    if target_member.top_role >= ctx.guild.me.top_role:
        await ctx.send("❌ Je ne peux pas agir sur quelqu'un avec un rôle supérieur ou égal au mien !")
        return False
    return True


async def ensure_mute_role(guild):
    """Crée ou récupère le rôle Muted avec les permissions appropriées."""
    from config import MUTE_ROLE_NAME

    mute_role = discord.utils.get(guild.roles, name=MUTE_ROLE_NAME)

    if not mute_role:
        mute_role = await guild.create_role(
            name=MUTE_ROLE_NAME,
            color=discord.Color.dark_gray(),
            reason="Création automatique du rôle Muted"
        )
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
