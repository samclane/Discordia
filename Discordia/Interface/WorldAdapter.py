# Note: NEVER EVER import Discord here, this defeats the whole point of an ADAPTER
from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Deque, Dict, Tuple, List, Iterator, Optional

from Discordia.GameLogic import Actors, Events
from Discordia.GameLogic.GameSpace import (
    World,
    Space,
    Store,
    Town,
    Wilds,
    Direction,
    PlayerActionResponse,
    bearing,
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
    if response.target is None:  # nobody hit, and nothing refused: someone else got there first
        return response.text
    return f"{character.name} deals {response.damage} to {response.target.name}.\n\n {response.text}"


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
SAMPLES_KEPT = 17280  # ticks remembered for the owner's dashboard: a day of them at 5 seconds


@dataclass
class GuildSettings:
    """One Discord server's settings, set by its admins on the website. Saved as JSON: a new setting is a
    new field with a default, and old saves load without a migration."""

    channels: List[int] = field(default_factory=list)  # where commands work; empty means everywhere
    digest_channel: Optional[int] = None  # where the daily digest goes; None means it doesn't
    announce_channel: Optional[int] = None  # where its players' deaths and hauls are posted; None means nowhere


PROC_STATUS = "/proc/self/status"


def memory_mb(path: str = PROC_STATUS) -> float | None:
    """The process's resident memory in MB (VmRSS), or None off Linux: the server runs on Linux."""
    try:
        with open(path) as status:
            kb = next(line.split()[1] for line in status if line.startswith("VmRSS:"))
    except (OSError, StopIteration):
        return None
    return round(int(kb) / 1024, 1)


class WorldAdapter:
    """
    Provides a public API for the game world for interfaces (like DiscordInterface) to connect to.
    """

    def __init__(self, gameworld: World):
        self.world: World = gameworld
        self._renderer = None
        self._discord_player_map: Dict[int, Actors.PlayerCharacter] = {}
        self.web_logins = WebLogins()  # here because the bot and the web map both hold the adapter
        # Set by the running bot: queue an order for the next tick, and await its result. None when nothing
        # ticks the world (tests, a bare web server).
        self.place_order: Optional[Callable[[Actors.PlayerCharacter, Callable[[], Any]], Awaitable[Any]]] = None
        # Discord server id -> its settings. Servers nobody has configured aren't in it.
        self.guild_settings: Dict[int, GuildSettings] = {}
        # Also set by the running bot, for the website's settings page: (member id, server id) ->
        # (server name, [(channel id, channel name, bot may post)]) if that member may manage that server, else None.
        self.guild_for_admin: Optional[Callable[[int, int], Awaitable[Optional[Tuple[str, List[Tuple[int, str, bool]]]]]]] = None
        # And Discord's "add this bot to a server" link, for the website's /invite.
        self.invite_url: Optional[str] = None
        # And whether a member owns the bot, for the website's dashboard (/admin).
        self.is_owner: Optional[Callable[[int], Awaitable[bool]]] = None
        # What each tick did, for that dashboard. Appended on the bot loop, read off it with samples().
        # ponytail: in memory, like _news: a restart starts the charts over.
        self._samples: Deque[Dict[str, float]] = deque(maxlen=SAMPLES_KEPT)
        self.started: float = time.time()
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

    def record_tick(self, **measures: float):
        """One row of the dashboard: what the bot measured this tick, and how big the world is after it."""
        world = self.world
        self._samples.append(
            {
                "at": round(time.time(), 1),
                "tick": world.ticks,
                "players": len(world.players),
                "npcs": len(world.npcs),
                "chunks": len(world.loaded_chunks()),
                "memory_mb": memory_mb(),  # with chunks: when it's time to evict some (ROADMAP)
                **measures,
            }
        )

    def samples(self, since: int = -1) -> List[Dict[str, float]]:
        """The rows after tick `since`, oldest first. A snapshot: safe to call off the bot loop."""
        return [row for row in list(self._samples) if row["tick"] > since]

    def income_per_hour(self, character: Actors.PlayerCharacter) -> int:
        """What the hideout pays into the stash an hour, at this server's tick."""
        ticks_an_hour = 3600 / self.tick_seconds
        return int(character.hideout_income * ticks_an_hour / Actors.HIDEOUT_PAY_TICKS)

    def work(self, character: Actors.PlayerCharacter) -> str:
        """Odd jobs for one shift in the town `character` stands in: World.advance pays it until it ends or they move."""
        character.work_until = self.world.ticks + Actors.WORK_SHIFT_TICKS
        wage = Actors.WORK_WAGE * (Actors.WORK_SHIFT_TICKS // Actors.WORK_PAY_TICKS)
        minutes = Actors.WORK_SHIFT_TICKS * self.tick_seconds / 60
        return (
            f"{character.name} takes odd jobs around {character.location.name}: hauling water, mending walls,"
            f" minding stalls. ${wage} over the next {minutes:.0f} minutes, paid as you go, as long as you stay in town."
        )

    def gather(self, character: Actors.PlayerCharacter) -> str:
        """Gather firewood for one shift on quiet ground out past the towns: World.advance hands it over."""
        if isinstance(character.location, Town):
            raise ValueError("You're in a town: `/town work` pays here.")
        if self.world.danger_at(character.location) > Actors.GATHER_MAX_DANGER:
            raise ValueError(
                f"Too rough here to stop and gather. Only danger {Actors.GATHER_MAX_DANGER} ground, near town, is quiet enough."
            )
        character.work_until = self.world.ticks + Actors.WORK_SHIFT_TICKS
        bundles = Actors.WORK_SHIFT_TICKS // Actors.GATHER_TICKS
        minutes = Actors.WORK_SHIFT_TICKS * self.tick_seconds / 60
        return (
            f"{character.name} gathers firewood: {bundles} bundles over the next {minutes:.0f} minutes, as long as you"
            f" stay put. Any store buys it, if you get it back to town."
        )

    def camp(self, character: Actors.PlayerCharacter) -> str:
        """Rest where `character` stands, out past the towns: World.advance heals it until it moves or dies."""
        if isinstance(character.location, Town):
            raise ValueError("You're in a town: `/town inn` patches you up on the spot.")
        character.camping = True
        missing = character.hit_points_max - character.hit_points
        minutes = math.ceil(missing / character.camp_heal) * Actors.CAMP_HEAL_TICKS * self.tick_seconds / 60
        return (
            f"{character.name} makes camp. Back to full in about {minutes:.0f} minutes, as long as you stay put."
            if missing > 0
            else f"{character.name} makes camp, already at full health."
        )

    def start_raid(self, character: Actors.PlayerCharacter, minutes: int, depth: int = 1) -> str:
        """Send `character` out unattended for `minutes`, no deeper than danger `depth`; World.tick walks it
        and says how it went."""
        character.auto_raid = (self.world.ticks + int(minutes * 60 / self.tick_seconds), character.deaths, depth)
        return (
            f"{character.name} heads out for the caches, no deeper than danger {depth}. Back in {minutes} minutes,"
            f" sooner if it goes badly: you'll get a message either way."
        )

    def hideout_text(self, character: Actors.PlayerCharacter) -> str:
        """The idle side in a sentence, from Discord or the web alike."""
        money, salvage = character.hideout_price
        price = f"{salvage} salvage" if salvage else f"${money:,}"
        if not character.hideout_level:
            return f"No hideout yet: `/hideout build` in any town, for {price}, earns while you're away."
        text = (
            f"Hideout level {character.hideout_level}: ${self.income_per_hour(character):,} an hour into your stash,"
            f" which is worth ${character.stash_value:,}. The next level costs {price}."
        )
        if character.best_haul:
            text += f" Your best haul, ${character.best_haul:,}, hangs on its wall."
        perks = Actors.HIDEOUT_PERKS.items()
        if rooms := [f"a {perk} ({what})" for perk, (_, what) in perks if character.has_perk(perk)]:
            text += f" It has {', '.join(rooms)}."
        if upcoming := [(level, perk, what) for perk, (level, what) in perks if not character.has_perk(perk)]:
            text += " Level {} opens a {}: {}.".format(*min(upcoming))
        if character.hideout_level >= Actors.PRESTIGE_LEVEL:
            text += " `/hideout prestige` trades it and the stash in for more income for good."
        return text

    def pet_text(self, character: Actors.PlayerCharacter) -> str:
        """How your pet is, from Discord or the web alike."""
        if character.pet_name is None:
            return (
                f"You don't keep a pet. `/pet adopt` in any town buys one for ${Actors.PET_PRICE}: fed, a goat gives"
                " milk into your stash while you're away, and a dog comes on raids and fetches salvage."
            )
        name, now = character.pet_name, self.world.ticks
        if character.pet_gone(now):
            return f"{name} got tired of waiting and wandered off. `/pet adopt` another in any town."
        left = (character.pet_fed_until - now) * self.tick_seconds
        if left <= 0:
            days = math.ceil((left + Actors.PET_RUNAWAY_TICKS * self.tick_seconds) / 86400)
            return (
                f"{name} is hungry and {'gives nothing' if character.pet_kind == 'goat' else 'stays home'}, and"
                f" wanders off within {days} day{'s' * (days > 1)} if nobody feeds it. `/pet feed` in any town, for"
                f" ${Actors.PET_FEED_COST}."
            )
        text = f"{name} is fed for another {math.ceil(left / 3600)} hours or so, and "
        if character.pet_kind == "goat":
            every = round(Actors.PET_MILK_TICKS * self.tick_seconds / 60)
            jugs = "two jugs" if character.pet_yield > 1 else "a jug"
            text += f"gives {jugs} of milk into your stash every {every} minutes."
        else:
            often = "now and then" if character.pet_yield > 1 else "once in a while"
            text += f"comes on your raids: it brings back salvage {often} when nothing else is going on."
        if character.pet_yield > 1:
            return text + f" It's a happy {character.pet_kind}: keep feeding it on time."
        more = Actors.PET_CARE_MAX - character.pet_care
        twice = "gives twice that" if character.pet_kind == "goat" else "fetches twice as often"
        return text + f" Feed it before it's hungry {more} more time{'s' * (more > 1)} running and it {twice}."

    @property
    def width(self):
        return self.world.width

    @property
    def height(self):
        return self.world.height

    def add_renderer(self, renderer):
        self._renderer = renderer

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

    def look_text(self, character: Actors.PlayerCharacter) -> str:
        """Where `character` stands, how rough it is, and who and what's in view (people, animals, the piles a
        raid death left), nearest first with a bearing to each."""
        here = character.location
        text = f"You're at {self.world.grid(here.x, here.y)}, on {here.terrain.label}."
        if isinstance(here, Town):
            text += f" You're in {here.name}: safe ground."
        elif isinstance(here, Wilds):
            text += f" You're in the wilds, {here.name}, danger {here.level}."
        else:
            text += f" Out here is danger {self.world.depth_at(here)}."
        if not isinstance(here, Town):  # where a raid ends: a town, or a ride to one (towns and extracts load as explored)
            out = min(self.world.towns + self.world.extracts, key=here.distance)
            squares = max(abs(out.x - here.x), abs(out.y - here.y))
            where = out.name if isinstance(out, Town) else "an extraction point"
            text += f" Nearest way out: {where}, {squares} square{'s' * (squares != 1)} {bearing(here, out)}."
        seen: List[Tuple[str, Space]] = []
        for actor in self.get_nearby_npcs(character) + self.get_nearby_players(character):
            if actor is not character:
                kind = " (raider)" if isinstance(actor, Actors.Raider) else ""
                kind = " (player)" if isinstance(actor, Actors.PlayerCharacter) else kind
                seen.append((actor.name + kind, actor.location))
        for space in self.world.live_piles():
            pile = space.remains
            if pile is not None and max(abs(space.x - here.x), abs(space.y - here.y)) <= character.fov:
                seen.append((f"{pile.owner.name}'s things ({pile})", space))
        if not seen:
            return text + " Nobody else in sight."

        def sighting(label: str, there: Space) -> str:
            squares = max(abs(there.x - here.x), abs(there.y - here.y))
            if not squares:
                return f"{label}, right here"
            return f"{label}, {squares} square{'s' * (squares != 1)} {bearing(here, there)}"

        seen.sort(key=lambda s: here.distance(s[1]))
        return text + "\nIn sight: " + "; ".join(sighting(*s) for s in seen) + "."

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

    def get_player_screenshot(self, character: Actors.PlayerCharacter) -> bytes | None:
        """The PNG /look attaches, or None without a renderer."""
        return self._renderer.get_player_view(character) if self._renderer is not None else None

    def hideout_png(self, character: Actors.PlayerCharacter) -> bytes | None:
        """A picture of the character's hideout, None before they build one or without a renderer."""
        return self._renderer.hideout_png(character) if self._renderer is not None else None
