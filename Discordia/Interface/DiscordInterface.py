import asyncio
import logging

import discord
from discord.ext import commands

from Discordia.ConfigParser import DISCORD_PREFIX, DISCORD_MSG_TIMEOUT
from Discordia.Interface.WorldAdapter import WorldAdapter, RegistrationException

LOG = logging.getLogger("Discordia.Interface.DiscordServer")

Context = discord.ext.commands.context.Context


class DiscordInterface(commands.Cog):
    def __init__(self, world_adapter: WorldAdapter):
        self.bot: commands.Bot = commands.Bot(command_prefix=DISCORD_PREFIX)
        self.bot.add_listener(self.on_ready, "on_ready")
        self.bot.add_cog(self)
        self.world_adapter: WorldAdapter = world_adapter

    async def on_ready(self):
        LOG.info(f"Connected successfully: {self.bot.user.name}: <{self.bot.user.id}>")

    @commands.command(name='register')
    async def register(self, ctx: Context):
        member: discord.Member = ctx.author
        LOG.info(f"[p]register called by {member.display_name}: <{member.id}>")
        try:
            # Currently just adds player id to dictionary. Maybe move to end of command?
            self.world_adapter.register_player(member.id)
        except RegistrationException:
            LOG.exception("Error trying to register")
            await ctx.send(f"User {member.display_name} has already been registered.")
            return
        await ctx.send("Are you sure you want to join the MUD? (say 'yes' to continue)")
        try:
            await self.bot.wait_for('message', check=lambda
                m: m.author == member and m.channel == ctx.channel and m.content.lower() == 'yes',
                                          timeout=DISCORD_MSG_TIMEOUT)
        except asyncio.TimeoutError:
            await ctx.send("Nevermind...")
        else:
            await ctx.send(f"User {member.display_name} successfully registered!")
