from __future__ import annotations

from abc import ABC
from typing import List

from Discordia.GameLogic import Actors


class FullyImplemented:
    #  Used to signify that equipment is fully defined and ready to be used in game (as opposed to being abstract)
    #  TODO It's bad and needs to be deleted.
    pass


class Equipment(ABC):

    def __init__(self, name: str = "Empty", weight_lb: float = 0, base_value: int = 0):
        self.name: name = name
        self.weight_lb: float = weight_lb
        self.base_value: int = base_value
        self.is_equipped = False

    def __str__(self):
        return self.name

    def __repr__(self):
        return "{} {}lbs ${} [{}]".format(self.name, self.weight_lb, self.base_value, 'X' if self.is_equipped else ' ')

    def on_equip(self, player_character: Actors.PlayerCharacter):
        self.is_equipped = True

    def on_unequip(self, player_character: Actors.PlayerCharacter):
        self.is_equipped = False


class Armor(Equipment, ABC):

    def __init__(self, armor_count=0, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._armor_count: int = armor_count
        self.base_value = 10 * self._armor_count

    @property
    def armour_count(self):
        # Determine if the bullet hits or misses
        return self._armor_count

    @armour_count.setter
    def armour_count(self, val):
        self._armor_count = val

    def activate_utility(self, player_character):
        pass


class HeadArmor(Armor, ABC):
    name: str = "Head"


class ChestArmor(Armor, ABC):
    name: str = "Chest"


class LegArmor(Armor, ABC):
    name: str = "Legs"


class FootArmor(Armor, ABC):
    name: str = "Feet"


class MainHandEquipment(Equipment, ABC):
    name: str = "Main Hand"


class OffHandEquipment(Equipment, ABC):
    name: str = "Off Hand"


class EquipmentSet:

    def __init__(self):
        self.head: HeadArmor = HeadArmor()
        self.chest: ChestArmor = ChestArmor()
        self.legs: LegArmor = LegArmor()
        self.feet: FootArmor = FootArmor()
        self.main_hand: MainHandEquipment = MainHandEquipment()
        self.off_hand: OffHandEquipment = OffHandEquipment()

    def __str__(self):
        return "Head: {}\r\n" \
               "Chest: {}\r\n" \
               "Legs: {}\r\n" \
               "Feet: {}\r\n" \
               "MainHand: {}\r\n" \
               "OffHand: {}\r\n".format(
            self.head.name,
            self.chest.name,
            self.legs.name,
            self.feet.name,
            self.main_hand.name,
            self.off_hand.name)

    def __iter__(self):
        yield self.head
        yield self.chest
        yield self.legs
        yield self.feet
        yield self.main_hand
        yield self.off_hand

    @property
    def armor_set(self) -> List[Armor]:
        armor_list = [self.head,
                      self.chest,
                      self.legs,
                      self.feet]
        if hasattr(self.main_hand, 'armour_count'):
            armor_list.append(self.main_hand)
        if hasattr(self.off_hand, 'armour_count'):
            armor_list.append(self.off_hand)
        return armor_list

    @property
    def armor_count(self) -> int:
        return sum([armor.armour_count for armor in self.armor_set])

    def equip(self, equipment: Equipment):
        if isinstance(equipment, HeadArmor):
            self.head = equipment
        if isinstance(equipment, ChestArmor):
            self.chest = equipment
        if isinstance(equipment, LegArmor):
            self.legs = equipment
        if isinstance(equipment, FootArmor):
            self.feet = equipment
        if isinstance(equipment, MainHandEquipment):
            self.main_hand = equipment
        if isinstance(equipment, OffHandEquipment):
            self.off_hand = equipment
        else:
            raise ValueError("Equipment was not of recognized type.")

    def unequip(self, equipment: Equipment):
        if isinstance(equipment, HeadArmor):
            self.head = HeadArmor()
        if isinstance(equipment, ChestArmor):
            self.chest = ChestArmor()
        if isinstance(equipment, LegArmor):
            self.legs = LegArmor()
        if isinstance(equipment, FootArmor):
            self.feet = FootArmor()
        if isinstance(equipment, MainHandEquipment):
            self.main_hand = MainHandEquipment()
        if isinstance(equipment, OffHandEquipment):
            self.off_hand = OffHandEquipment()
        else:
            raise ValueError("Equipment was not of recognized type.")


class Store:

    def __init__(self, inventory=None):
        super().__init__()
        self.inventory: List[Equipment] = inventory if inventory is not None else []
        self.price_ratio: float = 1.0  # Lower means better buy/sell prices, higher means worse

    def get_price(self, item: Equipment) -> float:
        return item.base_value * self.price_ratio

    def sell_item(self, index: int, player_character: Actors.PlayerCharacter) -> bool:
        # Get an instance of the item from the Store's inventory
        item = [item for item in self.inventory if isinstance(item, type(list(set(self.inventory))[index]))][0]
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
