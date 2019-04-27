from __future__ import annotations

import pickle
import random
from abc import ABC
from itertools import product
from typing import List, Tuple, Dict, Any

import numpy
from math import sqrt
from noise import pnoise3

from Discordia.GameLogic import Events, Actors, Items, Weapons
from Discordia.GameLogic.StringGenerator import TownNameGenerator


class Terrain(ABC):

    def __str__(self) -> str:
        return self.__class__.__name__

    def __repr__(self) -> str:
        return str(self)

    @property
    def id(self) -> int:
        raise NotImplementedError

    @property
    def walkable(self) -> bool:
        raise NotImplementedError


class NullTerrain(Terrain):
    id = 0
    walkable = False


class SandTerrain(Terrain):
    id = 1
    walkable = True


class GrassTerrain(Terrain):
    id = 2
    walkable = True


class WaterTerrain(Terrain):
    id = 3
    walkable = False


class MountainTerrain(Terrain):
    id = 4
    walkable = True


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


class Space:

    def __init__(self, x: int, y: int, terrain: Terrain = NullTerrain()):
        self.x: int = x
        self.y: int = y
        self.terrain: Terrain = terrain

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

    def inn_event(self, character) -> str:
        character.hit_points = character.HitPointsMax
        return "Your hitpoints have been restored, {}".format(character.name)


class Base(Town):
    pass  # TODO


class Wilds(Space):

    def __init__(self, x, y, name):
        super(Wilds, self).__init__(x, y)
        self.name: str = name
        self.null_event: Events.Event = Events.Event(1.0, "Null Event")
        self.events: List[Events.Event] = []
        self.events.append(self.null_event)

    def add_event(self, event: Events.Event):
        self.events.append(event)
        self.null_event.probability -= event.probability

    def run_event(self, pc):
        result = numpy.random.choice(self.events, size=1, p=[event.probability for event in self.events])[0]
        result.run(pc)


class World:

    def __init__(self, name: str, width: int, height: int, water_height: float = .1, mountain_floor: float = .7):
        super().__init__()
        self.name: str = name
        self.width: int = width
        self.height: int = height
        self.generationParams: Dict[str, float] = {
            "water": water_height,
            "mountains": mountain_floor
        }
        self.map: List[List[Space]] = [[Space(x, y, Terrain()) for x in range(width)] for y in
                                       range(height)]
        self.towns: List[Town] = []
        self.wilds: List[Wilds] = []
        self.players: List[Actors.PlayerCharacter] = []
        self.starting_town: Town = None

        self.generate_map()

    def save_as_file(self):
        pickle.dump(self, open("world.p", "wb"))

    def generate_map(self):
        resolution = 0.2 * (
                (self.width + self.height) / 2)  # I pulled this out of my butt. Gives us decently scaled noise.
        sand_slice = random.random()
        mountain_slice = random.random()
        water_threshold = self.generationParams["water"]  # Higher water-factor -> more water on map
        mountain_threshold = self.generationParams["mountains"]  # Lower mountain_thresh -> less mountains
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

    def is_space_valid(self, space: Space) -> bool:
        return (0 < space.x < self.width - 1) and (0 < space.y < self.height - 1) and space.terrain.walkable

    def is_space_buildable(self, space: Space) -> bool:
        if not self.is_space_valid(space) or space in self.towns or space in self.wilds:
            return False
        return True

    def get_adjacent_spaces(self, space, sq_range: int = 1) -> List[Space]:
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

    def add_actor(self, actor, space=None):
        if isinstance(actor, Actors.PlayerCharacter):
            actor.location = self.starting_town
            self.players.append(actor)
        elif space and self.is_space_valid(space):
            actor.Location = space

    def attack(self, player_character: Actors.PlayerCharacter, direction: Tuple[int, int] = (0, 0)) -> Dict[str, Any]:
        response: Dict[str, Any] = {
            "success": False,
            "damage": 0,
            "target": None,
            "fail_reason": "No targets found in that direction."
        }
        loc: Space = player_character.location
        dmg: int = player_character.weapon.damage
        while dmg > 0:
            if isinstance(player_character.weapon, Weapons.ProjectileWeapon) and player_character.weapon.is_empty:
                response["fail_reason"] = "Your currently equipped weapon is empty!"
                break
            targets = [player for player in self.players if player != player_character and player.location == loc]
            if len(targets):
                target: Actors.PlayerCharacter = random.choice(targets)
                player_character.weapon.on_damage()
                target.take_damage(dmg)
                response["success"] = True
                response["damage"] = dmg
                response["target"] = target
                break
            else:
                if isinstance(player_character.weapon, Weapons.MeleeWeapon):
                    response["fail_reason"] = "No other players in range of your Melee Weapon."
                    break
                if direction == (0, 0):
                    response["fail_reason"] = "No other players in current square. " \
                                              "Specify a direction (n,s,e,w,ne,se,sw,nw))"
                    break
                loc += direction
                loc = self.map[loc.y][loc.x]
                dmg = player_character.weapon.calc_damage(player_character.location.distance(loc))
        return response

    def handle_player_death(self, player: Actors.PlayerCharacter):
        player.location = self.starting_town
        player.hit_points = player.hit_points_max
