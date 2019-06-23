from __future__ import annotations

import asyncio
import logging
import time
from typing import List

import discord
from discord.ext import commands

import Discordia.GameLogic.Actors as Actors
from Discordia.ConfigParser import DISCORD_PREFIX, DISCORD_MSG_TIMEOUT
from Discordia.GameLogic import GameSpace
from Discordia.GameLogic.GameSpace import PlayerActionResponse, DIRECTION_VECTORS
from Discordia.GameLogic.Items import Equipment
from Discordia.Interface.WorldAdapter import WorldAdapter, AlreadyRegisteredException, NotRegisteredException, \
    InvalidSpaceException, NoWeaponEquippedException, RangedAttackException, CombatException

LOG = logging.getLogger("Discordia.Interface.DiscordServer")

Context = discord.ext.commands.context.Context


def direction_vector(argument: str) -> GameSpace.Direction:
    """A discord.py Converter for changing strings (n,s,e,w, and combos) to unit vector Tuple[int,int]"""
    argument = argument.lower()
    directions = GameSpace.DIRECTION_VECTORS
    if argument not in directions.keys():
        argument = None
    return directions[argument]


class DiscordInterface(commands.Cog):
    def __init__(self, world_adapter: WorldAdapter):
        self.bot: commands.Bot = commands.Bot(command_prefix=DISCORD_PREFIX)
        self.bot.add_listener(self._on_ready, "on_ready")
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

    async def _on_ready(self):
        LOG.info(f"Connected successfully: {self.bot.user.name}: <{self.bot.user.id}>")

    @commands.command()
    async def register(self, ctx: Context):
        """*START HERE* Make a new character in the world"""
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
            LOG.warning(f"{member.display_name} tried to re-register.")
            await ctx.send(f"Player {member.display_name} is already registered.")
        except asyncio.TimeoutError:
            LOG.warning(f"Took more than {DISCORD_MSG_TIMEOUT}s for {member.display_name} to respond.")
            await ctx.send(f"Took more than {DISCORD_MSG_TIMEOUT}s to respond...")
        else:
            await ctx.send(f"User {member.display_name} has been registered! "
                           f"Or should I say {name}? Good luck out there, comrade!")

    @commands.command()
    async def equipment(self, ctx: Context):
        """List all equipped items on character"""
        member = ctx.author
        try:
            character: Actors.PlayerCharacter = self.world_adapter.get_player(member.id)
            msg = "Equipment: \n" \
                  "---------- \n" \
                  "{}".format(str(character.equipment_set))
            await ctx.send(msg)
        except NotRegisteredException:
            LOG.warning(f"Player {member.display_name} not registered: Tried to access `equipment`")
            await ctx.send(f"User {member.display_name} has not yet registered. Please use `{DISCORD_PREFIX}register` "
                           f"to create a character.")

    @commands.command()
    async def look(self, ctx: Context):
        """Describes your character's surroundings"""
        member = ctx.author
        try:
            character: Actors.PlayerCharacter = self.world_adapter.get_player(member.id)
            msg = f"Your coordinates are {character.location}. The terrain is {character.location.terrain.name}-y. "
            if self.world_adapter.is_town(character.location):
                msg += f"You are also in a town, {character.location.name}. "
            if self.world_adapter.is_wilds(character.location):
                msg += f"You are also in the wilds, {character.location.name}. "
            nearby_npcs = self.world_adapter.get_nearby_npcs(character)
            if nearby_npcs:
                msg += "There are some NPCs nearby: \n" + \
                       ", ".join([str(npc) for npc in nearby_npcs])
            nearby_players = self.world_adapter.get_nearby_players(character)
            if len(nearby_players) > 1:
                msg += "\nThere are also some Players nearby: \n" + \
                       ", ".join([player.name for player in nearby_players if player.name != character.name])
            screenshot_path = self.world_adapter.get_player_screenshot(character)
        except NotRegisteredException:
            LOG.warning(f"Player {member.display_name} not registered: Tried to access `look`")
            await ctx.send(f"User {member.display_name} has not yet registered. Please use `{DISCORD_PREFIX}register` "
                           f"to create a character.")
        else:
            discord_file = discord.File(screenshot_path)
            await ctx.send(msg, file=discord_file)

    @commands.group()
    async def inventory(self, ctx: Context):
        """Lists all the items in your inventory with ID #"""
        member = ctx.author
        try:
            character: Actors.PlayerCharacter = self.world_adapter.get_player(member.id)
            if ctx.invoked_subcommand is None:
                msg = f"{character.name}'s inventory:\n"
                if len(character.inventory) == 0:
                    msg += "\t(Empty)"
                else:
                    for index, item in enumerate(character.inventory):
                        msg += f"\t#{index}\t{item}\n"
                await ctx.send(msg)
        except NotRegisteredException:
            LOG.warning(f"Player {member.display_name} not registered: Tried to access `inventory`")
            await ctx.send(f"User {member.display_name} has not yet registered. Please use `{DISCORD_PREFIX}register` "
                           f"to create a character.")

    @inventory.command()
    async def equip(self, ctx: Context, index: int):
        """Equip the item at the given index"""
        member = ctx.author
        try:
            character: Actors.PlayerCharacter = self.world_adapter.get_player(member.id)
            item: Equipment = character.inventory[index]
            character.equip(item)
        except NotRegisteredException:
            LOG.warning(f"Player {member.display_name} not registered: Tried to access `equip`")
            await ctx.send(f"User {member.display_name} has not yet registered. Please use `{DISCORD_PREFIX}register` "
                           f"to create a character.")
        except IndexError:
            await ctx.send(f"Given index {index} is invalid.")

    @inventory.command()
    async def unequip(self, ctx: Context, index: int):
        """Unequip the item at the given index"""
        member = ctx.author
        try:
            character: Actors.PlayerCharacter = self.world_adapter.get_player(member.id)
            item: Equipment = character.inventory[index]
            character.unequip(item)
        except NotRegisteredException:
            LOG.warning(f"Player {member.display_name} not registered: Tried to access `unequip`")
            await ctx.send(f"User {member.display_name} has not yet registered. Please use `{DISCORD_PREFIX}register` "
                           f"to create a character.")
        except IndexError:
            await ctx.send(f"Given index {index} is invalid.")

    async def _move_player(self, ctx, direction):
        try:
            character: Actors.PlayerCharacter = self.world_adapter.get_player(ctx.author.id)
            results: List[PlayerActionResponse] = self.world_adapter.move_player(character, direction)

            msg = ""

            # If any Events happen, let the PC know step-by-step
            if results:
                for r in results:
                    if r.text:
                        msg += (r.text + '\n')
                    if not r.is_successful:
                        break

                if msg:
                    for i in range(0, len(msg) - 1, 2000):
                        await ctx.send(msg[i:i+2000])

            character.last_time_moved = time.time()
        except NotRegisteredException:
            LOG.warning(f"Player {ctx.author.display_name} not registered: Tried to access movement.")
            await ctx.send(
                f"User {ctx.author.display_name} has not yet registered. Please use `{DISCORD_PREFIX}register` "
                f"to create a character.")
        except InvalidSpaceException:
            await ctx.send("Invalid direction.")

    @commands.command()
    async def north(self, ctx: Context):
        """Move your character north"""
        await self._move_player(ctx, DIRECTION_VECTORS['n'])

    @commands.command()
    async def up(self, ctx: Context):
        """Move your character north"""
        await self._move_player(ctx, DIRECTION_VECTORS['n'])

    @commands.command()
    async def south(self, ctx: Context):
        """Move your character south"""
        await self._move_player(ctx, DIRECTION_VECTORS['s'])

    @commands.command()
    async def down(self, ctx: Context):
        """Move your character south"""
        await self._move_player(ctx, DIRECTION_VECTORS['s'])

    @commands.command()
    async def east(self, ctx: Context):
        """Move your character east"""
        await self._move_player(ctx, DIRECTION_VECTORS['e'])

    @commands.command()
    async def right(self, ctx: Context):
        """Move your character east"""
        await self._move_player(ctx, DIRECTION_VECTORS['e'])

    @commands.command()
    async def west(self, ctx: Context):
        """Move your character west"""
        await self._move_player(ctx, DIRECTION_VECTORS['w'])

    @commands.command()
    async def left(self, ctx: Context):
        """Move your character west"""
        await self._move_player(ctx, DIRECTION_VECTORS['w'])

    @commands.command()
    async def attack(self, ctx: Context, *, direction: direction_vector = None):
        """Have your character perform an attack, with optional direction:
        (n,s,e,w,ne,se,sw,nw)"""
        member = ctx.author
        try:
            character: Actors.PlayerCharacter = self.world_adapter.get_player(member.id)
            response: PlayerActionResponse = self.world_adapter.attack(character, direction)
            await ctx.send(f"{character.name} deals {response.damage} to {response.target.name}.\n"
                           f"\n"
                           f" {response.text}")
        except NotRegisteredException:
            LOG.warning(f"Player {member.display_name} not registered: Tried to access `attack`")
            await ctx.send(f"User {member.display_name} has not yet registered. Please use `{DISCORD_PREFIX}register` "
                           f"to create a character.")
        except NoWeaponEquippedException:
            await ctx.send(f"Player {member.display_name} tried to attack without a weapon equipped. Try equipping a"
                           f"weapon with {DISCORD_PREFIX}equip.")
        except RangedAttackException:
            await ctx.send(f"Player {member.display_name} tried to make a ranged attack without a ranged weapon.")
        except CombatException as e:
            await ctx.send(f"Attack failed: {str(e)}")

    @commands.group(invoke_without_command=True)
    async def town(self, ctx: Context):
        """Check if you're in a town."""
        member = ctx.author
        try:
            character: Actors.PlayerCharacter = self.world_adapter.get_player(member.id)
            if self.world_adapter.is_town(character.location):
                await ctx.send(f"You're currently in {character.location.name}.")
            else:
                await ctx.send(f"You're currently not in a town...")
        except NotRegisteredException:
            LOG.warning(f"Player {member.display_name} not registered: Tried to access `town`")
            await ctx.send(f"User {member.display_name} has not yet registered. Please use `{DISCORD_PREFIX}register` "
                           f"to create a character.")

    @town.command()
    async def inn(self, ctx: Context):
        """Rest to restore hitpoints."""
        member = ctx.author
        try:
            character: Actors.PlayerCharacter = self.world_adapter.get_player(member.id)
            if self.world_adapter.is_town(character.location):
                resp: PlayerActionResponse = character.location.inn_event(character)
                await ctx.send(resp.text)
        except NotRegisteredException:
            LOG.warning(f"Player {member.display_name} not registered: Tried to access `inn`")
            await ctx.send(f"User {member.display_name} has not yet registered. Please use `{DISCORD_PREFIX}register` "
                           f"to create a character.")

    @town.group(invoke_without_command=True)
    async def store(self, ctx: Context):
        member = ctx.author
        try:
            character: Actors.PlayerCharacter = self.world_adapter.get_player(member.id)
            town: GameSpace.Town = character.location
            if self.world_adapter.is_town(character.location):
                if town.store is not None:
                    if len(town.store.inventory) == 0:
                        msg = "There are no items in the store at the moment. Please try again later."
                    else:
                        msg = "Index\tName\tPrice\tCount\n"
                        for idx, item in enumerate(set(town.store.inventory)):
                            msg += "#{}\t{}\t${}\t{}\n".format(idx,
                                                               item.name,
                                                               town.store.get_price(item),
                                                               town.store.inventory.count(item))
                else:
                    msg = "There is no store in this town. Sorry..."
                await ctx.send(msg)
            else:
                await ctx.send("You're not in a town. Find one before trying to use a store.")
        except NotRegisteredException:
            LOG.warning(f"Player {member.display_name} not registered: Tried to access `inn`")
            await ctx.send(f"User {member.display_name} has not yet registered. Please use `{DISCORD_PREFIX}register` "
                           f"to create a character.")

    @store.command()
    async def buy(self, ctx: Context, index: int = None):
        if index is None:
            await ctx.send("You must give an item index to buy.")
        else:
            member = ctx.author
            try:
                character: Actors.PlayerCharacter = self.world_adapter.get_player(member.id)
                town: GameSpace.Town = character.location
                if self.world_adapter.is_town(character.location):
                    if town.store is not None:
                        if town.store.sell_item(index, character):
                            await ctx.send(f"Item successfully bought.")
                        else:
                            await ctx.send(f"Not enough money")
                    else:
                        await ctx.send("Town doesn't have a store.")
                else:
                    await ctx.send("Please enter a town before trying to buy.")
            except NotRegisteredException:
                LOG.warning(f"Player {member.display_name} not registered: Tried to access `inn`")
                await ctx.send(
                    f"User {member.display_name} has not yet registered. Please use `{DISCORD_PREFIX}register` "
                    f"to create a character.")

    @store.command()
    async def sell(self, ctx: Context, index: int = None):
        if index is None:
            await ctx.send("You must give an item index to sell.")
        else:
            member = ctx.author
            try:
                character: Actors.PlayerCharacter = self.world_adapter.get_player(member.id)
                item: Equipment = character.inventory[index]
                town: GameSpace.Town = character.location
                if self.world_adapter.is_town(character.location):
                    if town.store is not None:
                        price = town.store.buy_item(item, character)
                        await ctx.send(f"Successfully sold {item.name} for ${price}.")
                    else:
                        await ctx.send("Town doesn't have a store.")
                else:
                    await ctx.send("Please enter a town before trying to buy.")
            except IndexError:
                await ctx.send(f"Invalid index {index} given.")
            except NotRegisteredException:
                LOG.warning(f"Player {member.display_name} not registered: Tried to access `inn`")
                await ctx.send(
                    f"User {member.display_name} has not yet registered. Please use `{DISCORD_PREFIX}register` "
                    f"to create a character.")
