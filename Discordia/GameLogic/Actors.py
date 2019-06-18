from __future__ import annotations

import random
from abc import ABC, abstractmethod
from typing import Tuple, List, Union
from enum import Enum, auto

from Discordia import SPRITE_FOLDER
from Discordia.GameLogic import GameSpace, Items, Weapons, Procedural
from Discordia.GameLogic.Items import Equipment, MainHandEquipment, OffHandEquipment
from Discordia.GameLogic.StringGenerator import CharacterNameGenerator


class BodySize(Enum):
    SmallAnimal = auto()
    Humanoid = auto()
    LargeAnimal = auto()
    Monstrosity = auto()


class BodyType(ABC):
    """
    Determines the physical size of the Actor.
    """

    @property
    def size_code(self) -> int:
        """
        Can be used to check if one actor is larger than another. Larger size_codes -> larger Actors.
        """
        return BodySize[self.__class__.__name__].value

    def __str__(self) -> str:
        return self.__class__.__name__


# TODO Random sprite generation (base templates on BodySize)
class SmallAnimal(BodyType):
    pass


class Humanoid(BodyType):
    pass


class LargeAnimal(BodyType):
    pass


class Monstrosity(BodyType):
    pass


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

    def __init__(self, parent_world: GameSpace.World, hp: int = 0, name: str = "<NONE>",
                 body_type: BodyType = Humanoid()):
        self.parent_world = parent_world
        self._hit_points = self.hit_points_max = hp
        self.name = name
        self.body_type = body_type
        self.location = None
        self.fov_default = 2
        self.last_time_moved = 0

    def __str__(self):
        return self.name

    def __repr__(self):
        attrdict = []
        for attr in [a for a in self.__dict__ if not a.startswith('__')]:
            attrdict.append(f"{attr}: {getattr(self, attr)}")
        return f"{self.__class__.__name__}(" + ', '.join(attrdict) + ')'

    def attempt_move(self, shift: Tuple[int, int]) -> List[GameSpace.PlayerActionResponse]:
        new_coords = self.location + shift
        if not self.parent_world.is_coords_valid(new_coords.x, new_coords.y):
            return [GameSpace.PlayerActionResponse(is_successful=False, source=self)]
        self.location = self.parent_world.map[new_coords.y][new_coords.x]
        if isinstance(self.location, GameSpace.Wilds) and isinstance(self, PlayerCharacter):
            return self.location.run_event(player=self)
        else:
            return [GameSpace.PlayerActionResponse(is_successful=True, source=self)]

    @property
    def hit_points(self) -> int:
        return self._hit_points

    @hit_points.setter
    def hit_points(self, value):
        self._hit_points = min(max(value, 0), self.hit_points_max)
        if self._hit_points <= 0:
            self.on_death()

    def take_damage(self, damage: int):
        self.hit_points -= damage

    @property
    def is_dead(self) -> bool:
        return self.hit_points <= 0

    def on_death(self):
        pass

    @property
    def sprite_path(self) -> str:
        return SPRITE_FOLDER / "Actors" / "null_actor.png"

    @property
    def sprite_path_string(self) -> str:
        return str(self.sprite_path)


class NPC(Actor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.inventory: List[Items.Equipment] = []
        self.flavor_text: str = "<NONE>"
        self.base_attack = 1

    def on_death(self) -> List[Items.Equipment]:
        self.location = None
        return self.inventory

    @classmethod
    def generate(cls, level) -> NPC:
        if random.random() > .5:
            name = CharacterNameGenerator.male_name().generate_name()
        else:
            name = CharacterNameGenerator.female_name().generate_name()
        return cls(
            None,
            Procedural.normal((WandererClass.hit_points_max_base//2)*(level//2), positive=True, integer=True),
            name,
            random.choice(BodyType.__subclasses__())()
        )

    @property
    def sprite_path(self) -> str:
        return SPRITE_FOLDER / "Actors" / "null_npc.png"


class PlayerClass(ABC):

    @property
    def name(self) -> str:
        raise NotImplementedError

    @property
    def hit_points_max_base(self) -> int:
        raise NotImplementedError

    @property
    def sprite_path(self) -> str:
        raise NotImplementedError

    def __str__(self) -> str:
        return self.name


class WandererClass(PlayerClass):
    """ Default player class with nothing special. """
    name = "Wanderer"
    hit_points_max_base = 50

    @property
    def sprite_path(self):
        return SPRITE_FOLDER / "Actors" / "wanderer_class.png"
    
    
class SoliderClass(PlayerClass):
    """ After joining some military (East or West). """
    name = "Solider"
    hit_points_max_base = 75
    
    @property
    def sprite_path(self) -> str:
        return SPRITE_FOLDER / "Actors" / "solider_class.png"


class RaiderClass(PlayerClass):
    """ You've taken up arms without joining a military. """
    name = "Raider"
    hit_points_max_base = 60

    @property
    def sprite_path(self) -> str:
        return SPRITE_FOLDER / "Actors" / "raider_class.png"


class PlayerCharacter(Actor):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._player_class: PlayerClass = WandererClass()
        self._hit_points = self.hit_points_max = self._player_class.hit_points_max_base
        self.equipment_set: Items.EquipmentSet = Items.EquipmentSet()
        self.fov: int = self.fov_default
        self.inventory: List[Items.Equipment] = []
        self.currency: int = 1000

        self.equipment_set.equip(Weapons.Fist(), MainHandEquipment)
        self.equipment_set.equip(Weapons.Fist(), OffHandEquipment)

    @property
    def player_class(self):
        return self._player_class

    @player_class.setter
    def player_class(self, class_: PlayerClass):
        self._player_class = class_
        self.hit_points_max = class_.hit_points_max_base
        self._hit_points = class_.hit_points_max_base

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

    @property
    def sprite_path(self) -> str:
        return self._player_class.sprite_path


