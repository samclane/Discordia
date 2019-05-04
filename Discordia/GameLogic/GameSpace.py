from __future__ import annotations

import pickle
import random
from abc import ABC
from dataclasses import dataclass
from itertools import product
from typing import List, Tuple, Dict

import numpy
from math import sqrt
from noise import pnoise3

from Discordia import SPRITE_FOLDER
from Discordia.GameLogic import Events, Actors, Items, Weapons
from Discordia.GameLogic.Items import Equipment
from Discordia.GameLogic.StringGenerator import TownNameGenerator, WildsNameGenerator

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
    None: (0, 0)
}


class Terrain(ABC):

    def __str__(self) -> str:
        return self.__class__.__name__

    def __repr__(self) -> str:
        return str(self)

    def __hash__(self):
        return hash(self.id) + hash(self.walkable)

    @property
    def id(self) -> int:
        raise NotImplementedError

    @property
    def walkable(self) -> bool:
        raise NotImplementedError

    @property
    def sprite_path(self) -> str:
        raise NotImplementedError


class NullTerrain(Terrain):
    id = 0
    walkable = False
    sprite_path = SPRITE_FOLDER / "null_tile.png"


class SandTerrain(Terrain):
    id = 1
    walkable = True
    sprite_path = SPRITE_FOLDER / "Terrain" / "sand_center.png"


class GrassTerrain(Terrain):
    id = 2
    walkable = True
    sprite_path = SPRITE_FOLDER / "Terrain" / "grass_center.png"


class WaterTerrain(Terrain):
    id = 3
    walkable = False
    sprite_path = SPRITE_FOLDER / "Terrain" / "water_center.png"


class MountainTerrain(Terrain):
    id = 4
    walkable = True
    sprite_path = SPRITE_FOLDER / "Terrain" / "mountain_center.png"


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
        self.x: int = x
        self.y: int = y
        self.terrain: Terrain = terrain
        self.sprite_path = SPRITE_FOLDER / "null_tile.png"
        self.name = str(self)

    def __str__(self):
        return "({}, {})".format(self.x, self.y)

    def __repr__(self):
        return str((self.x, self.y, self.terrain))

    def __eq__(self, other):
        if isinstance(other, Space):
            return self.x == other.x and self.y == other.y
        else:
            return self.x == other[0] and self.y == other[1]

    def __add__(self, other) -> Space:
        if isinstance(other, Space):
            return Space(self.x + other.x, self.y + other.y, other.terrain)
        else:
            return Space(self.x + int(other[0]), self.y + int(other[1]), NullTerrain())

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

    @classmethod
    def null_space(cls):
        return cls(-1, -1)

    def distance(self, other) -> float:
        if isinstance(other, Space):
            return sqrt(abs(self.x - other.x) ** 2 + abs(self.y - other.y) ** 2)
        else:
            return sqrt(abs(self.x - other[0]) ** 2 + abs(self.y - other[1]) ** 2)


class Town(Space):

    def __init__(self, x: int, y: int, name: str, population: int = 0, industry: IndustryType = NullIndustry(),
                 terrain: Terrain = NullTerrain(), store: Items.Store = None) -> None:
        super(Town, self).__init__(x, y)
        self.name = name
        self.population = population
        self.industry = industry
        self.terrain = terrain
        self.store = store
        self.is_underwater = isinstance(self.terrain, WaterTerrain)
        self.sprite_path = SPRITE_FOLDER / "Structures" / "town_default.png"

    def inn_event(self, character: Actors.PlayerCharacter) -> PlayerActionResponse:
        character.hit_points = character.hit_points_max
        resp = PlayerActionResponse(True, 0, character, f"Your hitpoints have been restored, {character.name}", [], 0)
        return resp


class Base(Town):
    pass  # TODO


class Wilds(Space):

    def __init__(self, x, y, name):
        super(Wilds, self).__init__(x, y)
        self.name: str = name
        self.null_event: Events.Event = Events.Event(1.0, "Null Event")
        self.events: List[Events.Event] = []
        self.events.append(self.null_event)
        self.sprite_path = SPRITE_FOLDER / "Structures" / "wilds_default.png"

    def add_event(self, event: Events.Event):
        self.events.append(event)
        self.null_event.probability -= event.probability

    def run_event(self, pc):
        result = numpy.random.choice(self.events, size=1, p=[event.probability for event in self.events])[0]
        result.run(pc)


@dataclass
class PlayerActionResponse:
    is_successful: bool
    damage: int
    target: Actors.Actor
    text: str
    items: List[Equipment]
    currency: int


@dataclass
class WorldGenerationParameters:
    water: float = .1
    mountains: float = .7
    wilds: float = .1


class World:

    def __init__(self, name: str, width: int, height: int,
                 generation_parameters: WorldGenerationParameters = WorldGenerationParameters()):
        super().__init__()
        self.name: str = name
        self.width: int = width
        self.height: int = height
        self.gen_params: WorldGenerationParameters = generation_parameters
        self.map: List[List[Space]] = [[Space(x, y, Terrain()) for x in range(width)] for y in
                                       range(height)]
        self.towns: List[Town] = []
        self.wilds: List[Wilds] = []
        self.players: List[Actors.PlayerCharacter] = []
        self.npcs: List[Actors.NPC] = []
        self.starting_town: Town = None

        self.generate_map()

    def save_as_file(self):
        pickle.dump(self, open("world.p", "wb"))

    def generate_map(self):
        resolution = 0.2 * (
                (self.width + self.height) / 2)  # I pulled this out of my butt. Gives us decently scaled noise.
        sand_slice = random.random()
        mountain_slice = random.random()
        water_threshold = self.gen_params.water  # Higher water-factor -> more water on map
        mountain_threshold = self.gen_params.mountains  # Lower mountain_thresh -> less mountains
        for x in range(self.width):
            for y in range(self.height):
                # Land and water pass
                self.map[y][x] = Space(x, y, SandTerrain() if abs(
                    pnoise3(x / resolution, y / resolution, sand_slice)) > water_threshold else WaterTerrain())

                # Mountains pass
                if abs(pnoise3(x / resolution, y / resolution, mountain_slice)) > mountain_threshold and self.map[y][
                    x].terrain.walkable:
                    self.map[y][x] = Space(x, y, MountainTerrain())

                if self.starting_town is None and self.is_space_buildable(self.map[y][x]):
                    # Just puts town in first valid spot. Not very interesting.
                    self.add_town(Town(x, y, TownNameGenerator.generate_name()), True)
                elif self.is_space_buildable(self.map[y][x]) and random.random() <= self.gen_params.wilds:
                    self.add_wilds(Wilds(x, y, WildsNameGenerator.generate_name()))

    def is_space_valid(self, space: Space) -> bool:
        return (0 <= space.x <= self.width - 1) and (0 <= space.y <= self.height - 1) and space.terrain.walkable

    def is_space_buildable(self, space: Space) -> bool:
        if not self.is_space_valid(space) or space in self.towns or space in self.wilds:
            return False
        return True

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

    def attack(self, player_character: Actors.PlayerCharacter, direction: Direction = (0, 0)) -> PlayerActionResponse:
        response = PlayerActionResponse(False, 0, None, "No targets found in that direction")
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
        player.location = self.starting_town
        player.hit_points = player.hit_points_max
