"""
Armor players can purchase and wear.

The classes here are behaviour -- how coverage turns a hit into a graze. The numbers that tell one piece
from another live in data/armor.json, keyed by class name, and reach the class through FromData.
"""

from random import random

from Discordia.GameLogic import Data
from Discordia.GameLogic.Data import DATA_FOLDER
from Discordia.GameLogic.Items import (
    HeadArmorAbstract,
    ChestArmorAbstract,
)

STATS_PATH = DATA_FOLDER / "armor.json"

# No enum fields here, so the blocks load as written -- no decoding pass like Weapons.
STATS = Data.load(STATS_PATH)


class FromData(Data.FromData):
    STATS = STATS


class Helmet(HeadArmorAbstract):
    def __init__(self, *args, coverage: float = 0.0, **kwargs):
        super().__init__(*args, **kwargs)
        self.coverage = coverage  # Pct. of head the helmet covers. [0, 1]

    @property
    def armor_count(self):
        # Determine if the bullet hits or misses
        return self._armor_count if random() <= self.coverage else 0

    @armor_count.setter
    def armor_count(self, val):
        self._armor_count = val


class ChestArmor(ChestArmorAbstract):
    def __init__(self, *args, coverage: float = 0.0, efficiency: float = 0.0, **kwargs):
        super().__init__(*args, **kwargs)
        self.coverage = coverage  # Pct. of head the helmet covers. [0, 1]
        self.efficiency = efficiency  # How well the armor works on a miss

    @property
    def armor_count(self):
        # Body armor provides constant protection
        return (
            self._armor_count
            if random() <= self.coverage
            else self.efficiency * self._armor_count
        )

    @armor_count.setter
    def armor_count(self, val):
        self._armor_count = val


class SSh68(FromData, Helmet):
    """
    Based on the Soviet SSh-68 helmet
    """


class Helm6B27(FromData, Helmet):
    """
    Based on the Soviet 6B27/6B26/6B28
    """


class Chest6B45(FromData, ChestArmor):
    """
    Based on the Soviet 6B45
    """


class Chest6B2(FromData, ChestArmor):
    """
    Based on the Soviet 6B2, the first vest issued in numbers (1981): stops fragments, not rifle rounds.
    """


class Chest6B3(FromData, ChestArmor):
    """
    Based on the Soviet 6B3 (1983), the answer to that: stops more, weighs twice as much in the mountains.
    """


class HelmAltyn(FromData, Helmet):
    """
    Based on the Soviet Altyn titanium helmet, issued to special units only. Boss loot only.
    """


class Chest6B4(FromData, ChestArmor):
    """
    Based on the Soviet 6B4 (1985), ceramic plates: the best vest of the war, and the heaviest. Boss loot only.
    """
