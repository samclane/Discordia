from __future__ import annotations

import logging
import pickle
import random
import sys
from abc import ABC
from dataclasses import dataclass, field
from itertools import product
from pathlib import Path
from typing import List, Tuple, Dict, Iterator, Union

import math
import numpy as np
from astar import AStar
from math import sqrt
from noise import pnoise3

from Discordia import SPRITE_FOLDER
from Discordia.GameLogic import Events, Actors, Items, Weapons
from Discordia.GameLogic.Items import Equipment
from Discordia.GameLogic.Procedural import normal, WorldGenerationParameters
from Discordia.GameLogic.StringGenerator import TownNameGenerator, WildsNameGenerator

LOG = logging.getLogger("Discordia.GameLogic.GameSpace")

Direction = Tuple[int, int]

DIRECTION_VECTORS: Dict[str, Direction] = {
    'n': (0, -1),
    's': (0, 1),
    'e': (1, 0),
    'w': (-1, 0),
    'ne': (1, -1),
    'se': (1, 1),
    'sw': (-1, 1),
    'nw': (-1, -1),
    'center': (0, 0),
    None: (0, 0)
}


def bitmask_to_orientation(value: int) -> str:
    if 0xff & value == 0xff or 0b01011010 & value == 0b01011010:
        return 'center'
    if 0b01011000 & value == 0b01011000:
        return 'n'
    if 0b01001010 & value == 0b01001010:
        return 'e'
    if 0b00011010 & value == 0b00011010:
        return 's'
    if 0b01010010 & value == 0b01010010:
        return 'w'
    if 0b01010000 & value == 0b01010000:
        return 'nw'
    if 0b01001000 & value == 0b01001000:
        return 'ne'
    if 0b00010010 & value == 0b00010010:
        return 'sw'
    if 0b00001010 & value == 0b00001010:
        return 'se'
    else:
        return 'center'


class Terrain(ABC):
    _orientation: str = "center"

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
    def orientation(self) -> str:
        return self._orientation

    @orientation.setter
    def orientation(self, value: str):
        value = value.lower()
        if value not in DIRECTION_VECTORS.keys():
            raise ValueError("Invalid direction given: ", value)
        self._orientation = value

    @property
    def sprite_path(self) -> Path:
        return SPRITE_FOLDER / "Terrain" / f"{self.name}_{self.orientation}.png"

    @property
    def sprite_path_string(self) -> str:
        return str(self.sprite_path)

    @property
    def cost(self) -> int:
        # Unimplemented terrain returns "infinite"
        return sys.maxsize

    @property
    def buildable(self):
        raise NotImplementedError

    @property
    def layer(self):
        """ Basically the Z value of the terrain; how high it is. 0 is sea level. -1 is null-level """
        return -1


class NullTerrain(Terrain):
    walkable = False
    name = "null_tile"
    buildable = False


class SandTerrain(Terrain):
    walkable = True
    name = "sand"
    cost = 2
    buildable = True
    layer = 1


class GrassTerrain(Terrain):
    walkable = True
    name = "grass"
    cost = 1
    buildable = True
    layer = 1


class WaterTerrain(Terrain):
    walkable = True
    name = "water"
    cost = 5
    buildable = False
    layer = 0

    @property
    def orientation(self) -> str:
        return 'center'

    @orientation.setter
    def orientation(self, value):
        pass


class MountainTerrain(Terrain):
    walkable = True
    name = "mountain"
    cost = 8
    buildable = False
    layer = 2


class IndustryType(ABC):
    @property
    def name(self) -> str:
        raise NotImplementedError


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


class Space(ABC):

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
        return self.x == other[0] and self.y == other[1]

    def __add__(self, other) -> Space:
        if isinstance(other, Space):
            return Space(max(self.x + other.x, 0), max(self.y + other.y, 0), other.terrain)
        else:
            return Space(max(self.x + int(other[0]), 0), max(self.y + int(other[1]), 0), NullTerrain())

    def __sub__(self, other):
        if isinstance(other, Space):
            return Space(max(self.x - other.x, 0), max(self.y - other.y, 0), other.terrain)
        else:
            return Space(max(self.x - int(other[0]), 0), max(self.y - int(other[1]), 0), NullTerrain())

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
        return hash(self.x) + (10 * hash(self.y)) + (100 * hash(self.terrain))

    @property
    def sprite_path(self):
        return self.terrain.sprite_path

    @property
    def sprite_path_string(self):
        return str(self.sprite_path)

    def distance(self, other) -> float:
        return sqrt(abs(self.x - other[0]) ** 2 + abs(self.y - other[1]) ** 2)

    def closest(self, space_list: List[Union[Space, Tuple[int, int]]], size=1):
        """ Returns a list of the closest spaces out of space_list, in decreasing order """
        return sorted(space_list, key=lambda o: self.distance(o))[0:size - 1]


class Town(Space):

    def __init__(self, x: int, y: int, name: str, population: int = 0, industry: IndustryType = NullIndustry(),
                 terrain: Terrain = NullTerrain(), store: Store = None) -> None:
        super(Town, self).__init__(x, y, terrain)
        self.name: str = name
        self.population: int = population
        self.industry: IndustryType = industry
        self.store: Store = store
        self.is_underwater: bool = isinstance(self.terrain, WaterTerrain)

    @classmethod
    def generate_town(cls, x, y, terrain):
        name = TownNameGenerator.generate_name()
        population = random.randint(1, 1000)
        industry = random.choice(IndustryType.__subclasses__())
        store = Store.generate_store()
        return cls(x, y, name, population, industry, terrain, store)

    def inn_event(self, character: Actors.PlayerCharacter) -> PlayerActionResponse:
        character.hit_points = character.hit_points_max
        resp = PlayerActionResponse(True, 0, character, f"Your hitpoints have been restored, {character.name}", [], 0,
                                    source=character)
        return resp

    @property
    def sprite_path(self):
        return SPRITE_FOLDER / "Structures" / "town_default.png"


class Base(Town):
    pass  # TODO "Base" Class


class Wilds(Space):

    def __init__(self, x, y, name, terrain: Terrain = NullTerrain()):
        super().__init__(x, y, terrain)
        self.name: str = name
        self.null_event: Events.Event = Events.Event.null_event()
        self.events: List[Events.Event] = []
        self.events.append(self.null_event)

    def add_event(self, event: Events.Event):
        if event.probability > self.null_event.probability:
            event.probability = self.null_event.probability
        self.events.append(event)
        self.null_event.probability -= event.probability
        assert self.null_event.probability >= 0

    def run_event(self, player) -> List[PlayerActionResponse]:
        chosen_event = np.random.choice(self.events, size=1, p=[event.probability for event in self.events])[0]
        results = chosen_event.run(player)
        if results is None:
            results = [PlayerActionResponse(source=player)]
        return list(results)

    @classmethod
    def generate(cls, x, y, terrain: Terrain, level) -> Wilds:
        name = WildsNameGenerator.generate_name()
        wilds = cls(x, y, name, terrain)
        for _ in range(level):
            event = Events.generate_event(level)
            wilds.add_event(event)
        return wilds

    @property
    def sprite_path(self):
        return SPRITE_FOLDER / "Structures" / "wilds_default.png"


@dataclass
class PlayerActionResponse:
    is_successful: bool = False
    damage: int = 0
    target: Actors.Actor = None
    text: str = ""
    items: List[Equipment] = field(default_factory=list)
    currency: int = 0
    source: Actors.Actor = None

    @property
    def failed(self):
        return not self.is_successful


class World:

    def __init__(self, name: str, width: int, height: int,
                 generation_parameters: WorldGenerationParameters = WorldGenerationParameters(), seed=None):
        super().__init__()
        self.name: str = name
        self.width: int = width
        self.height: int = height
        self.gen_params: WorldGenerationParameters = generation_parameters
        self.map: List[List[Space]] = [[Space(x, y, NullTerrain()) for x in range(width)] for y in
                                       range(height)]
        self.towns: List[Town] = []
        self.wilds: List[Wilds] = []
        self.players: List[Actors.PlayerCharacter] = []
        self.npcs: List[Actors.NPC] = []
        self.starting_town: Town = Town.generate_town(0, 0, NullTerrain())

        if seed:
            random.seed(seed)
            np.random.seed(seed)
        self.generate_map()

    def save_as_file(self):
        pickle.dump(self, open("world.p", "wb"))

    def generate_map(self):
        LOG.info("Generating Map...")

        # Get parameters
        resolution = self.gen_params.resolution_constant * (
                (self.width + self.height) / 2)  # I pulled this out of my butt. Gives us decently scaled noise.
        sand_slice = random.random()
        mountain_slice = random.random()
        grass_slice = random.random()
        water_threshold = self.gen_params.water  # Higher factor -> more Spaces on the map
        mountain_threshold = self.gen_params.mountains
        grass_threshold = self.gen_params.grass

        # First pass
        for x in range(self.width):
            for y in range(self.height):
                # Land and water pass
                self.map[y][x] = Space(x, y, SandTerrain() if abs(
                    pnoise3(x / resolution, y / resolution, sand_slice)) > water_threshold else WaterTerrain())

                # Mountains pass
                if abs(pnoise3(x / resolution, y / resolution, mountain_slice)) > mountain_threshold and self.map[y][
                    x].terrain.walkable:
                    self.map[y][x] = Space(x, y, MountainTerrain())

                # Grass pass
                if abs(pnoise3(x / resolution, y / resolution, grass_slice)) > grass_threshold:
                    self.map[y][x] = Space(x, y, GrassTerrain())

                # Town and Wilds pass
                if self.map[y][x].terrain.buildable:
                    if random.random() <= self.gen_params.towns:
                        # Just puts town in first valid spot. Not very interesting.
                        self.add_town(Town.generate_town(x, y, terrain=self.map[y][x].terrain))
                    elif random.random() <= self.gen_params.wilds:
                        self.add_wilds(
                            Wilds.generate(x, y, self.map[y][x].terrain,
                                           normal(sqrt(self.starting_town.distance((x, y))), integer=True,
                                                  positive=True)))

        # Second (orientation) pass
        # https://gamedevelopment.tutsplus.com/tutorials/how-to-use-tile-bitmasking-to-auto-tile-your-level-layouts--cms-25673
        for x in range(1, self.width - 1):
            for y in range(1, self.height - 1):
                space: Space = self.map[y][x]

                # Bitmask
                value = 0
                for bit, neighbor in enumerate([DIRECTION_VECTORS.get(key) for key in ['nw', 'n', 'ne',
                                                                                       'w', 'e', 'sw',
                                                                                       's', 'se']]):
                    ix, iy = space + neighbor
                    if self.map[iy][ix].terrain.layer == space.terrain.layer:
                        value += pow(2, bit)

                if value != 0:
                    space.terrain.orientation = bitmask_to_orientation(value)

        self.starting_town = random.choice(self.towns)
        LOG.info("Generation finished")

    def is_space_valid(self, space: Space) -> bool:
        return (0 <= space.x <= self.width - 1) and (0 <= space.y <= self.height - 1) and space.terrain.walkable

    def is_coords_valid(self, x: int, y: int):
        if (0 <= x <= self.width - 1) and (0 <= y <= self.height - 1):
            return self.map[y][x].terrain.walkable
        return False

    def is_space_buildable(self, space: Space) -> bool:
        # FIXME Ugly function
        if space.terrain.buildable:
            if not self.is_space_valid(space) or space in self.towns or space in self.wilds:
                return False
            return True
        return False

    def get_adjacent_spaces(self, space: Space, sq_range: int = 1) -> List[Space]:
        fov = list(range(-sq_range, sq_range + 1))
        steps = product(fov, repeat=2)
        coords = (tuple(c + d for c, d in zip(space, delta)) for delta in steps)
        return [self.map[j][i] for i, j in coords if (0 <= i < self.width) and (0 <= j < self.height)]

    def add_town(self, town: Town, is_starting_town: bool = False):
        self.towns.append(town)
        town.terrain = self.map[town.y][town.x].terrain
        self.map[town.y][town.x] = town
        if is_starting_town:
            self.starting_town = town

    def add_wilds(self, wilds: Wilds):
        self.wilds.append(wilds)
        wilds.terrain = self.map[wilds.y][wilds.x].terrain
        self.map[wilds.y][wilds.x] = wilds

    def add_actor(self, actor: Actors.Actor, space: Space = None):
        if isinstance(actor, Actors.PlayerCharacter):
            actor.location = self.starting_town
            self.players.append(actor)
        elif space and self.is_space_valid(space):
            actor.location = space
            self.npcs.append(actor)

    def get_npcs_in_region(self, spaces: List[Space]) -> List[Actors.NPC]:
        npc_locations: Dict[Actors.NPC, Space] = {npc: npc.location for npc in self.npcs}
        common_locations: List[Space] = list(set(npc_locations.values()).intersection(spaces))
        npcs: List[Actors.NPC] = [npc for npc in self.npcs if npc.location in common_locations]
        return npcs

    def get_players_in_region(self, spaces: List[Space]) -> List[Actors.PlayerCharacter]:
        player_locations: Dict[Actors.PlayerCharacter, Space] = {player: player.location for player in self.players}
        common_locations: List[Space] = list(set(player_locations.values()).intersection(spaces))
        players: List[Actors.PlayerCharacter] = [player for player in self.players if
                                                 player.location in common_locations]
        return players

    def pvp_attack(self, player_character: Actors.PlayerCharacter,
                   direction: Direction = (0, 0)) -> PlayerActionResponse:
        response = PlayerActionResponse(text="No targets found in that direction", source=player_character)
        loc: Space = player_character.location
        dmg: int = player_character.weapon.damage
        while dmg > 0:
            if isinstance(player_character.weapon, Weapons.ProjectileWeapon) and player_character.weapon.is_empty:
                response.text = "Your currently equipped weapon is empty!"
                break
            targets = [player for player in self.players if player != player_character and player.location == loc]
            if len(targets):
                target: Actors.PlayerCharacter = random.choice(targets)
                player_character.weapon.on_damage()
                target.take_damage(dmg)
                response.is_successful = True
                response.damage = dmg
                response.target = target
                break
            else:
                if isinstance(player_character.weapon, Weapons.MeleeWeapon):
                    response.text = "No other players in range of your Melee Weapon."
                    break
                if direction == (0, 0):
                    response.text = "No other players in current square. " \
                                    "Specify a direction (n,s,e,w,ne,se,sw,nw))"
                    break
                loc += direction
                loc = self.map[loc.y][loc.x]
                dmg = player_character.weapon.calc_damage(player_character.location.distance(loc))
        return response

    def handle_player_death(self, player: Actors.PlayerCharacter):
        LOG.info(f"Player {player.name} has died")
        player.location = self.starting_town
        player.hit_points = player.hit_points_max


class Store:

    def __init__(self, inventory=None):
        super().__init__()
        self.inventory: List[Equipment] = inventory if inventory is not None else []
        self.price_ratio: float = 1.0  # Lower means better buy/sell prices, higher means worse

    @classmethod
    def generate_store(cls):
        inventory: List[Equipment] = []
        for item_class in Items.FullyImplemented.__subclasses__():
            item: Equipment = item_class()
            if random.random() > 0.2:
                inventory.append(item)
        return cls(inventory)

    def get_price(self, item: Equipment) -> float:
        return item.base_value * self.price_ratio

    def sell_item(self, index: int, player_character: Actors.PlayerCharacter) -> bool:
        # Get an instance of the item from the Store's inventory
        try:
            item = [item for item in self.inventory if issubclass(type(item), type(list(set(self.inventory))[index]))][
                0]
        except IndexError:
            return False
        price = self.get_price(item)
        if player_character.currency < price:
            return False
        self.inventory.remove(item)
        player_character.currency -= price
        player_character.inventory.append(item)
        return True

    def buy_item(self, item: Equipment, player_character: Actors.PlayerCharacter) -> float:
        self.inventory.append(item)
        price = item.base_value / self.price_ratio
        player_character.currency += price
        player_character.inventory.remove(item)
        return price


class AStarPathfinder(AStar):

    def __init__(self, world: World, cost: bool = True):
        self.world = world
        self.cost = cost

    @property
    def map(self):
        return self.world.map

    def is_space_valid(self, space: Space):
        return self.world.is_space_valid(space)

    def neighbors(self, space: Space) -> Iterator[Space]:
        directions = ['n', 's', 'e', 'w']
        for dir_vector in [DIRECTION_VECTORS.get(d) for d in directions]:
            potential_space = space + dir_vector
            if self.world.is_coords_valid(potential_space.x, potential_space.y):
                map_space = self.map[potential_space.y][potential_space.x]
                yield map_space

    def distance_between(self, first: Space, second: Space) -> float:
        if self.cost:
            return (sys.maxsize * (self.is_space_valid(second) is False)) + second.terrain.cost
        else:
            return 1

    def heuristic_cost_estimate(self, current: Space, goal: Space) -> float:
        """computes the 'direct' distance between two (x,y) tuples"""
        return math.hypot(goal.x - current.x, goal.y - current.y)

    def is_goal_reached(self, current: Space, goal: Space):
        return current == goal
