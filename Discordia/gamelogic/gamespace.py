from __future__ import annotations

import pickle
import random
from abc import ABC
from itertools import product
from math import sqrt
from typing import List, Tuple, Dict, Any

import numpy
from noise import pnoise3

from Discordia.gamelogic import events, actors, items, weapons


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
    def Name(self) -> str:
        raise NotImplementedError


class NullIndustry(IndustryType):
    Name = "None"


class MiningIndustry(IndustryType):
    Name = "Mining"


class FarmingIndustry(IndustryType):
    Name = "Farming"


class SmithingIndustry(IndustryType):
    Name = "Smithing"


class WoodworkingIndustry(IndustryType):
    Name = "Woodworking"


class Space:

    def __init__(self, x: int, y: int, terrain: Terrain = NullTerrain()):
        self.X: int = x
        self.Y: int = y
        self.Terrain: Terrain = terrain

    def __str__(self):
        return "({}, {})".format(self.X, self.Y)

    def __repr__(self):
        return str((self.X, self.Y, self.Terrain))

    def __eq__(self, other):
        if isinstance(other, Space):
            return self.X == other.X and self.Y == other.Y
        else:
            return self.X == other[0] and self.Y == other[1]

    def __add__(self, other) -> Space:
        if isinstance(other, Space):
            return Space(self.X + other.X, self.Y + other.Y, other.Terrain)
        else:
            return Space(self.X + int(other[0]), self.Y + int(other[1]), NullTerrain())

    def __iter__(self):
        yield self.X
        yield self.Y

    def __getitem__(self, item) -> int:
        if item == 0:
            return self.X
        if item == 1:
            return self.Y
        raise ValueError("Item should be either 0 or 1")

    @classmethod
    def null_space(cls):
        return cls(-1, -1)

    def distance(self, other) -> float:
        if isinstance(other, Space):
            return sqrt(abs(self.X - other.X) ** 2 + abs(self.Y - other.Y) ** 2)
        else:
            return sqrt(abs(self.X - other[0]) ** 2 + abs(self.Y - other[1]) ** 2)


class Town(Space):
    Name: str
    Population: int
    Industry: IndustryType

    def __init__(self, x: int, y: int, name: str, population: int = 0, industry: IndustryType = NullIndustry(),
                 terrain: Terrain = NullTerrain(), store: items.Store = None) -> None:
        super(Town, self).__init__(x, y)
        self.Name = name
        self.Population = population
        self.Industry = industry
        self.Terrain = terrain
        self.Store = store
        self.isUnderwater = isinstance(self.Terrain, WaterTerrain)

    def innEvent(self, pc) -> str:
        pc.hit_points = pc.HitPointsMax
        return "Your hitpoints have been restored, {}".format(pc.name)


class Base(Town):
    pass  # TODO


class Wilds(Space):

    def __init__(self, x, y, name):
        super(Wilds, self).__init__(x, y)
        self.name: str = name
        self.null_event: events.Event = events.Event(1.0, "Null Event")
        self.events: List[events.Event] = []
        self.events.append(self.null_event)

    def add_event(self, event: events.Event):
        self.events.append(event)
        self.null_event.probability -= event.probability

    def run_event(self, pc):
        n = 1
        result = numpy.random.choice(self.events, size=n, p=[event.probability for event in self.events])[0]
        result.run(pc)


class World:
    Name: str
    Width: int
    Height: int
    Map: List[List[Space]]

    def __init__(self, name: str, width: int, height: int, starting_town: Town, water_height: float = .1,
                 mountain_floor: float = .7):
        super().__init__()
        self.Name = name
        self.Width = width
        self.Height = height
        self.generationParams: Dict[str, float] = {
            "water": water_height,
            "mountains": mountain_floor
        }
        self.Map = [[Space(x, y, Terrain()) for x in range(width)] for y in
                    range(height)]
        self.Towns: List[Town] = []
        self.Wilds: List[Wilds] = []
        self.Players: List[actors.PlayerCharacter] = []
        self.StartingTown: Town = starting_town

        self.generate_map()

    def save_as_file(self):
        pickle.dump(self, open("world.p", "wb"))

    def generate_map(self):
        resolution = 0.2 * (
                (self.Width + self.Height) / 2)  # I pulled this out of my butt. Gives us decently scaled noise.
        sand_slice = random.random()
        mountain_slice = random.random()
        water_threshold = self.generationParams["water"]  # Higher water-factor -> more water on map
        mountain_threshold = self.generationParams["mountains"]  # Lower mountain_thresh -> less mountains
        for x in range(self.Width):
            for y in range(self.Height):
                # Land and water pass
                self.Map[y][x] = Space(x, y, SandTerrain() if abs(
                    pnoise3(x / resolution, y / resolution, sand_slice)) > water_threshold else WaterTerrain())

                # Mountains pass
                if abs(pnoise3(x / resolution, y / resolution, mountain_slice)) > mountain_threshold and self.Map[y][
                    x].Terrain.walkable:
                    self.Map[y][x] = Space(x, y, MountainTerrain())

    def is_space_valid(self, space: Space) -> bool:
        return (0 < space.X < self.Width - 1) and (0 < space.Y < self.Height - 1) and space.Terrain.walkable

    def is_space_buildable(self, space: Space):
        assert self.is_space_valid(space), "Somehow trying to build on an impossible spot."
        if space in self.Towns or space in self.Wilds:
            return False
        return True

    def get_adjacent_spaces(self, space, sq_range: int = 1) -> List[Space]:
        fov = list(range(-sq_range, sq_range + 1))
        steps = product(fov, repeat=2)
        coords = (tuple(c + d for c, d in zip(space, delta)) for delta in steps)
        return [self.Map[j][i] for i, j in coords if (0 <= i < self.Width) and (0 <= j < self.Height)]

    def add_town(self, town: Town, is_starting_town: bool = False):
        self.Towns.append(town)
        town.Terrain = self.Map[town.Y][town.X].Terrain
        self.Map[town.Y][town.X] = town
        if is_starting_town:
            self.StartingTown = town

    def add_wilds(self, wilds: Wilds):
        self.Wilds.append(wilds)
        wilds.Terrain = self.Map[wilds.Y][wilds.X].Terrain
        self.Map[wilds.Y][wilds.X] = wilds

    def add_actor(self, actor, space=None):
        if isinstance(actor, actors.PlayerCharacter):
            actor.location = self.StartingTown
            self.Players.append(actor)
        elif space and self.is_space_valid(space):
            actor.Location = space

    def attack(self, player_character: actors.PlayerCharacter, direction: Tuple[int, int] = (0, 0)) -> Dict[str, Any]:
        response: Dict[str, Any] = {
            "success": False,
            "damage": 0,
            "target": None,
            "fail_reason": "No targets found in that direction."
        }
        loc: Space = player_character.location
        dmg: int = player_character.weapon.damage
        while dmg > 0:
            if isinstance(player_character.weapon, weapons.ProjectileWeapon) and player_character.weapon.is_empty:
                response["fail_reason"] = "Your currently equipped weapon is empty!"
                break
            targets = [player for player in self.Players if player != player_character and player.location == loc]
            if len(targets):
                target: actors.PlayerCharacter = random.choice(targets)
                player_character.weapon.on_damage()
                target.take_damage(dmg)
                response["success"] = True
                response["damage"] = dmg
                response["target"] = target
                break
            else:
                if isinstance(player_character.weapon, weapons.MeleeWeapon):
                    response["fail_reason"] = "No other players in range of your Melee Weapon."
                    break
                if direction == (0, 0):
                    response["fail_reason"] = "No other players in current square. " \
                                              "Specify a direction (n,s,e,w,ne,se,sw,nw))"
                    break
                loc += direction
                loc = self.Map[loc.Y][loc.X]
                dmg = player_character.weapon.calc_damage(player_character.location.distance(loc))
        return response

    def handle_player_death(self, player_id):
        player = [pc for pc in self.Players if pc.user_id == player_id][0]
        player.location = self.StartingTown
        player.hit_points = player.HitPointsMax
