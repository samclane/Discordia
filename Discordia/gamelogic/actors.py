from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Tuple, List, Dict, Any

from Discordia.gamelogic import gamespace, items, weapons


class BodyType(ABC):

    @property
    def size_code(self):
        raise NotImplementedError


class Humanoid(BodyType):

    @property
    def size_code(self):
        return 1


class SmallAnimal(BodyType):

    @property
    def size_code(self):
        return 2


class LargeAnimal(BodyType):

    @property
    def size_code(self):
        return 3


class Monstrosity(BodyType):

    @property
    def size_code(self):
        return 4


class Mechanical(BodyType):

    @property
    def size_code(self):
        return 5


class AbstractActor(ABC):

    def attempt_move(self, shift: Tuple[int, int]) -> bool:
        pass

    @property
    def hit_points(self):
        raise NotImplementedError

    @hit_points.setter
    def hit_points(self, value: int):
        pass

    @property
    def is_dead(self):
        raise NotImplementedError

    @abstractmethod
    def on_death(self):
        pass


class Actor(AbstractActor, ABC):

    def __init__(self, parent_world: gamespace.World, hp: int = 0, name: str = "", body_type: BodyType = Humanoid()):
        self.parent_world = parent_world
        self._hit_points = self.hit_points_max = hp
        self.name = name
        self.body_type = body_type
        self.location: gamespace.Space = gamespace.Space.null_space()
        self.fov_default = 1
        self.last_time_moved = 0

    def attempt_move(self, shift: Tuple[int, int]) -> bool:
        new_space = self.location + shift
        new_space = self.parent_world.Map[new_space.Y][new_space.X]
        if not self.parent_world.is_space_valid(new_space):
            return False
        else:
            self.location = new_space
            map_space = self.parent_world.Map[self.location.Y][self.location.X]
            if isinstance(map_space, gamespace.Wilds):
                map_space.run_event(pc=self)
            return True

    @property
    def hit_points(self):
        return self._hit_points

    @hit_points.setter
    def hit_points(self, value):
        self._hit_points = min(max(value, 0), self.hit_points_max)
        if self._hit_points == 0:
            self.on_death()

    @property
    def is_dead(self) -> bool:
        return self.hit_points <= 0

    @abstractmethod
    def on_death(self):
        pass


class NPC(Actor, ABC):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.Inventory: [] = []
        self.FlavorText = ""


class Enemy(NPC):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.base_attack: int = 0
        self.abilities: Dict[Any] = {}
        self.loot: List[items.Equipment] = []

    def on_death(self):
        self.location: gamespace.Space = gamespace.Space.null_space()
        return self.loot


class PlayerClass(ABC):

    @property
    def name(self) -> str:
        raise NotImplementedError

    @property
    def hit_points_max_base(self) -> int:
        raise NotImplementedError

    def __str__(self) -> str:
        return self.name


class WandererClass(PlayerClass):
    """ Default player class with nothing special. """
    name = "Wanderer"
    hit_points_max_base = 50


class PlayerCharacter(Actor):

    def __init__(self, user_id, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.user_id: str = user_id
        if self.name is None:
            self.name: str = "Unnamed"
        self.class_: PlayerClass = WandererClass()
        self._hit_points = self.HitPointsMax = self.class_.hit_points_max_base
        self.equipment_set: items.EquipmentSet = items.EquipmentSet()
        self.fov: int = self.fov_default
        self.inventory: List[items.Equipment] = []
        self.currency: int = 1000

    @property
    def weapon(self):
        w = self.equipment_set.main_hand
        if not isinstance(w, weapons.Weapon):
            return None
        else:
            return w

    @property
    def has_weapon_equipped(self):
        return self.weapon is not None

    def equip(self, equipment):
        self.equipment_set.equip(equipment)
        equipment.on_equip(self)

    def unequip(self, equipment):
        self.equipment_set.unequip(equipment)
        equipment.on_unequip(self)

    def take_damage(self, damage: int):
        damage -= self.equipment_set.armor_count
        self.hit_points -= damage
        # TODO Finish this

    def on_death(self):
        self.parent_world.handle_player_death(self.user_id)
