from __future__ import annotations

import asyncio
import datetime
import inspect
import logging
import random
import time
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple, cast

import discord
from discord import app_commands
from discord.ext import commands, tasks

import Discordia.GameLogic.Actors as Actors
from ConfigParser import DISCORD_PREFIX
from Discordia.GameLogic import Events, GameSpace
from Discordia.GameLogic.GameSpace import PlayerActionResponse, DIRECTION_VECTORS
from Discordia.GameLogic.Items import Equipment
from Discordia.Interface.WorldAdapter import (
    WorldAdapter,
    NotSpawnedException,
    InvalidSpaceException,
    DIRECTION_NAMES,
    SUPERSEDED,
    attack_text,
    choose_text,
    error_text,
    move_text,
)

LOG = logging.getLogger("Discordia.Interface.DiscordServer")

DIRECTION_CHOICES = [
    app_commands.Choice(name=name, value=key) for key, name in DIRECTION_NAMES.items()
]

ENCOUNTER_CHOICES = [
    app_commands.Choice(name=choice, value=choice)
    for choice in Events.EncounterEvent.CHOICES
]

NO_STORE = "There's no store here. Find a town that has one."
# What the bot asks for when it's added to a server: enough to post the welcome and the daily digest.
# Commands answer through their interaction, which needs no channel permissions.
INVITE_PERMISSIONS = discord.Permissions(view_channel=True, send_messages=True)
WELCOME = (
    "Discordia is here: a world of towns and wilds, played with slash commands. "
    "Start with `/register`. Admins: `/settings` picks the channels it plays in, and where the daily digest goes."
)


def _character(interaction: discord.Interaction) -> Actors.PlayerCharacter:
    """The character behind an interaction. Checks only get the interaction, so dig the cog out of the command."""
    cog = getattr(interaction.command, "binding", None)
    assert isinstance(
        cog, DiscordInterface
    ), "check used outside the DiscordInterface cog"
    return cog.world_adapter.get_player(
        interaction.user.id
    )  # raises NotRegisteredException


class GameCheckFailure(app_commands.CheckFailure):
    """A game exception a check raised, as `original`, like CommandInvokeError has it."""

    def __init__(self, original: Exception):
        super().__init__(str(original))
        self.original = original


class WrongChannel(app_commands.CheckFailure):
    """A command used outside the channels its server's admins picked. The message says where to go."""


def _game_check(predicate: Callable[[discord.Interaction], Any]):
    """app_commands.check for a predicate that raises game exceptions. The command tree only handles
    AppCommandErrors: anything else escapes it, and the player gets "The application did not respond"
    instead of why."""

    async def wrapped(interaction: discord.Interaction) -> bool:
        try:
            return await predicate(interaction)
        except app_commands.AppCommandError:
            raise
        except Exception as exc:
            raise GameCheckFailure(exc) from exc

    return app_commands.check(wrapped)


def requires_character():
    """Prerequisite check: caller has a registered character that's spawned into the world."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if not _character(interaction).registered:
            raise NotSpawnedException
        return True

    return _game_check(predicate)


def requires_space(space_type: type[GameSpace.Space]):
    """Prerequisite check: caller's character is in a Space of the given type."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if not isinstance(_character(interaction).location, space_type):
            raise InvalidSpaceException(
                f"You need to be in a {space_type.__name__.lower()} to do that."
            )
        return True

    return _game_check(predicate)


def _town_of(character: Actors.PlayerCharacter) -> GameSpace.Town:
    """The town the character is standing in. Only valid under @requires_space(GameSpace.Town)."""
    return cast(GameSpace.Town, character.location)


def _stock_listing(store: GameSpace.Store) -> str:
    """What's for sale and what it costs, for a town store or a trader's blanket alike."""
    msg = "Index\tName\tPrice\tCount\n"
    for idx, item in enumerate(store.inventory):
        msg += f"#{idx}\t{item.name}\t${store.get_price(item)}\t{store.inventory.count(item)}\n"
    return msg


def _chunks(text: str, size: int = 2000) -> Iterator[str]:
    """Discord rejects any message over 2000 characters."""
    for start in range(0, len(text), size):
        yield text[start : start + size]


async def _send(interaction: discord.Interaction, content: str, **kwargs):
    """Reply to an interaction whether or not it's already been responded to/deferred.

    Best effort, like _dm: an interaction dies 3s after Discord sends it, and with it over a bot
    restart. Losing the reply must never take the world change down with it.
    """
    try:
        if interaction.response.is_done():
            await interaction.followup.send(content, **kwargs)
        else:
            await interaction.response.send_message(content, **kwargs)
    except discord.HTTPException as exc:
        LOG.info("Could not reply to /%s: %s", interaction.command, exc)


async def _defer(interaction: discord.Interaction):
    """Buy the full 15 minutes for a slow command. Best effort for the same reason as _send:
    a dead interaction must not abort the order the command was about to queue."""
    try:
        await interaction.response.defer()
    except discord.HTTPException as exc:
        LOG.info("Could not defer /%s: %s", interaction.command, exc)


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
    trade = app_commands.Group(
        name="trade", description="Deal with a trader you met on the road"
    )
    stash = app_commands.Group(
        name="stash", description="Bank items and money in town, safe from whatever kills you out there"
    )

    def __init__(
        self,
        world_adapter: WorldAdapter,
        jobs: Sequence[Tuple[float | datetime.time, Callable[[], None], str]] = (),
        tick_seconds: float = 5.0,
        web_url: str | None = None,
    ):
        """`jobs` are (every, action, name) triples run alongside the commands: every so many seconds, or
        daily at a datetime.time.
        `web_url` is where players reach the web map, or None if it isn't running."""
        self.bot: commands.Bot = commands.Bot(
            command_prefix=str(DISCORD_PREFIX), intents=discord.Intents.default()
        )
        # ponytail: attribute override instead of a Bot subclass; subclass it if the bot needs more hooks
        self.bot.setup_hook = self._setup_hook
        self.world_adapter: WorldAdapter = world_adapter
        self.jobs = jobs
        self.tick_seconds = tick_seconds
        self.web_url = web_url.rstrip("/") if web_url else None
        self._job_loops: List[tasks.Loop] = (
            []
        )  # kept alive; a Loop nobody holds gets collected
        self._orders: Dict[
            Actors.PlayerCharacter, Tuple[Callable[[], Any], asyncio.Future]
        ] = {}

    def _start_job(self, every: float | datetime.time, action: Callable[[], Any], name: str):
        """Run `action` every `every` seconds, or daily at that time, on the bot's event loop: same thread as
        the commands, so no locking.

        Each job blocks command handling while it runs, which is why they're all short. A job may be
        a coroutine function; the tick is one, because it sends DMs.
        """

        loop = tasks.loop(time=every) if isinstance(every, datetime.time) else tasks.loop(seconds=every)

        @loop
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
        self.world_adapter.world.stats.active_players.update(orders)
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
            text = "\n".join(lines)
            if isinstance(character, Actors.PlayerCharacter):
                self.world_adapter.add_news(character, text)
            await self._dm(character, text)

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

    async def post_digest(self, text: str):
        """Post the daily digest in every server that picked a channel for it. Best effort, like _dm."""
        for guild_id, settings in list(self.world_adapter.guild_settings.items()):
            if settings.digest_channel is None:
                continue
            channel = self.bot.get_channel(settings.digest_channel)
            if channel is None:  # deleted, or the bot can't see it any more
                LOG.info("No digest channel %s in server %s", settings.digest_channel, guild_id)
                continue
            try:
                for chunk in _chunks(text):
                    await channel.send(chunk)  # type: ignore[union-attr]  # the website only offers text channels
            except discord.HTTPException:  # not allowed to post there
                LOG.info("Could not post the digest in %s", settings.digest_channel)

    def order_threadsafe(
        self,
        character: Actors.PlayerCharacter,
        action: Callable[[], Any],
        timeout: float = 30,
    ) -> Any:
        """order() for a caller on another thread (the web map): queue it on the bot loop, block for the
        tick. Raises whatever the action raised, or TimeoutError if no tick comes."""

        async def place():
            return await self.order(character, action)

        return asyncio.run_coroutine_threadsafe(place(), self._loop).result(timeout)

    def guild_for_admin(
        self, member_id: int, guild_id: int, timeout: float = 10
    ) -> Optional[Tuple[str, List[Tuple[int, str]]]]:
        """For the website's settings page, from its thread: (server name, [(channel id, name)]) if the
        member may manage that server, else None. Asks Discord every time rather than trusting a cache,
        so taking someone's Manage Server away locks them out at once."""

        async def look():
            guild = self.bot.get_guild(guild_id)
            if guild is None:  # not a server the bot is in
                return None
            try:
                member = await guild.fetch_member(member_id)
            except discord.HTTPException:  # not in that server
                return None
            if not member.guild_permissions.manage_guild:
                return None
            return guild.name, [(channel.id, channel.name) for channel in guild.text_channels]

        return asyncio.run_coroutine_threadsafe(look(), self._loop).result(timeout)

    async def _setup_hook(self):
        self._loop = asyncio.get_running_loop()
        self.world_adapter.place_order = self.order_threadsafe
        self.world_adapter.guild_for_admin = self.guild_for_admin
        self.world_adapter.invite_url = discord.utils.oauth_url(
            cast(int, self.bot.application_id),  # login fetched it before this hook
            permissions=INVITE_PERMISSIONS,
            scopes=("bot", "applications.commands"),
        )
        await self.bot.add_cog(self)
        self._start_job(self.tick_seconds, self.tick, "World tick")
        for every, action, name in self.jobs:
            self._start_job(every, action, name)
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

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        """Say hello and where to start. Best effort, like _dm: the server may have no system channel, or
        not let the bot post in it."""
        LOG.info("Joined server %s <%s>", guild.name, guild.id)
        if guild.system_channel is None:
            return
        try:
            await guild.system_channel.send(WELCOME)
        except discord.HTTPException:
            LOG.info("Could not welcome server %s", guild.id)

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        """One handler for every game exception, instead of the same try/except in every command."""
        if isinstance(error, WrongChannel):
            await _send(interaction, str(error), ephemeral=True)
            return
        error = getattr(error, "original", error)
        msg = error_text(error)
        if msg is None:
            LOG.error(
                f"Unhandled error in /{interaction.command.name if interaction.command else '?'}",
                exc_info=error,
            )
            msg = "Something went wrong on the server."
        LOG.warning(f"{interaction.user.display_name}: {type(error).__name__}")
        await _send(interaction, msg, ephemeral=True)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Commands only work in the channels a server's admins picked on the website: all of them if
        they picked none. /settings works anywhere, so nobody locks themselves out."""
        settings = self.world_adapter.guild_settings.get(interaction.guild_id or 0)
        if settings is None or not settings.channels or getattr(interaction.command, "name", None) == "settings":
            return True
        # A thread counts as the channel it hangs off.
        if {interaction.channel_id, getattr(interaction.channel, "parent_id", None)} & set(settings.channels):
            return True
        raise WrongChannel(
            "Discordia doesn't play in this channel. Try " + ", ".join(f"<#{c}>" for c in settings.channels) + "."
        )

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
    async def weblogin(self, interaction: discord.Interaction):
        """Get a one-time link that logs you in to the web map"""
        if self.web_url is None:
            await _send(
                interaction, "The web map isn't running on this server.", ephemeral=True
            )
            return
        token = self.world_adapter.web_logins.new_link_token(interaction.user.id)
        # Ephemeral: only you see it. <> stops Discord fetching it for a preview.
        await _send(
            interaction,
            f"Your map login link. It works once, for 10 minutes; don't share it:\n"
            f"<{self.web_url}/login?t={token}>",
            ephemeral=True,
        )

    @app_commands.command()
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)  # hides it from everyone else in the command list
    async def settings(self, interaction: discord.Interaction):
        """Choose which channels Discordia plays in on this server (admins)"""
        if self.web_url is None:
            await _send(interaction, "The website isn't running on this server.", ephemeral=True)
            return
        # Server admins can hand the command to anyone; the website asks Discord again either way.
        if not interaction.permissions.manage_guild:
            await _send(interaction, "You need Manage Server to change this server's settings.", ephemeral=True)
            return
        token = self.world_adapter.web_logins.new_link_token(interaction.user.id)
        await _send(
            interaction,
            f"This server's Discordia settings. The link works once, for 10 minutes; don't share it:\n"
            f"<{self.web_url}/login?t={token}&next=/admin/{interaction.guild_id}>",
            ephemeral=True,
        )

    @app_commands.command()
    @requires_character()
    async def equipment(self, interaction: discord.Interaction):
        """List all equipped items on character"""
        character = self._player(interaction)
        await _send(
            interaction,
            f"{character.name}, level {character.level} {character.player_class} "
            f"({character.experience_to_next_level} XP to go), ${character.currency}\n"
            f"HP: {character.hit_points}/{character.hit_points_max}\n"
            f"Equipment: \n"
            f"---------- \n"
            f"{character.equipment_set}",
        )

    @app_commands.command()
    @requires_character()
    async def look(self, interaction: discord.Interaction):
        """Describes your character's surroundings"""
        await _defer(interaction)
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
        await _send(interaction, msg, files=files)

    @app_commands.command()
    @app_commands.choices(direction=DIRECTION_CHOICES)
    @requires_character()
    async def move(
        self, interaction: discord.Interaction, direction: app_commands.Choice[str]
    ):
        """Move your character one space in the given direction, resolved on the next tick"""
        await _defer(interaction)
        character = self._player(interaction)
        results = await self.order(
            character,
            lambda: self.world_adapter.move_player(
                character, DIRECTION_VECTORS[direction.value]
            ),
        )
        if results is SUPERSEDED:
            await _send(interaction, "You change your mind before setting off.")
            return
        msg = move_text(cast(List[PlayerActionResponse], results), direction.name)
        character.last_time_moved = time.time()
        for chunk in _chunks(msg):
            await _send(interaction, chunk)

    @app_commands.command()
    @app_commands.choices(direction=DIRECTION_CHOICES)
    @requires_character()
    async def attack(
        self, interaction: discord.Interaction, direction: app_commands.Choice[str]
    ):
        """Attack, resolved on the next tick: your square first, then that way (melee reaches one square)"""
        await _defer(interaction)
        character = self._player(interaction)
        response = await self.order(
            character,
            lambda: self.world_adapter.attack(
                character, DIRECTION_VECTORS[direction.value]
            ),
        )
        if response is SUPERSEDED:
            await _send(interaction, "You hold your fire.")
            return
        await _send(
            interaction, attack_text(character, cast(PlayerActionResponse, response))
        )

    @app_commands.command()
    @app_commands.choices(choice=ENCOUNTER_CHOICES)
    @requires_character()
    async def choose(
        self, interaction: discord.Interaction, choice: app_commands.Choice[str]
    ):
        """Decide what to do about whoever is waiting on the road, resolved on the next tick"""
        await _defer(interaction)
        character = self._player(interaction)
        results = await self.order(
            character,
            lambda: self.world_adapter.resolve_encounter(character, choice.value),
        )
        if results is SUPERSEDED:
            await _send(interaction, "You think better of it.")
            return
        for chunk in _chunks(choose_text(cast(List[PlayerActionResponse], results))):
            await _send(interaction, chunk)

    @trade.command(name="list")
    @requires_character()
    async def trade_list(self, interaction: discord.Interaction):
        """See what the trader in front of you is selling"""
        store = self.world_adapter.merchant_store(self._player(interaction))
        await _send(interaction, _stock_listing(store))

    @trade.command(name="buy")
    @requires_character()
    async def trade_buy(self, interaction: discord.Interaction, index: int):
        """Buy the trader's item at the given index"""
        character = self._player(interaction)
        store = self.world_adapter.merchant_store(character)
        if store.sell_item(index, character):
            await _send(interaction, "The trader takes your money and hands it over.")
        else:
            await _send(
                interaction,
                "You can't afford that, or there's nothing at that index.",
                ephemeral=True,
            )

    @stash.command(name="list")
    @requires_character()
    @requires_space(GameSpace.Town)
    async def stash_list(self, interaction: discord.Interaction):
        """See what you've banked"""
        character = self._player(interaction)
        msg = f"{character.name}'s stash: ${character.stash_currency}\n"
        msg += "".join(f"\t#{index}\t{item}\n" for index, item in enumerate(character.stash)) or "\t(No items)"
        await _send(interaction, msg)

    @stash.command(name="put")
    @requires_character()
    @requires_space(GameSpace.Town)
    async def stash_put(
        self, interaction: discord.Interaction, item: Optional[int] = None, money: int = 0
    ):
        """Bank the inventory item at the given index, and/or some money"""
        await self._stash_move(interaction, self._player(interaction).stash_put, item, money)

    @stash.command(name="take")
    @requires_character()
    @requires_space(GameSpace.Town)
    async def stash_take(
        self, interaction: discord.Interaction, item: Optional[int] = None, money: int = 0
    ):
        """Take the stashed item at the given index, and/or some money, to carry"""
        await self._stash_move(interaction, self._player(interaction).stash_take, item, money)

    async def _stash_move(self, interaction: discord.Interaction, move, item, money):
        try:
            moved = move(item, money)
        except ValueError as exc:
            await _send(interaction, str(exc), ephemeral=True)
            return
        await _send(interaction, f"Moved {moved}." if moved else "Nothing to move.", ephemeral=not moved)

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
        msg += f"\nPouch (kept if you die): {character.pouch or '(empty)'}"
        await _send(interaction, msg)

    @inventory.command()
    @requires_character()
    async def pouch(self, interaction: discord.Interaction, index: Optional[int] = None):
        """Keep the item at the given index safe from death (one at a time); no index empties the pouch"""
        try:
            moved = self._player(interaction).pouch_swap(index)
        except ValueError as exc:
            await _send(interaction, str(exc), ephemeral=True)
            return
        await _send(interaction, f"Moved {moved}." if moved else "Your pouch is already empty.", ephemeral=not moved)

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
        try:
            character.equip(item)
        except ValueError:  # no slot takes it, like a box of rounds: those load themselves
            await _send(interaction, f"{item.name} isn't something you wear or hold.", ephemeral=True)
            return
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
        try:
            character.unequip(item)
        except ValueError:  # no slot takes it, like a box of rounds: those load themselves
            await _send(interaction, f"{item.name} isn't something you wear or hold.", ephemeral=True)
            return
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
            await _send(interaction, _stock_listing(store))

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
