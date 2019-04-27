import asyncio
import logging

import discord
from discord.ext import commands

from Discordia.ConfigParser import DISCORD_PREFIX, DISCORD_MSG_TIMEOUT
from Discordia.Interface.WorldAdapter import WorldAdapter, AlreadyRegisteredException, NotRegisteredException
import Discordia.GameLogic.Actors as Actors

LOG = logging.getLogger("Discordia.Interface.DiscordServer")

Context = discord.ext.commands.context.Context


class DiscordInterface(commands.Cog):
    def __init__(self, world_adapter: WorldAdapter):
        self.bot: commands.Bot = commands.Bot(command_prefix=DISCORD_PREFIX)
        self.bot.add_listener(self.on_ready, "on_ready")
        self.bot.add_cog(self)
        self.world_adapter: WorldAdapter = world_adapter

    @staticmethod
    def _check_response(ctx: Context, message: discord.Message, phrase: str = None, exact: bool = False) -> bool:
        chk_author = ctx.author == message.author
        chk_channel = ctx.channel == message.channel
        if phrase:
            if exact:
                chk_phrase = message.content.lower() == phrase
            else:
                chk_phrase = phrase in message.content.lower()
        else:
            chk_phrase = True
        return chk_author and chk_channel and chk_phrase

    async def on_ready(self):
        LOG.info(f"Connected successfully: {self.bot.user.name}: <{self.bot.user.id}>")

    @commands.command()
    async def register(self, ctx: Context):
        member: discord.Member = ctx.author
        LOG.info(f"[p]register called by {member.display_name}: <{member.id}>")
        try:
            await ctx.send("Are you sure you want to join the MUD? (say 'yes' to continue)")
            await self.bot.wait_for('message', check=lambda m: self._check_response(ctx, m, 'yes', True),
                                    timeout=DISCORD_MSG_TIMEOUT)

            await ctx.send(f"Choose a character name: ")
            resp: discord.Message = await self.bot.wait_for('message', timeout=DISCORD_MSG_TIMEOUT)
            name: str = resp.clean_content.strip(DISCORD_PREFIX)
            self.world_adapter.register_player(member.id, player_name=name)
        except AlreadyRegisteredException:
            LOG.warning("Player tried to re-register.")
            await ctx.send(f"Player {member.display_name} is already registered.")
        except asyncio.TimeoutError:
            await ctx.send(f"Took move than {DISCORD_MSG_TIMEOUT}s to respond...")
        else:
            await ctx.send(f"User {member.display_name} has been registered! "
                           f"Or should I say {name}? Good luck out there, comrade!")

    @commands.command()
    async def equipment(self, ctx: Context):
        member = ctx.author
        try:
            character: Actors.PlayerCharacter = self.world_adapter.get_player(member.id)
            msg = "Equipment: \n" \
                  "---------- \n" \
                  "{}".format(str(character.equipment_set))
            await ctx.send(msg)
        except NotRegisteredException:
            await ctx.send(f"User {member.display_name} has not yet registered. Please use `{DISCORD_PREFIX}register` "
                           f"to create a character.")

    @commands.command()
    async def look(self, ctx: Context):
        member = ctx.author
        try:
            character: Actors.PlayerCharacter = self.world_adapter.get_player(member.id)
            msg: str = f"Your coordinates are {character.location}."
            if self.world_adapter.is_town(character.location):
                msg += f"You are also in a town, {character.location.name}."
            if self.world_adapter.is_wilds(character.location):
                msg += "You are also in the wilds."
        except NotRegisteredException:
            await ctx.send(f"User {member.display_name} has not yet registered. Please use `{DISCORD_PREFIX}register` "
                           f"to create a character.")
        else:
            await ctx.send(msg)