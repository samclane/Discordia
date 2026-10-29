# Note: NEVER EVER import Discord here, this defeats the whole point of an ADAPTER
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, Tuple, List, Iterator, Optional

from Discordia.GameLogic import Actors, Events
from Discordia.GameLogic.GameSpace import (
    World,
    Space,
    Store,
    Town,
    Wilds,
    Direction,
    PlayerActionResponse,
)
from Discordia.Interface.WebLogins import WebLogins


class NullWorldException(Exception):
    pass


class AlreadyRegisteredException(Exception):
    pass


class NotRegisteredException(Exception):
    pass


class NotSpawnedException(Exception):
    """Registered, but the character isn't standing anywhere in the world."""

    pass


class InvalidSpaceException(Exception):
    pass


class ItemRequirementException(Exception):
    pass


class NoWeaponEquippedException(ItemRequirementException):
    pass


class CombatException(Exception):
    pass


class NoEncounterException(Exception):
    """Nothing is waiting on a decision right now."""

    pass


class NoMerchantException(Exception):
    """Nobody is here to trade with."""

    pass


def error_text(error: Exception) -> Optional[str]:
    """What to tell a player whose command raised `error`, or None if it's a bug rather than a rule."""
    if isinstance(error, NotRegisteredException):
        return "You haven't registered a character yet. Use `/register` to make one."
    if isinstance(error, AlreadyRegisteredException):
        return "You already have a character."
    if isinstance(error, NotSpawnedException):
        return "Your character hasn't spawned into the world yet."
    if isinstance(error, NoWeaponEquippedException):
        return "You have no weapon equipped. Try `/inventory equip`."
    if isinstance(error, InvalidSpaceException):
        return str(error) or "You can't go that way."
    if isinstance(error, CombatException):
        return f"Attack failed: {error}"
    if isinstance(error, NoEncounterException):
        return "Nobody is waiting on you to decide anything."
    if isinstance(error, NoMerchantException):
        return "There is nobody here to trade with."
    return None


# What an order's results say back, from Discord or the web alike.
def move_text(results: List[PlayerActionResponse], direction_name: str) -> str:
    """Each step's events in turn, up to the first that stopped you."""
    lines = []
    for r in results:
        if r.text:
            lines.append(r.text)
        if not r.is_successful:
            break
    return "\n".join(lines) or f"You move {direction_name}."


def attack_text(character: Actors.PlayerCharacter, response: PlayerActionResponse) -> str:
    target_name = response.target.name if response.target else "nobody"
    return f"{character.name} deals {response.damage} to {target_name}.\n\n {response.text}"


def choose_text(results: List[PlayerActionResponse]) -> str:
    return "\n".join(r.text for r in results if r.text)


# What an order resolves to when the player replaces it before the tick.
SUPERSEDED = object()

DIRECTION_NAMES = {
    "n": "north",
    "s": "south",
    "e": "east",
    "w": "west",
    "ne": "northeast",
    "se": "southeast",
    "sw": "southwest",
    "nw": "northwest",
}

NEWS_KEPT = 20  # world events remembered per player, for the website


@dataclass
class GuildSettings:
    """One Discord server's settings, set by its admins on the website. Saved as JSON: a new setting is a
    new field with a default, and old saves load without a migration."""

    channels: List[int] = field(default_factory=list)  # where commands work; empty means everywhere
    digest_channel: Optional[int] = None  # where the daily digest goes; None means it doesn't


class WorldAdapter:
    """
    Provides a public API for the game world for interfaces (like DiscordInterface) to connect to.
    """

    def __init__(self, gameworld: World):
        self.world: World = gameworld
        self._renderer = None
        self._discord_player_map: Dict[int, Actors.PlayerCharacter] = {}
        self.web_logins = WebLogins()  # here because the bot and the web map both hold the adapter
        # Set by the running bot: queue an order for the next tick from another thread, and block for its
        # result. None when nothing ticks the world (tests, a bare web server).
        self.place_order: Optional[Callable[[Actors.PlayerCharacter, Callable[[], Any]], Any]] = None
        # Discord server id -> its settings. Servers nobody has configured aren't in it.
        self.guild_settings: Dict[int, GuildSettings] = {}
        # Also set by the running bot, for the website's settings page: (member id, server id) ->
        # (server name, [(channel id, channel name)]) if that member may manage that server, else None.
        self.guild_for_admin: Optional[Callable[[int, int], Optional[Tuple[str, List[Tuple[int, str]]]]]] = None
        # And Discord's "add this bot to a server" link, for the website's /invite.
        self.invite_url: Optional[str] = None
        # Seconds per World.tick, set by the running bot; what turns per-tick income into per-hour.
        self.tick_seconds: float = 5.0
        # ponytail: in memory, so a restart forgets it. Save it if anyone misses it.
        self._news: Dict[Actors.PlayerCharacter, Deque[Tuple[float, str]]] = {}

    def add_news(self, character: Actors.PlayerCharacter, text: str):
        """Remember something the world did to a player while they weren't looking (what the bot DMs)."""
        self._news.setdefault(character, deque(maxlen=NEWS_KEPT)).append((time.time(), text))

    def news(self, character: Actors.PlayerCharacter) -> List[Tuple[float, str]]:
        """(unix time, text) pairs, oldest first. A snapshot: safe to call off the bot loop."""
        return list(self._news.get(character, ()))

    def income_per_hour(self, character: Actors.PlayerCharacter) -> int:
        """What the hideout pays into the stash an hour, at this server's tick."""
        ticks_an_hour = 3600 / self.tick_seconds
        return int(Actors.HIDEOUT_INCOME * character.hideout_level * ticks_an_hour / Actors.HIDEOUT_PAY_TICKS)

    def hideout_text(self, character: Actors.PlayerCharacter) -> str:
        """The idle side in a sentence, from Discord or the web alike."""
        money, salvage = character.hideout_price
        price = f"{salvage} salvage" if salvage else f"${money:,}"
        if not character.hideout_level:
            return f"No hideout yet: `/hideout build` in any town, for {price}, earns while you're away."
        return (
            f"Hideout level {character.hideout_level}: ${self.income_per_hour(character):,} an hour into your stash,"
            f" which is worth ${character.stash_value:,}. The next level costs {price}."
        )

    @property
    def width(self):
        return self.world.width

    @property
    def height(self):
        return self.world.height

    def add_renderer(self, window):
        self._renderer = window

    def register_player(self, member_id: int, player_name: str):
        if not self.world:
            raise NullWorldException(
                "Tried to register PlayerCharacter to empty world."
            )
        if self.is_registered(member_id):
            raise AlreadyRegisteredException("Member is already registered!")

        # Forcibly strip evil characters
        player_name = "".join(
            [c for c in player_name if c not in ["<", ">", "\\", "/"]]
        )

        # Create new PlayerCharacter and add him into the existing world
        new_player = Actors.PlayerCharacter(parent_world=self.world, name=player_name)
        self._discord_player_map[member_id] = new_player
        self.world.add_actor(new_player, self.world.starting_town)

    def is_registered(self, member_id: int) -> bool:
        return member_id in self._discord_player_map.keys()

    def get_player(self, member_id) -> Actors.PlayerCharacter:
        if not self.is_registered(member_id):
            raise NotRegisteredException

        # Sanity check
        assert member_id in self._discord_player_map.keys()

        return self._discord_player_map[member_id]

    def get_member_id(self, character: Actors.Actor) -> int | None:
        """Who plays this character, or None if it isn't a registered player's."""
        return next(
            (
                member_id
                for member_id, player in self._discord_player_map.items()
                if player is character
            ),
            None,
        )

    def is_town(self, location: Space) -> bool:
        return isinstance(self.world.space_at(location.x, location.y), Town)

    def is_wilds(self, location: Space) -> bool:
        return isinstance(self.world.space_at(location.x, location.y), Wilds)

    def move_player(
        self, character: Actors.PlayerCharacter, direction: Tuple[int, int]
    ) -> List[PlayerActionResponse]:
        responses = character.attempt_move(direction)
        if len(responses) == 1 and responses[0].failed:
            raise InvalidSpaceException()

        return responses

    def get_nearby_npcs(self, character: Actors.PlayerCharacter) -> List[Actors.NPC]:
        location: Space = character.location
        fov: int = character.fov
        npcs: List[Actors.NPC] = self.world.get_npcs_in_region(
            self.world.get_adjacent_spaces(location, fov)
        )
        return npcs

    def get_nearby_players(
        self, character: Actors.PlayerCharacter
    ) -> List[Actors.PlayerCharacter]:
        location: Space = character.location
        fov: int = character.fov
        players: List[Actors.PlayerCharacter] = self.world.get_players_in_region(
            self.world.get_adjacent_spaces(location, fov)
        )
        return players

    def attack(
        self, character: Actors.PlayerCharacter, direction: Direction
    ) -> PlayerActionResponse:
        if not character.has_weapon_equipped:
            raise NoWeaponEquippedException
        response: PlayerActionResponse = self.world.attack(character, direction)
        if not response.is_successful:
            raise CombatException(response.text)
        return response

    def resolve_encounter(
        self, character: Actors.PlayerCharacter, choice: str
    ) -> List[PlayerActionResponse]:
        encounter = character.pending_event
        if not isinstance(encounter, Events.EncounterEvent):
            raise NoEncounterException()
        return encounter.resolve(character, choice)

    def merchant_store(self, character: Actors.PlayerCharacter) -> Store:
        """The blanket the trader in front of you has laid out, if one is."""
        merchant = character.pending_event
        if not isinstance(merchant, Events.MerchantEvent):
            raise NoMerchantException()
        return merchant.store

    def iter_spaces(self) -> Iterator[Space]:
        """Every square generated so far. The rest of the map doesn't exist until something walks there."""
        for cx, cy in self.world.loaded_chunks():
            for row in self.world.loaded_chunk(cx, cy) or []:
                yield from row

    def iter_players(self) -> Iterator[Actors.PlayerCharacter]:
        for player in self._discord_player_map.values():
            yield player

    def iter_registered(self) -> Iterator[Tuple[int, Actors.PlayerCharacter]]:
        yield from self._discord_player_map.items()

    def get_player_screenshot(self, character: Actors.PlayerCharacter) -> str:
        if self._renderer is not None:
            path = self._renderer.get_player_view(character)
            return path
        return "<No Renderer>"
