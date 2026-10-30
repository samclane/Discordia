from __future__ import annotations

import logging
import random
import sys
import time
from abc import ABC
from contextlib import contextmanager
from dataclasses import dataclass, field
from collections import Counter
from itertools import product
from typing import List, Tuple, Dict, Iterator, Sequence, Set, Type, Union

import math
import numpy as np
from astar import AStar
from math import sqrt
from noise import pnoise3

from Discordia import SPRITE_FOLDER
from Discordia.GameLogic import Events, Actors, Items, Weapons
from Discordia.GameLogic.Items import Equipment
from Discordia.GameLogic.Procedural import normal, WorldGenerationParameters
from Discordia.GameLogic.StringGenerator import (
    FemaleNameGenerator,
    MaleNameGenerator,
    TownNameGenerator,
    WildsNameGenerator,
)

LOG = logging.getLogger("Discordia.GameLogic.GameSpace")

Direction = Tuple[int, int]

DIRECTION_VECTORS: Dict[str | None, Direction] = {
    "n": (0, -1),
    "s": (0, 1),
    "e": (1, 0),
    "w": (-1, 0),
    "ne": (1, -1),
    "se": (1, 1),
    "sw": (-1, 1),
    "nw": (-1, -1),
    "center": (0, 0),
    None: (0, 0),
}

MAX_POPULATION_TOWN = 1000  # Maximum population of a town

# Who you meet in every town (Town.residents), and what each might say. Flavor only: they aren't on the map.
TOWNSFOLK = {
    "shopkeeper": [
        "Cash only. Everything on these shelves has been somewhere before.",
        "Bring back what you find out there. I'll give you a fair price. Fair-ish.",
        "If it fires, I'll sell it. If it doesn't, I'll still sell it.",
    ],
    "innkeeper": [
        "A bed and a bandage, on the house. Dying out there is bad for business.",
        "Sit down before you fall down.",
        "Half the beds are empty. The other half aren't coming back.",
    ],
    "guard": [
        "Nobody brings a fight past this gate. Out there's your business.",
        "Raiders don't come in. They wait for you to come out.",
        "Keep your head down past the last streetlight.",
    ],
}


def bearing(origin: Space, target: Space) -> str:
    """Rough compass direction from one square to another: "northeast", "west", or "" if they match."""
    vertical = (
        "north" if target.y < origin.y else "south" if target.y > origin.y else ""
    )
    horizontal = (
        "west" if target.x < origin.x else "east" if target.x > origin.x else ""
    )
    return vertical + horizontal


# The roughest the wilds get, at the far end of the map. A level-8 wilds is a rifle-and-a-few-levels
# proposition; see danger_level for how distance from the spawn maps onto the range.
WILDS_MAX_LEVEL = 8
# Squares of distance from the spawn per wilds level, so WILDS_MAX_LEVEL starts about 220 squares out.
# It used to be a share of the whole map, which on a big map made everywhere walkable level 1.
DANGER_TILES_PER_LEVEL = 32

# The map is generated CHUNK_SIZE squares on a side, as each chunk is first touched. The spawn search
# gives up after this many rings of chunks around the middle and plants a town instead.
CHUNK_SIZE = 32
SPAWN_SEARCH_RINGS = 3

# The order Terrain.neighbours reads a square's neighbours in, lowest bit first.
NEIGHBOURS = [
    DIRECTION_VECTORS[key] for key in ["nw", "n", "ne", "w", "e", "sw", "s", "se"]
]

# How many sprites a wilds square picks between (Sprites/Structures/wilds_N.png).
WILDS_SPRITES = 8

# Roaming raiders are capped at one per this many wilds squares. At one per square every step off the
# road had a raider on it, hitting every tick, and a fresh character lasted a couple of minutes. At one
# per 10 (about 9 a chunk) a player woke dozens at once; one per 40 is about 2 a chunk.
# The cap counts animals too: ANIMAL_SHARE of what spawns is wildlife rather than raiders.
WILDS_PER_RAIDER = 40
ANIMAL_SHARE = 1 / 3

# Caches: the map is cut into cells CACHE_CELL chunks a side, and each cell rolls CACHE_CHANCE for one cache in
# one of its middle chunks (never an edge one, so two caches are always two chunks apart). Within that chunk it
# goes on the square furthest from any town, and not at all if that's under CACHE_TOWN_DISTANCE squares.
CACHE_CELL = 4
CACHE_CHANCE = 0.5
CACHE_TOWN_DISTANCE = 12
# What a cache holds, in money per wilds level. Several kills' worth: it's a long walk out.
CACHE_CURRENCY_PER_LEVEL = 100
# Its piece of kit is the dearest of `level` picks from a store's stock, and it holds one salvage plus one more
# every CACHE_LEVELS_PER_SALVAGE levels: further out pays better. An emptied cache restocks after
# CACHE_REFILL_TICKS, four hours at a 5-second tick, so a raid route is worth running a few times a day.
CACHE_LEVELS_PER_SALVAGE = 3
CACHE_REFILL_TICKS = 2880

# Extraction points: on the same cells as caches, each cell rolls EXTRACT_CHANCE for one on a plain square of one
# of its middle chunks. Stepping on one is a ride to the nearest town, so a deep raid needn't walk all the way back.
EXTRACT_CHANCE = 0.5

# NPCs only act within this many squares of a player. Everywhere else holds still until somebody comes
# near, which keeps a tick cheap however many raiders are out there. A chunk, not the player's view, so
# raiders still wander in from just out of sight.
NPC_AWAKE_RADIUS = CHUNK_SIZE

# How far a raider spots a player from, in squares either way. Further than /look's 2, so the first a
# player knows of one is its warning, while there's still room to run.
NPC_SIGHT = 6

# An auto-raid heads home early below this share of its hit points, as a player watching would.
AUTO_RAID_RETREAT = 0.4

# After something happens on a wilds square it goes quiet for this many world ticks (an hour at a 5-second tick),
# then restocks with fresh events: no stepping back and forth on one square for fight after fight.
WILDS_QUIET_TICKS = 720

# How long what a raid death drops lies on the ground, in world ticks: an hour at the default 5-second tick.
REMAINS_TICKS = 720


@contextmanager
def _seeded(*key):
    """Run world generation on its own RNG, keyed so a chunk comes out the same whenever and in
    whatever order it's generated, without disturbing the game's own random sequence.
    """
    state, np_state = random.getstate(), np.random.get_state()
    random.seed(":".join(map(str, key)))
    np.random.seed(random.randrange(2**32))
    try:
        yield
    finally:
        random.setstate(state)
        np.random.set_state(np_state)


def death_toll_text(player: Actors.PlayerCharacter) -> str:
    """What the last death cost, phrased for a player, or "" if they had nothing to lose."""
    return f" You lost {player.last_death_loss}." if player.last_death_loss else ""


class Terrain(ABC):
    # Which of the eight neighbours are the same terrain, as bits in NEIGHBOURS order. Set at generation;
    # the renderer draws coastlines and kerbs from it.
    neighbours: int = 0

    def __str__(self) -> str:
        return self.__class__.__name__

    def __repr__(self) -> str:
        return str(self)

    def __hash__(self):
        return hash(str(self)) + hash(self.walkable)

    @property
    def walkable(self) -> bool:
        raise NotImplementedError

    @property
    def name(self) -> str:
        raise NotImplementedError

    @property
    def cost(self) -> int:
        # Unimplemented terrain returns "infinite"
        return sys.maxsize

    @property
    def buildable(self):
        raise NotImplementedError

    @property
    def layer(self):
        """Basically the Z value of the terrain; how high it is. 0 is sea level. -1 is null-level"""
        raise NotImplementedError


class NullTerrain(Terrain):
    @property
    def walkable(self) -> bool:
        return False

    @property
    def name(self) -> str:
        return "null_tile"

    @property
    def cost(self) -> int:
        return sys.maxsize

    @property
    def buildable(self) -> bool:
        return False

    @property
    def layer(self) -> int:
        return -1


class SandTerrain(Terrain):
    @property
    def walkable(self) -> bool:
        return True

    @property
    def name(self) -> str:
        return "sand"

    @property
    def cost(self) -> int:
        return 2

    @property
    def buildable(self) -> bool:
        return True

    @property
    def layer(self) -> int:
        return 1


class GrassTerrain(Terrain):
    @property
    def walkable(self) -> bool:
        return True

    @property
    def name(self) -> str:
        return "grass"

    @property
    def cost(self) -> int:
        return 1

    @property
    def buildable(self) -> bool:
        return True

    @property
    def layer(self) -> int:
        return 1


class WaterTerrain(Terrain):
    @property
    def walkable(self) -> bool:
        return True

    @property
    def name(self) -> str:
        return "water"

    @property
    def cost(self) -> int:
        return 5

    @property
    def buildable(self) -> bool:
        return False

    @property
    def layer(self) -> int:
        return 0


class MountainTerrain(Terrain):
    @property
    def walkable(self) -> bool:
        return True

    @property
    def name(self) -> str:
        return "mountain"

    @property
    def cost(self) -> int:
        return 8

    @property
    def buildable(self) -> bool:
        return False

    @property
    def layer(self) -> int:
        return 2


class IndustryType(ABC):
    @property
    def name(self) -> str:
        raise NotImplementedError

    @property
    def recruitment_class(self) -> Actors.PlayerClass:
        return Actors.WandererClass()


class NullIndustry(IndustryType):
    @property
    def name(self) -> str:
        return "None"


class MiningIndustry(IndustryType):
    @property
    def name(self) -> str:
        return "Mining"


class FarmingIndustry(IndustryType):
    @property
    def name(self) -> str:
        return "Farming"


class SmithingIndustry(IndustryType):
    @property
    def name(self) -> str:
        return "Smithing"


class WoodworkingIndustry(IndustryType):
    @property
    def name(self) -> str:
        return "Woodworking"


class MilitaryBase(IndustryType, ABC):
    @property
    def name(self) -> str:
        raise NotImplementedError

    @property
    def recruitment_class(self) -> Actors.PlayerClass:
        return Actors.Soldier()


class EasternMilitaryBase(MilitaryBase):
    @property
    def name(self) -> str:
        return "Eastern Military Base"


class WesternMilitaryBase(MilitaryBase):
    @property
    def name(self) -> str:
        return "Western Military Base"


def concrete_industries() -> List[Type[IndustryType]]:
    """Industries a town can actually have.

    IndustryType.__subclasses__() only goes one level deep, so it hands back MilitaryBase - which is
    abstract, has no name, and hides the two real military bases underneath it.
    """
    return [
        leaf
        for industry in IndustryType.__subclasses__()
        for leaf in (industry.__subclasses__() or [industry])
    ]


class Space(ABC):
    # What a raid death left here, if anything. A class default, so the million squares nobody died on
    # don't each carry an empty pile.
    remains: Remains | None = None

    def __init__(self, x: int, y: int, terrain: Terrain = NullTerrain()):
        if x < 0 or y < 0:
            raise ValueError(f"Negative coordinate given: {min(x, y)}")
        self.x: int = x
        self.y: int = y
        self.terrain: Terrain = terrain
        self.name = str(self)

    def __str__(self):
        return "({}, {})".format(self.x, self.y)

    def __repr__(self):
        return str((self.x, self.y, self.terrain))

    def __eq__(self, other):
        if isinstance(other, Space):
            return self.x == other.x and self.y == other.y
        try:
            return self.x == other[0] and self.y == other[1]
        except (TypeError, IndexError, ValueError):
            # Anything that isn't a coordinate pair simply isn't this space. A despawned actor's
            # location is None, and comparing against it must answer False, not raise.
            return NotImplemented

    def __add__(self, other) -> Space:
        if isinstance(other, Space):
            return Space(
                max(self.x + other.x, 0), max(self.y + other.y, 0), other.terrain
            )
        else:
            return Space(
                max(self.x + int(other[0]), 0),
                max(self.y + int(other[1]), 0),
                NullTerrain(),
            )

    def __sub__(self, other):
        if isinstance(other, Space):
            return Space(
                max(self.x - other.x, 0), max(self.y - other.y, 0), other.terrain
            )
        else:
            return Space(
                max(self.x - int(other[0]), 0),
                max(self.y - int(other[1]), 0),
                NullTerrain(),
            )

    def __iter__(self):
        yield self.x
        yield self.y

    def __getitem__(self, item) -> int:
        if item == 0:
            return self.x
        if item == 1:
            return self.y
        raise ValueError("Item should be either 0 or 1")

    def __hash__(self):
        # Whatever __eq__ compares, and nothing else: a space equals its (x, y), so it hashes like one too.
        return hash((self.x, self.y))

    def distance(self, other) -> float:
        return sqrt(abs(self.x - other[0]) ** 2 + abs(self.y - other[1]) ** 2)

    def closest(self, space_list: Sequence[Union[Space, Tuple[int, int]]], size=1):
        """The `size` spaces in space_list nearest this one, nearest first."""
        return sorted(space_list, key=lambda o: self.distance(o))[:size]


class Town(Space):

    def __init__(
        self,
        x: int,
        y: int,
        name: str,
        population: int = 0,
        industry: IndustryType = NullIndustry(),
        terrain: Terrain = NullTerrain(),
        store: Store | None = None,
    ) -> None:
        super(Town, self).__init__(x, y, terrain)
        self.name: str = name
        self.population: int = population
        self.industry: IndustryType = industry
        self.store: Store = store if store is not None else Store()
        self.is_underwater: bool = isinstance(self.terrain, WaterTerrain)

    @property
    def residents(self) -> List[Tuple[str, str, str]]:
        """(role, name, what they say) for each of TOWNSFOLK. Rolled on its own seed from where the town stands,
        not in generate_town: drawing there would shift the chunk's generation and move every existing map."""
        with _seeded("residents", self.x, self.y):
            return [
                (role, random.choice([MaleNameGenerator, FemaleNameGenerator]).generate_name(), random.choice(lines))
                for role, lines in TOWNSFOLK.items()
            ]

    @classmethod
    def generate_town(cls, x, y, terrain):
        name = TownNameGenerator.generate_name()
        population = random.randint(1, MAX_POPULATION_TOWN)
        industry = random.choice(concrete_industries())()
        store = Store.generate_store()
        return cls(x, y, name, population, industry, terrain, store)

    def inn_event(self, character: Actors.PlayerCharacter) -> PlayerActionResponse:
        character.hit_points = character.hit_points_max
        resp = PlayerActionResponse(
            True,
            0,
            character,
            f"Your hitpoints have been restored, {character.name}",
            [],
            0,
            source=character,
        )
        return resp

    def recruit(self, character: Actors.PlayerCharacter) -> PlayerActionResponse:
        _class = self.industry.recruitment_class
        if (
            _class.tier >= character.player_class.tier
            and _class.name != character.player_class.name
        ):
            character.player_class = _class
            resp = PlayerActionResponse(
                is_successful=True,
                text=f"Class was successfully changed to {_class.name}",
            )
        else:
            resp = PlayerActionResponse(
                is_successful=False,
                text=f"Your class is already better than {_class.name}",
            )
        return resp

    @property
    def sprite_path(self):
        return SPRITE_FOLDER / "Structures" / "town_default.png"

    @property
    def sprite_path_string(self):
        return str(self.sprite_path)


class BaseLevel:

    def __init__(self, level: int):
        self.level: int = level
        self.max_level: int = 5

    def upgrade(self):
        if self.level < self.max_level:
            self.level += 1
            return True
        return False

    def base_event(self, character: Actors.PlayerCharacter) -> PlayerActionResponse:
        character.hit_points = character.hit_points_max
        resp = PlayerActionResponse(
            is_successful=True,
            text=f"Your hitpoints have been restored, {character.name}",
            source=character,
        )
        return resp


class Base(Space):

    def __init__(
        self,
        x: int,
        y: int,
        name: str,
        terrain: Terrain = NullTerrain(),
        store: Store | None = None,
        owner: Actors.PlayerCharacter | None = None,
    ) -> None:
        super().__init__(x, y, terrain)
        self.name: str = name
        self.store: Store = store if store is not None else Store()
        self.owner: Actors.PlayerCharacter | None = owner
        self.is_underwater: bool = isinstance(self.terrain, WaterTerrain)
        self.level = BaseLevel(1)

    @classmethod
    def generate_base(cls, x, y, terrain, owner: Actors.PlayerCharacter | None = None):
        name = "Base"
        store = Store.generate_store()
        return cls(x, y, name, terrain, store, owner=owner)


class Wilds(Space):

    def __init__(self, x, y, name, terrain: Terrain = NullTerrain()):
        super().__init__(x, y, terrain)
        self.name: str = name
        self.level: int = (
            0  # set by the World once it knows the spawn; 0 means nothing happens here
        )
        self.null_event: Events.Event = Events.Event.null_event()
        self.events: List[Events.Event] = []
        self.events.append(self.null_event)
        # World.ticks until which nothing happens here, after the last event; None if nothing has yet.
        # ponytail: not saved, but neither are the events: a restart restocks every square on its next visit.
        self.quiet_until: int | None = None

    def add_event(self, event: Events.Event):
        if event.probability > self.null_event.probability:
            event.probability = self.null_event.probability
        self.events.append(event)
        self.null_event.probability -= event.probability
        assert self.null_event.probability >= 0

    def run_event(self, player) -> List[PlayerActionResponse]:
        if self.quiet_until is not None:
            if player.parent_world.ticks < self.quiet_until:
                return []  # as the null event: nothing to narrate
            # Back after a quiet spell: new faces, not the bodies of the last fight to loot again.
            self.null_event, self.events, self.quiet_until = Events.Event.null_event(), [], None
            self.events.append(self.null_event)
        if len(self.events) == 1:
            # Stocked on the first visit, not at generation: enemies and merchant stock are most of a
            # chunk's memory, and most wilds on a big map never see a player.
            self.populate(self.level)
        chosen_event = random.choices(
            self.events, weights=[event.probability for event in self.events]
        )[0]
        results = chosen_event.run(player)
        if results is None:
            results = [PlayerActionResponse(source=player)]
        if chosen_event is not self.null_event:
            self.quiet_until = player.parent_world.ticks + WILDS_QUIET_TICKS
        return list(results)

    def populate(self, level: int):
        """Fill these wilds with `level` events of that difficulty.

        Separate from construction because how rough a place is depends on how far it is from the
        starting town, and the map does not know where that is until every town has been placed.
        """
        self.level = level
        for _ in range(level):
            self.add_event(Events.generate_event(level))

    @classmethod
    def generate(cls, x, y, terrain: Terrain, level) -> Wilds:
        wilds = cls(x, y, WildsNameGenerator.generate_name(), terrain)
        wilds.populate(level)
        return wilds

    @property
    def sprite_path(self):
        # Picked by position, so a square looks the same every time it's drawn.
        variant = (self.x * 31 + self.y * 17) % WILDS_SPRITES
        return SPRITE_FOLDER / "Structures" / f"wilds_{variant}.png"

    @property
    def sprite_path_string(self):
        return str(self.sprite_path)


class Cache(Space):
    """A stash out past the towns: money and a piece of kit for the first player to step on it."""

    def __init__(self, x, y, terrain: Terrain = NullTerrain()):
        super().__init__(x, y, terrain)
        self.name = "a cache"
        self.level: int = 0  # set by the World with the wilds around it
        # World.ticks when it was last emptied, or None if it's full.
        # ponytail: not saved, so a restart refills every cache early. Save opened caches if anyone farms that.
        self.looted_at: int | None = None

    def run_event(self, player) -> List[PlayerActionResponse]:
        response = PlayerActionResponse(is_successful=True, source=player)
        now = player.parent_world.ticks
        if self.looted_at is not None and now - self.looted_at < CACHE_REFILL_TICKS:
            response.text = "There's a cache here, already emptied. Someone will restock it, in time."
            return [response]
        self.looted_at = now
        level = max(self.level, 1)
        response.currency = int(normal(CACHE_CURRENCY_PER_LEVEL * level, positive=True, integer=True))
        player.currency += response.currency
        found = [f"${response.currency}"]
        stock = Store.generate_store().inventory
        kit = [max(random.sample(stock, min(level, len(stock))), key=lambda i: i.base_value)] if stock else []
        # Salvage every time: the hideout's barter levels can't be bought, so caches are where they come from.
        salvage = [Items.Salvage() for _ in range(1 + level // CACHE_LEVELS_PER_SALVAGE)]
        for item in kit + salvage:
            player.inventory.append(item)
            response.items.append(item)
            found.append(str(item))
        response.text = f"You find a cache, and in it {', '.join(found)}."
        return [response]

    @property
    def sprite_path(self):
        return SPRITE_FOLDER / "Structures" / "cache.png"

    @property
    def sprite_path_string(self):
        return str(self.sprite_path)


class Extract(Space):
    """A way out in the wilds: step on it and you're driven to the nearest town, raid over."""

    def __init__(self, x, y, terrain: Terrain = NullTerrain()):
        super().__init__(x, y, terrain)
        self.name = "an extraction point"

    def run_event(self, player) -> List[PlayerActionResponse]:
        world = player.parent_world
        # Picked up here, before the ride: a pile on this square can't be reached any other way.
        responses = [found] if (found := world.pick_up_remains(player)) is not None else []
        town = min(world.towns, key=self.distance)
        player.location = town  # PlayerCharacter.attempt_move sees a town and reports the haul
        text = f"A ride is waiting at the extraction point. It drops you in {town.name}."
        return responses + [PlayerActionResponse(is_successful=True, source=player, text=text)]

    @property
    def sprite_path(self):
        return SPRITE_FOLDER / "Structures" / "extract.png"

    @property
    def sprite_path_string(self):
        return str(self.sprite_path)


@dataclass
class PlayerActionResponse:
    is_successful: bool = False
    damage: int = 0
    target: Actors.Actor | None = None
    text: str = ""
    items: List[Equipment] = field(default_factory=list)
    currency: int = 0
    source: Actors.Actor | None = None

    @property
    def failed(self):
        return not self.is_successful


@dataclass
class Remains:
    """What a raid death left on a square, for whoever steps on it first before World.ticks passes `expires`."""

    owner: Actors.PlayerCharacter
    items: List[Equipment]
    currency: int
    expires: int

    def __str__(self):
        return ", ".join(([f"${self.currency}"] if self.currency else []) + [str(item) for item in self.items])


@dataclass
class Stats:
    """What happened since the last digest (Interface.Alerts.digest). Not saved: a restart starts over."""

    since: float = field(default_factory=time.time)
    kills: int = 0
    # Keyed by the danger level of the wilds you died in; 0 is anywhere that isn't wilds.
    deaths_by_level: Counter = field(default_factory=Counter)
    active_players: Set[Actors.PlayerCharacter] = field(default_factory=set)


class World:
    """A width x height map, generated a chunk at a time as something first touches it.

    Nothing about a chunk depends on when it was generated: terrain is noise sampled at its
    coordinates, and towns and wilds roll on an RNG keyed by (seed, chunk). So the map can be as big
    as you like, a save file stays just the seed, and only the ground somebody has walked on costs
    memory.
    """

    def __init__(
        self,
        name: str,
        width: int,
        height: int,
        generation_parameters: WorldGenerationParameters = WorldGenerationParameters(),
        seed=None,
    ):
        super().__init__()
        self.name: str = name
        self.width: int = width
        self.height: int = height
        self.gen_params: WorldGenerationParameters = generation_parameters
        # ponytail: chunks are never unloaded, so memory grows ~0.4 MB per chunk explored. Evict chunks
        # nobody stands in if that ever adds up; they regenerate identically, minus store sales.
        self._chunks: Dict[Tuple[int, int], List[List[Space]]] = {}
        self.towns: List[Town] = []  # in loaded chunks only, like wilds
        self.wilds: List[Wilds] = []
        self.caches: List[Cache] = []
        self.extracts: List[Extract] = []
        self.players: List[Actors.PlayerCharacter] = []
        self.npcs: List[Actors.NPC] = []
        self.stats: Stats = Stats()
        self.ticks: int = 0  # how many times tick() has run, as a clock for things that expire
        self.starting_town: Town = None  # type: ignore[assignment]  # chosen by _choose_spawn

        # Always seeded, and always remembers its seed: that's what lets a save file be just the seed.
        self.seed: int = random.randrange(2**32) if seed is None else seed
        random.seed(self.seed)
        np.random.seed(self.seed)
        # Tuned on a 50-square map, where it gave islands about ten squares across. Fixed rather than
        # scaled to the map, so a big world is more of the same, not the same few islands blown up.
        self._noise_scale = self.gen_params.resolution_constant * 50
        self._slices = (random.random(), random.random(), random.random())
        self._choose_spawn()

    def _choose_spawn(self):
        """Start in the town nearest the middle, searching outward a ring of chunks at a time."""
        LOG.info("Generating Map...")
        center = Space(self.width // 2, self.height // 2)
        ccx, ccy = center.x // CHUNK_SIZE, center.y // CHUNK_SIZE
        last_x, last_y = (self.width - 1) // CHUNK_SIZE, (self.height - 1) // CHUNK_SIZE
        for ring in range(SPAWN_SEARCH_RINGS + 1):
            for cx in range(max(ccx - ring, 0), min(ccx + ring, last_x) + 1):
                for cy in range(max(ccy - ring, 0), min(ccy + ring, last_y) + 1):
                    if max(abs(cx - ccx), abs(cy - ccy)) == ring:
                        self._load_chunk(cx, cy)
            if self.towns:
                break

        if not self.towns:
            # Towns are a per-square dice roll, so a small or unlucky map can come up with none, and a
            # world with nowhere to spawn is no world at all. Plant one rather than dying on the empty list.
            buildable = [
                space
                for rows in self._chunks.values()
                for row in rows
                for space in row
                if self.is_space_buildable(space)
            ]
            if not buildable:
                raise RuntimeError(f"World '{self.name}' generated no buildable land")
            spot = min(buildable, key=center.distance)
            town = Town.generate_town(spot.x, spot.y, terrain=spot.terrain)
            rows = self._chunks[spot.x // CHUNK_SIZE, spot.y // CHUNK_SIZE]
            rows[spot.y % CHUNK_SIZE][spot.x % CHUNK_SIZE] = town
            self.towns.append(town)
            LOG.info(f"No towns were rolled; placed one at ({spot.x}, {spot.y})")

        self.starting_town = min(self.towns, key=center.distance)

        # Only now is there a spawn to measure danger from: wilds loaded before this are still bare.
        for cx, cy in list(self._chunks):
            self._populate_chunk(cx, cy)
        LOG.info("Generation finished")

    def _terrain_at(self, x: int, y: int) -> Terrain:
        nx, ny = x / self._noise_scale, y / self._noise_scale
        # ponytail: pnoise3 repeats every 256 noise units, so terrain tiles every ~2560 squares (towns
        # and wilds don't, they're rolled per chunk). Shift the z slice per region if anyone notices.
        terrain: Terrain = (
            SandTerrain()
            if abs(pnoise3(nx, ny, self._slices[0])) > self.gen_params.water
            else WaterTerrain()
        )
        if (
            abs(pnoise3(nx, ny, self._slices[1])) > self.gen_params.mountains
            and terrain.walkable
        ):
            terrain = MountainTerrain()
        if abs(pnoise3(nx, ny, self._slices[2])) > self.gen_params.grass:
            terrain = GrassTerrain()
        return terrain

    def _load_chunk(self, cx: int, cy: int) -> List[List[Space]]:
        rows = self._roll_chunk(cx, cy)
        self._place_cache(cx, cy, rows)
        self._place_extract(cx, cy, rows)
        for row in rows:
            for space in row:
                if isinstance(space, Town):
                    self.towns.append(space)
                elif isinstance(space, Wilds):
                    self.wilds.append(space)
                elif isinstance(space, Cache):
                    self.caches.append(space)
                elif isinstance(space, Extract):
                    self.extracts.append(space)
        self._chunks[cx, cy] = (
            rows  # published whole: the web map reads this from another thread
        )
        if self.starting_town is not None:
            self._populate_chunk(cx, cy)
        return rows

    def _cell_picked(self, cx: int, cy: int, kind: str, chance: float) -> bool:
        """Whether this chunk's cell rolled a `kind` (under `chance`) and put it in this chunk (see CACHE_CELL)."""
        gx, gy = cx // CACHE_CELL, cy // CACHE_CELL
        with _seeded(self.seed, gx, gy, kind):
            if random.random() > chance:
                return False
            pick = (
                gx * CACHE_CELL + random.randint(1, CACHE_CELL - 2),
                gy * CACHE_CELL + random.randint(1, CACHE_CELL - 2),
            )
        return pick == (cx, cy)

    def _place_extract(self, cx: int, cy: int, rows: List[List[Space]]):
        """Put this chunk's extraction point in, if its cell rolled one here: any plain square will do."""
        if not self._cell_picked(cx, cy, "extract", EXTRACT_CHANCE):
            return
        spots = [space for row in rows for space in row if type(space) is Space and space.terrain.buildable]
        if not spots:
            return
        with _seeded(self.seed, cx, cy, "extract"):
            spot = random.choice(spots)
        rows[spot.y % CHUNK_SIZE][spot.x % CHUNK_SIZE] = Extract(spot.x, spot.y, spot.terrain)

    def _place_cache(self, cx: int, cy: int, rows: List[List[Space]]):
        """Put this chunk's cache in, if its cell rolled one and picked this chunk (see CACHE_CELL)."""
        if not self._cell_picked(cx, cy, "cache", CACHE_CHANCE):
            return
        # Towns over the chunk line count too. Rolling a neighbour is pure, so unloaded ones are rolled
        # and thrown away rather than loaded, which would set every neighbour placing its own cache.
        towns = [
            space
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            if 0 <= (cx + dx) * CHUNK_SIZE < self.width
            and 0 <= (cy + dy) * CHUNK_SIZE < self.height
            for row in (
                rows
                if (dx, dy) == (0, 0)
                else self._chunks.get((cx + dx, cy + dy))
                or self._roll_chunk(cx + dx, cy + dy)
            )
            for space in row
            if isinstance(space, Town)
        ]
        spots = [space for row in rows for space in row if space.terrain.buildable]
        if not spots:
            return
        far = lambda s: min((s.distance(t) for t in towns), default=float("inf"))
        spot = max(spots, key=far)
        if far(spot) < CACHE_TOWN_DISTANCE:
            return
        x, y = spot.x % CHUNK_SIZE, spot.y % CHUNK_SIZE
        rows[y][x] = Cache(spot.x, spot.y, spot.terrain)

    def _roll_chunk(self, cx: int, cy: int) -> List[List[Space]]:
        """A chunk's squares, towns and wilds. No side effects: the same chunk comes out every call."""
        x0, y0 = cx * CHUNK_SIZE, cy * CHUNK_SIZE
        xs = range(x0, min(x0 + CHUNK_SIZE, self.width))
        ys = range(y0, min(y0 + CHUNK_SIZE, self.height))
        # A square of margin: edges look at neighbours, and those can be in the next chunk over.
        terrain = {
            (x, y): self._terrain_at(x, y)
            for x in range(xs.start - 1, xs.stop + 1)
            for y in range(ys.start - 1, ys.stop + 1)
        }

        rows: List[List[Space]] = []
        with _seeded(self.seed, cx, cy):
            for y in ys:
                row: List[Space] = []
                for x in xs:
                    here = terrain[x, y]
                    here.neighbours = sum(
                        1 << bit
                        for bit, (dx, dy) in enumerate(NEIGHBOURS)
                        if terrain[x + dx, y + dy].name == here.name
                    )

                    space: Space = Space(x, y, here)
                    if here.buildable:
                        if random.random() <= self.gen_params.towns:
                            space = Town.generate_town(x, y, terrain=here)
                        elif random.random() <= self.gen_params.wilds:
                            # Bare until the spawn is known: how rough it is depends on the distance.
                            space = Wilds(
                                x, y, WildsNameGenerator.generate_name(), here
                            )
                    row.append(space)
                rows.append(row)
        return rows

    def _populate_chunk(self, cx: int, cy: int):
        """Rate the chunk's wilds and cache. Wilds roll their events from that on the first visit (Wilds.run_event)."""
        with _seeded(self.seed, cx, cy, "wilds"):
            for row in self._chunks[cx, cy]:
                for space in row:
                    if isinstance(space, (Wilds, Cache)):
                        space.level = self.danger_level(space)

    def loaded_chunk(self, cx: int, cy: int) -> List[List[Space]] | None:
        """A chunk's rows if something already generated it, else None. Never generates, so it's safe
        off the game loop."""
        return self._chunks.get((cx, cy))

    def loaded_chunks(self) -> List[Tuple[int, int]]:
        return list(self._chunks)

    def load_around(self, space: Space):
        """Generate the chunks around `space`, so anything asking what's nearby isn't limited to where
        players happen to have been."""
        for dx in (-CHUNK_SIZE, 0, CHUNK_SIZE):
            for dy in (-CHUNK_SIZE, 0, CHUNK_SIZE):
                x, y = space.x + dx, space.y + dy
                if 0 <= x < self.width and 0 <= y < self.height:
                    self.space_at(x, y)

    def space_at(self, x: int, y: int) -> Space:
        """The square at (x, y), generating its chunk on first touch."""
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise IndexError(f"({x}, {y}) is off the map")
        cx, cy = x // CHUNK_SIZE, y // CHUNK_SIZE
        rows = self._chunks.get((cx, cy)) or self._load_chunk(cx, cy)
        return rows[y % CHUNK_SIZE][x % CHUNK_SIZE]

    def depth_at(self, space: Space) -> int:
        """danger_level without the roll: the level a square is meant to be, by distance from the spawn."""
        return min(WILDS_MAX_LEVEL, 1 + int(self.starting_town.distance(space) / DANGER_TILES_PER_LEVEL))

    def danger_level(self, space: Space) -> int:
        """How rough the wilds are at `space`: 1 next to the starting town, one more per
        DANGER_TILES_PER_LEVEL squares out, up to WILDS_MAX_LEVEL. The roll adds a little local variety.
        """
        share = self.starting_town.distance(space) / DANGER_TILES_PER_LEVEL
        rolled = normal(1 + share, integer=True, positive=True)
        return int(max(1, min(WILDS_MAX_LEVEL, rolled)))

    def is_space_valid(self, space: Space) -> bool:
        return (
            (0 <= space.x <= self.width - 1)
            and (0 <= space.y <= self.height - 1)
            and space.terrain.walkable
        )

    def is_coords_valid(self, x: int, y: int):
        if (0 <= x <= self.width - 1) and (0 <= y <= self.height - 1):
            return self.space_at(x, y).terrain.walkable
        return False

    def is_space_buildable(self, space: Space) -> bool:
        # FIXME Ugly function
        if space.terrain.buildable:
            if (
                not self.is_space_valid(space)
                or space in self.towns
                or space in self.wilds
            ):
                return False
            return True
        return False

    def get_adjacent_spaces(self, space: Space, sq_range: int = 1) -> List[Space]:
        fov = list(range(-sq_range, sq_range + 1))
        steps = product(fov, repeat=2)
        coords = (tuple(c + d for c, d in zip(space, delta)) for delta in steps)
        return [
            self.space_at(i, j)
            for i, j in coords
            if (0 <= i < self.width) and (0 <= j < self.height)
        ]

    def add_actor(self, actor: Actors.Actor, space: Space | None = None):
        actor.parent_world = self
        if isinstance(actor, Actors.PlayerCharacter):
            actor.location = self.starting_town
            self.players.append(actor)
        elif isinstance(actor, Actors.NPC) and space and self.is_space_valid(space):
            actor.location = space
            self.npcs.append(actor)

    def get_npcs_in_region(self, spaces: List[Space]) -> List[Actors.NPC]:
        npc_locations: Dict[Actors.NPC, Space] = {
            npc: npc.location for npc in self.npcs
        }
        common_locations: List[Space] = list(
            set(npc_locations.values()).intersection(spaces)
        )
        npcs: List[Actors.NPC] = [
            npc for npc in self.npcs if npc.location in common_locations
        ]
        return npcs

    def get_players_in_region(
        self, spaces: List[Space]
    ) -> List[Actors.PlayerCharacter]:
        player_locations: Dict[Actors.PlayerCharacter, Space] = {
            player: player.location for player in self.players
        }
        common_locations: List[Space] = list(
            set(player_locations.values()).intersection(spaces)
        )
        players: List[Actors.PlayerCharacter] = [
            player for player in self.players if player.location in common_locations
        ]
        return players

    def attack(
        self, player_character: Actors.PlayerCharacter, direction: Direction = (0, 0)
    ) -> PlayerActionResponse:
        """Swing or shoot at whatever is standing in the way: another player or an NPC, whichever is there."""
        direction = direction or (0, 0)  # None: just this square
        response = PlayerActionResponse(
            text="No targets found in that direction", source=player_character
        )
        held = player_character.weapon
        weapon = player_character.ready_weapon()
        if weapon is None:
            response.text = "You have no weapon equipped!"
            return response
        loc: Space = player_character.location
        dmg: int = int(
            weapon.damage
        )  # weapons compute in floats; a hit lands in whole points
        while dmg > 0:
            targets: List[Actors.Actor] = [
                actor
                for actor in self.players + self.npcs
                if actor is not player_character and actor.location == loc
            ]
            if len(targets):
                target: Actors.Actor = random.choice(targets)
                weapon.on_damage()
                target.take_damage(dmg)
                response.is_successful = True
                response.damage = dmg
                response.target = target
                response.text = ""
                # A dead NPC is despawned by its own on_death, so this is the one chance to take its kit.
                if target.is_dead and isinstance(target, Actors.NPC):
                    drops = player_character.loot(target, response)
                    response.text = f"You kill {target.name}" + (
                        f" and take {drops}." if drops else "."
                    )
                break
            else:
                # A melee weapon reaches your square and the one next to it: a raider beside you is one
                # you can hit, not one you have to land on the same square as in the same tick.
                melee = not isinstance(weapon, Weapons.RangedWeapon)
                if melee and loc != player_character.location:
                    response.text = "Nothing within reach of your melee weapon."
                    break
                if direction == (0, 0):
                    response.text = (
                        "Nothing in this square. "
                        "Specify a direction (n,s,e,w,ne,se,sw,nw))"
                    )
                    break
                loc += direction
                loc = self.space_at(loc.x, loc.y)
                if not melee:  # a bullet loses punch with distance; a swing at arm's length doesn't
                    dmg = int(
                        weapon.calc_damage(int(player_character.location.distance(loc)))
                    )
        if weapon is not held and held is not None:
            response.text = f"Your {held.name} is empty, with nothing to load, so it's fists. {response.text}"
        return response

    def near_a_player(self, space: Space | None) -> bool:
        """Whether `space` is within NPC_AWAKE_RADIUS squares of some player, either way."""
        # ponytail: every NPC against every player, each tick. Bucket players by chunk if that grows.
        return space is not None and any(
            p.location is not None
            and max(abs(p.location.x - space.x), abs(p.location.y - space.y)) <= NPC_AWAKE_RADIUS
            for p in self.players
        )

    def prey_in_sight(self, space: Space) -> Actors.PlayerCharacter | None:
        """The nearest player within NPC_SIGHT of `space` who isn't safe in a town."""
        in_sight = [
            p
            for p in self.players
            if p.location is not None
            and not isinstance(p.location, Town)
            and max(abs(p.location.x - space.x), abs(p.location.y - space.y)) <= NPC_SIGHT
        ]
        return min(in_sight, key=lambda p: space.distance(p.location), default=None)

    def _auto_raid_step(self, player: Actors.PlayerCharacter) -> PlayerActionResponse | None:
        """One tick of an unattended raid: fight whatever shares the square, else walk to the nearest stocked
        cache no deeper than `depth` (or explore out to that depth if none is known), and once time is up or
        it's hurt, walk to the nearest town. Returns the raid's result when it ends, for the player to be told; None while it goes on."""
        home_at, deaths, depth = player.auto_raid  # type: ignore[misc]
        if player.deaths != deaths:  # killed since the last step, by an NPC's turn or a wilds fight
            player.auto_raid = None
            return PlayerActionResponse(
                is_successful=False, target=player, source=player,
                text="Your raid is over: you didn't make it back." + death_toll_text(player),
            )
        here = player.location
        if any(npc.location == here for npc in self.npcs) and not isinstance(here, Town):
            self.attack(player, (0, 0))
            return None
        going_home = self.ticks >= home_at or player.hit_points < player.hit_points_max * AUTO_RAID_RETREAT
        if going_home:
            if isinstance(here, Town):  # started in town and never left, or a manual move brought it home
                player.auto_raid = None
                return PlayerActionResponse(
                    is_successful=True, target=player, source=player, text=f"Your raid is over, in {here.name}."
                )
            # An extraction point drops it in a town, so the nearest of either is the way home.
            results = player.step(min(self.towns + self.extracts, key=here.distance))
        else:
            stocked = [
                c for c in self.caches
                if c.level <= depth and (c.looted_at is None or self.ticks - c.looted_at >= CACHE_REFILL_TICKS)
            ]
            if stocked:
                results = player.step(min(stocked, key=here.distance))
            elif (at := self.depth_at(here)) != depth:  # out to its depth, or back up from past it
                results = player.step(self.starting_town, toward=at > depth)
            else:  # as deep as it goes: wander the band, and find a cache if there's one
                results = []
        if not results:  # boxed in: any way at all, and try again next tick
            results = player.attempt_move(random.choice(list(DIRECTION_VECTORS.values())))
        if player.deaths != deaths:
            return self._auto_raid_step(player)  # reports the death
        if going_home and isinstance(player.location, Town):
            player.auto_raid = None
            # The step's last word is PlayerCharacter.extract's haul.
            # ponytail: a raid whose way to a cache crosses a town extracts there too, so this only counts
            # the last leg. Keep a raid-long snapshot on auto_raid if anyone's haul looks short.
            return PlayerActionResponse(
                is_successful=True, target=player, source=player, text=f"Your raid is over. {results[-1].text}"
            )
        return None

    def advance(self, ticks: int):
        """Move the clock on `ticks`, paying every hideout once for each pay day passed. tick() moves it one;
        a load moves it however many ticks the server was down for, so a restart doesn't eat idle income."""
        paydays = (self.ticks + ticks) // Actors.HIDEOUT_PAY_TICKS - self.ticks // Actors.HIDEOUT_PAY_TICKS
        heals = (self.ticks + ticks) // Actors.CAMP_HEAL_TICKS - self.ticks // Actors.CAMP_HEAL_TICKS
        self.ticks += ticks
        for p in self.players:
            p.stash_currency += Actors.HIDEOUT_INCOME * p.hideout_level * paydays
            if p.camping:
                p.hit_points += p.camp_heal * heals

    def tick(self) -> List[PlayerActionResponse]:
        """One step of world time: NPCs spawn, wander and fight without any player input.

        Returns what happened *to players*, so an interface can tell them about it: nobody is watching
        the world when a tick lands on them.
        """
        events: List[PlayerActionResponse] = []
        self.advance(1)
        for p in self.players:
            if p.auto_raid is not None and (event := self._auto_raid_step(p)) is not None:
                events.append(event)
        self.npcs = [npc for npc in self.npcs if not npc.is_dead]
        if self.wilds and len(self.npcs) < len(self.wilds) // WILDS_PER_RAIDER:
            kind = Actors.Animal if random.random() < ANIMAL_SHARE else Actors.Raider
            self.add_actor(kind.generate(1), random.choice(self.wilds))
        for npc in self.npcs:
            if not self.near_a_player(npc.location):
                continue  # the world holds still where nobody is
            # Towns are safe ground: somewhere to respawn, rest and shop without a raider on you.
            targets = [
                p
                for p in self.players
                if p.location == npc.location and not isinstance(p.location, Town)
            ]
            if not targets:
                prey = self.prey_in_sight(npc.location)
                if prey is None:
                    npc.attempt_move(random.choice(list(DIRECTION_VECTORS.values())))
                elif warning := npc.brain.see(prey):
                    events.append(PlayerActionResponse(is_successful=True, target=prey, source=npc, text=warning))
                continue
            target = random.choice(targets)
            deaths = target.deaths
            damage = npc.brain.update(target)
            if damage is None:  # disengaged: it backs off, which isn't worth waking the player up for
                npc.brain.see(target)
                continue
            text = f"{npc.name} hits you for {damage} damage."
            if target.deaths != deaths:  # handle_player_death already sent them home
                text += (
                    f" You black out, and come to in {self.starting_town.name}."
                    + death_toll_text(target)
                )
            events.append(
                PlayerActionResponse(
                    is_successful=True,
                    damage=damage,
                    target=target,
                    source=npc,
                    text=text,
                )
            )
        return events

    def pick_up_remains(self, player: Actors.PlayerCharacter) -> PlayerActionResponse | None:
        """Take whatever a raid death left on the square `player` stands on, if it hasn't rotted away."""
        here = player.location
        pile = here.remains
        if pile is None:
            return None
        here.remains = None
        if pile.expires < self.ticks:
            return None
        player.inventory += pile.items
        player.currency += pile.currency
        whose = "your own" if pile.owner is player else f"{pile.owner.name}'s"
        return PlayerActionResponse(
            is_successful=True, items=pile.items, currency=pile.currency, source=player,
            text=f"You find {whose} things where they fell, and take {pile}.",
        )

    def handle_player_death(self, player: Actors.PlayerCharacter):
        """Send a dead player home. Out past the towns that's a lost raid: whatever they carried stays there,
        and only the stash is safe. A town is safe, so a death in one costs nothing.
        """
        LOG.info(f"Player {player.name} has died")
        here = player.location
        player.last_death_loss = ""
        if not isinstance(here, Town):
            items, currency = player.lose_carried()
            # ponytail: on the Space, so a restart (which regenerates the map) loses every pile. Save them
            # with the NPCs item on ROADMAP.md if that ever bites.
            pile = here.remains
            if pile is None or pile.expires < self.ticks:
                pile = here.remains = Remains(player, [], 0, 0)
            pile.items += items
            pile.currency += currency
            pile.expires = self.ticks + REMAINS_TICKS
            if items or currency:
                player.last_death_loss = f"{Remains(player, items, currency, 0)}, left where you fell at {here}"
        player.deaths += 1
        player.raid_start = None
        player.camping = False
        self.stats.deaths_by_level[here.level if isinstance(here, Wilds) else 0] += 1
        player.location = self.starting_town
        player.revive()


class Store:

    def __init__(self, inventory=None):
        super().__init__()
        self.inventory: List[Equipment] = inventory if inventory is not None else []
        self.price_ratio: float = (
            1.0  # Lower means better buy/sell prices, higher means worse
        )
        # Bought from or sold to since generation. Only these are saved: an untouched store regenerates as it was.
        self.traded: bool = False

    @classmethod
    def generate_store(cls):
        inventory: List[Equipment] = []
        for item_class in Items.FullyImplemented.__subclasses__():
            item = item_class()
            if isinstance(item, Equipment) and random.random() > 0.2:
                inventory.append(item)
        return cls(inventory)

    def get_price(self, item: Equipment) -> int:
        return int(item.base_value * self.price_ratio)

    def sell_item(self, index: int, player_character: Actors.PlayerCharacter) -> bool:
        # Get an instance of the item from the Store's inventory
        try:
            item = self.inventory[index]
        except IndexError:
            return False
        price = self.get_price(item)
        if player_character.currency < price:
            return False
        self.inventory.remove(item)
        self.traded = True
        player_character.currency -= price
        player_character.inventory.append(item)
        return True

    def buy_item(
        self, item: Equipment, player_character: Actors.PlayerCharacter
    ) -> int:
        self.inventory.append(item)
        self.traded = True
        price = int(item.base_value / self.price_ratio)
        player_character.currency += price
        player_character.inventory.remove(item)
        return price


class AStarPathfinder(AStar[Space]):

    def __init__(self, world: World, cost: bool = True):
        self.world = world
        self.cost = cost

    def is_space_valid(self, space: Space):
        return self.world.is_space_valid(space)

    def neighbors(self, node: Space) -> Iterator[Space]:
        directions = ["n", "s", "e", "w"]
        for dir_vector in [DIRECTION_VECTORS[d] for d in directions]:
            potential_space = node + dir_vector
            if self.world.is_coords_valid(potential_space.x, potential_space.y):
                yield self.world.space_at(potential_space.x, potential_space.y)

    def distance_between(self, n1: Space, n2: Space) -> float:
        if self.cost:
            return (sys.maxsize * (self.is_space_valid(n2) is False)) + n2.terrain.cost
        else:
            return 1

    def heuristic_cost_estimate(self, current: Space, goal: Space) -> float:
        """computes the 'direct' distance between two (x,y) tuples"""
        return math.hypot(goal.x - current.x, goal.y - current.y)

    def is_goal_reached(self, current: Space, goal: Space):
        return current == goal
