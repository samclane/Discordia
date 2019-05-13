from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Tuple, List, Dict, Any, Union

from Discordia import SPRITE_FOLDER
from Discordia.GameLogic import GameSpace, Items, Weapons
from Discordia.GameLogic.Items import Equipment


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
    """
    Defines an interface to interact with all generic Actor objects
    """

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

    @property
    def sprite_path(self) -> str:
        raise NotImplementedError


class Actor(AbstractActor, ABC):

    def __init__(self, parent_world: GameSpace.World, hp: int = 0, name: str = "<Unnamed>",
                 body_type: BodyType = Humanoid()):
        self.parent_world = parent_world
        self._hit_points = self.hit_points_max = hp
        self.name = name
        self.body_type = body_type
        self.location: GameSpace.Space = GameSpace.Space.null_space()
        self.fov_default = 2
        self.last_time_moved = 0

    def attempt_move(self, shift: Tuple[int, int]) -> bool:
        new_space = self.location + shift
        new_space = self.parent_world.map[new_space.y][new_space.x]
        if not self.parent_world.is_space_valid(new_space):
            return False
        self.location = new_space
        map_space = self.parent_world.map[self.location.y][self.location.x]
        if isinstance(map_space, GameSpace.Wilds):
            map_space.run_event(pc=self)
        return True

    @property
    def hit_points(self) -> int:
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

    @property
    def sprite_path(self) -> str:
        return SPRITE_FOLDER / "Actors" / "null_actor.png"

    @property
    def sprite_path_string(self) -> str:
        return str(self.sprite_path)


class NPC(Actor, ABC):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.inventory: List[Items.Equipment] = []
        self.flavor_text: str = "<No Flavor Text Set>"

    def on_death(self) -> List[Items.Equipment]:
        self.location: GameSpace.Space = GameSpace.Space.null_space()
        return self.inventory


class Enemy(NPC):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.base_attack: int = 0
        self.abilities: Dict[Any] = {}


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.class_: PlayerClass = WandererClass()
        self._hit_points = self.hit_points_max = self.class_.hit_points_max_base
        self.equipment_set: Items.EquipmentSet = Items.EquipmentSet()
        self.fov: int = self.fov_default
        self.inventory: List[Items.Equipment] = []
        self.currency: int = 1000

    @property
    def weapon(self) -> Union[Weapons.Weapon, None]:
        wep = self.equipment_set.main_hand
        if not isinstance(wep, Weapons.Weapon):
            return None
        return wep

    @property
    def has_weapon_equipped(self) -> bool:
        return self.weapon is not None

    def equip(self, equipment: Equipment):
        self.equipment_set.equip(equipment)
        equipment.on_equip(self)

    def unequip(self, equipment: Equipment):
        self.equipment_set.unequip(equipment)
        equipment.on_unequip(self)

    def take_damage(self, damage: int):
        damage -= self.equipment_set.armor_count
        self.hit_points -= damage

    def on_death(self):
        self.parent_world.handle_player_death(self)
