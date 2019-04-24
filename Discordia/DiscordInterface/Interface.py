import logging

import discord
from discord.ext import commands

from Discordia.ConfigParser import DISCORD_PREFIX

LOG = logging.getLogger("Discordia.DiscordInterface.DiscordServer")

Context = discord.ext.commands.context.Context


class DiscordInterface(commands.Cog):
    def __init__(self):
        self.bot: commands.Bot = commands.Bot(command_prefix=DISCORD_PREFIX)
        self.bot.add_listener(self.on_ready, "on_ready")
        self.bot.add_cog(self)

    @commands.command(name='register')
    async def register(self, ctx: Context):
        LOG.info("Register called")

    async def on_ready(self):
        LOG.info(f"Bot connected {self.bot.user.name} <{self.bot.user.id}>")