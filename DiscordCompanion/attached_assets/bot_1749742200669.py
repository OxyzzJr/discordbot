import random
import math
import discord
from discord import app_commands
from discord.ext import commands

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"{bot.user} est en ligne !")
    try:
        synced = await bot.tree.sync()
        print(f"Commandes slash synchronisées : {len(synced)}")
    except Exception as e:
        print(f"Erreur de sync : {e}")

@bot.tree.command(name="ntm", description="ntm")
@app_commands.describe(user="La personne que vous voulez niquer la mams a ")
async def ntm(interaction: discord.Interaction, user: discord.Member):
    await interaction.response.send_message(f"pine ta mams {user.mention} !")

@bot.tree.command(name="fdpduserv", description="Mentionne un membre donné comme le fdp")
@app_commands.describe(user="Le membre que vous voulez mentionner")
async def fdpduserv(interaction: discord.Interaction, user: discord.Member):
    await interaction.response.send_message(f"{user.mention} est le plus gros fdp que ce monde ai connu meme gazem prime n'arrive pas a sa cheville!!!")

@bot.tree.command(name="turc", description="kardesh")
async def turc(interaction: discord.Interaction):
    await interaction.response.send_message("Arap tout casser et flemmard et vendre shit et voler Nous kardeshim faire kredi por bmw a 16 ans vous arap tout casser turk tout reparer MEHMET IL EST OÙ MON AYRAN BRRRRRRRRR SKIBIDI DOP DOP YES YES YES MANGER KEBAB JAMAIS MALAD")

bot.run("MTMzMzgyMjQ3MjE1MTM2Nzc0Mg.GB2sLG.YWDYaMeBqzSevFgk_hF4AcT6t-KSAhm7Cv64qA")
