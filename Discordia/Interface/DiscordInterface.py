from __future__ import annotations

import asyncio
import inspect
import logging
import random
import time
from typing import Any, Callable, Dict, Iterator, List, Sequence, Tuple, cast

import discord
from discord import app_commands
from discord.ext import commands, tasks

import Discordia.GameLogic.Actors as Actors
from ConfigParser import DISCORD_PREFIX
from Discordia.GameLogic import GameSpace
from Discordia.GameLogic.GameSpace import PlayerActionResponse, DIRECTION_VECTORS
from Discordia.GameLogic.Items import Equipment
from Discordia.Interface.WorldAdapter import (
    WorldAdapter,
    AlreadyRegisteredException,
    NotRegisteredException,
    NotSpawnedException,
    InvalidSpaceException,
    NoWeaponEquippedException,
    RangedAttackException,
    CombatException,
)

LOG = logging.getLogger("Discordia.Interface.DiscordServer")

DIRECTION_CHOICES = [
    app_commands.Choice(name=name, value=key)
    for name, key in [
        ("north", "n"),
        ("south", "s"),
        ("east", "e"),
        ("west", "w"),
        ("northeast", "ne"),
        ("southeast", "se"),
        ("southwest", "sw"),
        ("northwest", "nw"),
    ]
]

NO_STORE = "There's no store here. Find a town that has one."

SUPERSEDED = (
    object()
)  # what an order resolves to when the player replaces it before the tick


def _character(interaction: discord.Interaction) -> Actors.PlayerCharacter:
    """The character behind an interaction. Checks only get the interaction, so dig the cog out of the command."""
    cog = getattr(interaction.command, "binding", None)
    assert isinstance(
        cog, DiscordInterface
    ), "check used outside the DiscordInterface cog"
    return cog.world_adapter.get_player(
        interaction.user.id
    )  # raises NotRegisteredException


def requires_character():
    """Prerequisite check: caller has a registered character that's spawned into the world."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if not _character(interaction).registered:
            raise NotSpawnedException
        return True

    return app_commands.check(predicate)


def requires_space(space_type: type[GameSpace.Space]):
    """Prerequisite check: caller's character is in a Space of the given type."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if not isinstance(_character(interaction).location, space_type):
            raise InvalidSpaceException(
                f"You need to be in a {space_type.__name__.lower()} to do that."
            )
        return True

    return app_commands.check(predicate)


def _town_of(character: Actors.PlayerCharacter) -> GameSpace.Town:
    """The town the character is standing in. Only valid under @requires_space(GameSpace.Town)."""
    return cast(GameSpace.Town, character.location)


def _chunks(text: str, size: int = 2000) -> Iterator[str]:
    """Discord rejects any message over 2000 characters."""
    for start in range(0, len(text), size):
        yield text[start : start + size]


async def _send(interaction: discord.Interaction, content: str, **kwargs):
    """Reply to an interaction whether or not it's already been responded to/deferred."""
    if interaction.response.is_done():
        await interaction.followup.send(content, **kwargs)
    else:
        await interaction.response.send_message(content, **kwargs)


class DiscordInterface(commands.Cog):
    inventory = app_commands.Group(
        name="inventory", description="Look at and equip the items you're carrying"
    )
    town = app_commands.Group(
        name="town", description="Interact with the town you're standing in"
    )
    store = app_commands.Group(
        name="store", description="Buy and sell items", parent=town
    )

    def __init__(
        self,
        world_adapter: WorldAdapter,
        jobs: Sequence[Tuple[float, Callable[[], None], str]] = (),
        tick_seconds: float = 5.0,
    ):
        """`jobs` are (seconds, action, name) triples run periodically alongside the commands."""
        self.bot: commands.Bot = commands.Bot(
            command_prefix=str(DISCORD_PREFIX), intents=discord.Intents.default()
        )
        # ponytail: attribute override instead of a Bot subclass; subclass it if the bot needs more hooks
        self.bot.setup_hook = self._setup_hook
        self.world_adapter: WorldAdapter = world_adapter
        self.jobs = jobs
        self.tick_seconds = tick_seconds
        self._job_loops: List[tasks.Loop] = (
            []
        )  # kept alive; a Loop nobody holds gets collected
        self._orders: Dict[
            Actors.PlayerCharacter, Tuple[Callable[[], Any], asyncio.Future]
        ] = {}

    def _start_job(self, seconds: float, action: Callable[[], Any], name: str):
        """Run `action` every `seconds` on the bot's event loop: same thread as the commands, so no locking.

        Each job blocks command handling while it runs, which is why they're all short. A job may be
        a coroutine function; the tick is one, because it sends DMs.
        """

        @tasks.loop(seconds=seconds)
        async def job():
            try:
                result = action()
                if inspect.isawaitable(result):
                    await result
            except Exception:
                LOG.exception("%s failed", name)

        job.start()
        self._job_loops.append(job)

    def order(
        self, character: Actors.PlayerCharacter, action: Callable[[], Any]
    ) -> asyncio.Future:
        """Hold a world-changing action until the next tick, and hand back its eventual result.

        One order per character: typing a second one before the tick replaces the first, whose command
        gets SUPERSEDED back. Spamming a command therefore buys nothing but a change of mind.
        """
        _, previous = self._orders.pop(character, (None, None))
        if previous is not None and not previous.done():
            previous.set_result(SUPERSEDED)
        future = asyncio.get_running_loop().create_future()
        self._orders[character] = (action, future)
        return future

    async def tick(self):
        """Resolve everyone's orders, then let the world act. Same-tick orders resolve in random order."""
        orders, self._orders = self._orders, {}
        for action, future in random.sample(list(orders.values()), len(orders)):
            if future.done():  # the command that asked for it went away
                continue
            try:
                future.set_result(action())
            except Exception as exc:
                future.set_exception(exc)
        # One DM per player per tick, however many NPCs piled on: Discord rate-limits, players tilt.
        news: Dict[Actors.Actor, List[str]] = {}
        for event in self.world_adapter.world.tick():
            if event.target is not None:
                news.setdefault(event.target, []).append(event.text)
        for character, lines in news.items():
            await self._dm(character, "\n".join(lines))

    async def _dm(self, character: Actors.Actor, text: str):
        """Tell a player something that happened while they weren't looking. Best effort: DMs can be closed."""
        member_id = self.world_adapter.get_member_id(character)
        if member_id is None:
            return
        try:
            user = self.bot.get_user(member_id) or await self.bot.fetch_user(member_id)
            for chunk in _chunks(text):
                await user.send(chunk)
        except discord.HTTPException:  # closed DMs, blocked bot, deleted account
            LOG.info("Could not DM %s", member_id)

    async def _setup_hook(self):
        await self.bot.add_cog(self)
        self._start_job(self.tick_seconds, self.tick, "World tick")
        for seconds, action, name in self.jobs:
            self._start_job(seconds, action, name)
        synced = await self.bot.tree.sync()
        LOG.info(
            f"Synced {len(synced)} slash commands (global commands can take up to an hour to appear)."
        )

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.bot.user:
            LOG.error("Bot user is None. Something went wrong.")
            return
        LOG.info(f"Connected successfully: {self.bot.user.name}: <{self.bot.user.id}>")

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        """One handler for every game exception, instead of the same try/except in every command."""
        error = getattr(error, "original", error)
        if isinstance(error, NotRegisteredException):
            msg = "You haven't registered a character yet. Use `/register` to make one."
        elif isinstance(error, AlreadyRegisteredException):
            msg = "You already have a character."
        elif isinstance(error, NotSpawnedException):
            msg = "Your character hasn't spawned into the world yet."
        elif isinstance(error, NoWeaponEquippedException):
            msg = "You have no weapon equipped. Try `/inventory equip`."
        elif isinstance(error, RangedAttackException):
            msg = "You need a ranged weapon to attack at a distance."
        elif isinstance(error, InvalidSpaceException):
            msg = str(error) or "You can't go that way."
        elif isinstance(error, CombatException):
            msg = f"Attack failed: {error}"
        else:
            LOG.error(
                f"Unhandled error in /{interaction.command.name if interaction.command else '?'}",
                exc_info=error,
            )
            msg = "Something went wrong on the server."
        LOG.warning(f"{interaction.user.display_name}: {type(error).__name__}")
        await _send(interaction, msg, ephemeral=True)

    def _player(self, interaction: discord.Interaction) -> Actors.PlayerCharacter:
        return self.world_adapter.get_player(interaction.user.id)

    @app_commands.command()
    async def register(
        self, interaction: discord.Interaction, name: app_commands.Range[str, 1, 32]
    ):
        """*START HERE* Make a new character in the world"""
        LOG.info(
            f"/register called by {interaction.user.display_name}: <{interaction.user.id}>"
        )
        self.world_adapter.register_player(interaction.user.id, player_name=name)
        await _send(interaction, f"Welcome, {name}! Good luck out there, comrade!")

    @app_commands.command()
    @requires_character()
    async def equipment(self, interaction: discord.Interaction):
        """List all equipped items on character"""
        character = self._player(interaction)
        await _send(
            interaction, f"Equipment: \n" f"---------- \n" f"{character.equipment_set}"
        )

    @app_commands.command()
    @requires_character()
    async def look(self, interaction: discord.Interaction):
        """Describes your character's surroundings"""
        await interaction.response.defer()
        character = self._player(interaction)
        msg = f"Your coordinates are {character.location}. The terrain is {character.location.terrain.name}-y. "
        if self.world_adapter.is_town(character.location):
            msg += f"You are also in a town, {character.location.name}. "
        if self.world_adapter.is_wilds(character.location):
            msg += f"You are also in the wilds, {character.location.name}. "
        nearby_npcs = self.world_adapter.get_nearby_npcs(character)
        if nearby_npcs:
            msg += "There are some NPCs nearby: \n" + ", ".join(
                [str(npc) for npc in nearby_npcs]
            )
        nearby_players = self.world_adapter.get_nearby_players(character)
        if len(nearby_players) > 1:
            msg += "\nThere are also some Players nearby: \n" + ", ".join(
                [
                    player.name
                    for player in nearby_players
                    if player.name != character.name
                ]
            )
        screenshot_path = self.world_adapter.get_player_screenshot(character)
        files = [discord.File(screenshot_path)] if screenshot_path else []
        await interaction.followup.send(msg, files=files)

    @app_commands.command()
    @app_commands.choices(direction=DIRECTION_CHOICES)
    @requires_character()
    async def move(
        self, interaction: discord.Interaction, direction: app_commands.Choice[str]
    ):
        """Move your character one space in the given direction, resolved on the next tick"""
        await interaction.response.defer()
        character = self._player(interaction)
        results = await self.order(
            character,
            lambda: self.world_adapter.move_player(
                character, DIRECTION_VECTORS[direction.value]
            ),
        )
        if results is SUPERSEDED:
            await interaction.followup.send("You change your mind before setting off.")
            return
        results = cast(List[PlayerActionResponse], results)
        msg = ""
        # If any Events happen, let the PC know step-by-step
        for r in results:
            if r.text:
                msg += r.text + "\n"
            if not r.is_successful:
                break

        character.last_time_moved = time.time()

        if not msg:
            msg = f"You move {direction.name}."
        for chunk in _chunks(msg):
            await interaction.followup.send(chunk)

    @app_commands.command()
    @app_commands.choices(direction=DIRECTION_CHOICES)
    @requires_character()
    async def attack(
        self, interaction: discord.Interaction, direction: app_commands.Choice[str]
    ):
        """Attack, resolved on the next tick; give a direction for a ranged attack"""
        await interaction.response.defer()
        character = self._player(interaction)
        response = await self.order(
            character,
            lambda: self.world_adapter.attack(
                character, DIRECTION_VECTORS[direction.value]
            ),
        )
        if response is SUPERSEDED:
            await interaction.followup.send("You hold your fire.")
            return
        response = cast(PlayerActionResponse, response)
        target_name = response.target.name if response.target else "nobody"
        await _send(
            interaction,
            f"{character.name} deals {response.damage} to {target_name}.\n"
            f"\n"
            f" {response.text}",
        )

    @inventory.command(name="list")
    @requires_character()
    async def inventory_list(self, interaction: discord.Interaction):
        """Lists all the items in your inventory with ID #"""
        character = self._player(interaction)
        msg = f"{character.name}'s inventory:\n"
        if not character.inventory:
            msg += "\t(Empty)"
        else:
            for index, item in enumerate(character.inventory):
                msg += f"\t#{index}\t{item}\n"
        await _send(interaction, msg)

    @inventory.command()
    @requires_character()
    async def equip(self, interaction: discord.Interaction, index: int):
        """Equip the item at the given index"""
        character = self._player(interaction)
        try:
            item: Equipment = character.inventory[index]
        except IndexError:
            await _send(interaction, f"Given index {index} is invalid.", ephemeral=True)
            return
        character.equip(item)
        await _send(interaction, f"Equipped {item.name}.")

    @inventory.command()
    @requires_character()
    async def unequip(self, interaction: discord.Interaction, index: int):
        """Unequip the item at the given index"""
        character = self._player(interaction)
        try:
            item: Equipment = character.inventory[index]
        except IndexError:
            await _send(interaction, f"Given index {index} is invalid.", ephemeral=True)
            return
        character.unequip(item)
        await _send(interaction, f"Unequipped {item.name}.")

    @town.command(name="status")
    @requires_character()
    async def town_status(self, interaction: discord.Interaction):
        """Check if you're in a town."""
        character = self._player(interaction)
        if self.world_adapter.is_town(character.location):
            await _send(interaction, f"You're currently in {character.location.name}.")
        else:
            await _send(interaction, "You're currently not in a town...")

    @town.command()
    @requires_character()
    @requires_space(GameSpace.Town)
    async def inn(self, interaction: discord.Interaction):
        """Rest to restore hitpoints."""
        character = self._player(interaction)
        resp: PlayerActionResponse = _town_of(character).inn_event(character)
        await _send(interaction, resp.text)

    @town.command()
    @requires_character()
    @requires_space(GameSpace.Town)
    async def recruit(self, interaction: discord.Interaction):
        """Change your player class to the one offered by the town."""
        character = self._player(interaction)
        resp: PlayerActionResponse = _town_of(character).recruit(character)
        await _send(interaction, resp.text)

    @store.command(name="list")
    @requires_character()
    @requires_space(GameSpace.Town)
    async def store_list(self, interaction: discord.Interaction):
        """List what this town's store has for sale"""
        character = self._player(interaction)
        store = _town_of(character).store
        if store is None:
            await _send(interaction, NO_STORE)
        elif not store.inventory:
            await _send(
                interaction,
                "There are no items in the store at the moment. Please try again later.",
            )
        else:
            msg = "Index\tName\tPrice\tCount\n"
            for idx, item in enumerate(store.inventory):
                msg += f"#{idx}\t{item.name}\t${store.get_price(item)}\t{store.inventory.count(item)}\n"
            await _send(interaction, msg)

    @store.command()
    @requires_character()
    @requires_space(GameSpace.Town)
    async def buy(self, interaction: discord.Interaction, index: int):
        """Buy the store item at the given index"""
        character = self._player(interaction)
        store = _town_of(character).store
        if store is None:
            await _send(interaction, NO_STORE)
        elif store.sell_item(index, character):
            await _send(interaction, "Item successfully bought.")
        else:
            await _send(interaction, "Not enough money.")

    @store.command()
    @requires_character()
    @requires_space(GameSpace.Town)
    async def sell(self, interaction: discord.Interaction, index: int):
        """Sell the inventory item at the given index"""
        character = self._player(interaction)
        store = _town_of(character).store
        if store is None:
            await _send(interaction, NO_STORE)
            return
        try:
            item: Equipment = character.inventory[index]
        except IndexError:
            await _send(interaction, f"Invalid index {index} given.", ephemeral=True)
            return
        price = store.buy_item(item, character)
        await _send(interaction, f"Successfully sold {item.name} for ${price}.")
