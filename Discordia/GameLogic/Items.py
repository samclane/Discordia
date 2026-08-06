from __future__ import annotations

import logging
from abc import ABC
from typing import Dict, Tuple, Type

from Discordia.GameLogic import Actors

LOG = logging.getLogger("Discordia.GameLogic.Items")


class FullyImplemented:
    #  Used to signify that equipment is fully defined and ready to be used in game (as opposed to being abstract)
    #  FIXME It's bad and needs to be deleted.
    pass


class Equipment(ABC):

    def __init__(
        self,
        name: str = "Empty",
        weight_lb: float = 0,
        base_value: float = 0.0,
        *args,
        **kwargs,
    ):
        self.name: str = name
        self.weight_lb: float = weight_lb
        self.base_value: float = base_value
        self.is_equipped = False

    def __str__(self):
        return self.name

    def __repr__(self):
        return "{} {}lbs ${} [{}]".format(
            self.name, self.weight_lb, self.base_value, "X" if self.is_equipped else " "
        )

    def on_equip(self, player_character: Actors.PlayerCharacter):
        self.is_equipped = True

    def on_unequip(self, player_character: Actors.PlayerCharacter):
        self.is_equipped = False


class ArmorAbstract(Equipment, ABC):

    def __init__(self, armor_count: float = 0.0, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._armor_count: float = armor_count
        self.base_value = 10 * self._armor_count

    @property
    def armor_count(self):
        # Determine if the bullet hits or misses
        return self._armor_count

    @armor_count.setter
    def armor_count(self, val):
        self._armor_count = val

    def activate_utility(self, player_character):
        pass


class HeadArmorAbstract(ArmorAbstract, ABC):
    name: str = "Head"


class ChestArmorAbstract(ArmorAbstract, ABC):
    name: str = "Chest"


class LegArmorAbstract(ArmorAbstract, ABC):
    name: str = "Legs"


class FootArmorAbstract(ArmorAbstract, ABC):
    name: str = "Feet"


class MainHandEquipment(Equipment, ABC):
    name: str = "Main Hand"


class OffHandEquipment(Equipment, ABC):
    name: str = "Off Hand"


class EquipmentSet:

    SLOTS: Dict[str, Type[Equipment]] = {
        "head": HeadArmorAbstract,
        "chest": ChestArmorAbstract,
        "legs": LegArmorAbstract,
        "feet": FootArmorAbstract,
        "main_hand": MainHandEquipment,
        "off_hand": OffHandEquipment,
    }

    def __init__(self):
        self.head: HeadArmorAbstract = HeadArmorAbstract()
        self.chest: ChestArmorAbstract = ChestArmorAbstract()
        self.legs: LegArmorAbstract = LegArmorAbstract()
        self.feet: FootArmorAbstract = FootArmorAbstract()
        self.main_hand: MainHandEquipment = MainHandEquipment()
        self.off_hand: OffHandEquipment = OffHandEquipment()

    def __str__(self):
        return (
            "Head: {}\r\n"
            "Chest: {}\r\n"
            "Legs: {}\r\n"
            "Feet: {}\r\n"
            "MainHand: {}\r\n"
            "OffHand: {}\r\n".format(
                self.head.name,
                self.chest.name,
                self.legs.name,
                self.feet.name,
                self.main_hand.name,
                self.off_hand.name,
            )
        )

    def __iter__(self):
        yield self.head
        yield self.chest
        yield self.legs
        yield self.feet
        yield self.main_hand
        yield self.off_hand

    @property
    def armor_count(self) -> float:
        return sum(getattr(equipment, "armor_count", 0.0) for equipment in self)

    def _slot(self, equipment_type: Type[Equipment]) -> Tuple[str, Type[Equipment]]:
        # ponytail: first match wins, so declaration order decides for multi-slot gear
        # (e.g. an SMG is both Main- and OffHandEquipment -> main hand by default).
        for slot, base in self.SLOTS.items():
            if issubclass(equipment_type, base):
                return slot, base
        raise ValueError(f"Equipment was not of recognized type: {equipment_type}")

    def equip(
        self, equipment: Equipment, equipment_type: Type[Equipment] | None = None
    ):
        slot, _ = self._slot(equipment_type or type(equipment))
        setattr(self, slot, equipment)

    def unequip(self, equipment: Equipment):
        slot, base = self._slot(type(equipment))
        setattr(self, slot, base())
