from random import random

from Discordia.GameLogic.Items import HeadArmorAbstract, ChestArmorAbstract, FullyImplemented


class Helmet(HeadArmorAbstract):
    def __init__(self, *args, coverage: float = 0., **kwargs):
        super().__init__(*args, **kwargs)
        self.coverage = coverage  # Pct. of head the helmet covers. [0, 1]

    @property
    def armor_count(self):
        # Determine if the bullet hits or misses
        return self._armor_count if random.random() <= self.coverage else 0

    @armor_count.setter
    def armor_count(self, val):
        self._armor_count = val


class ChestArmor(ChestArmorAbstract):
    def __init__(self, *args, coverage: float = 0., efficiency: float = 0., **kwargs):
        super().__init__(*args, **kwargs)
        self.coverage = coverage  # Pct. of head the helmet covers. [0, 1]
        self.efficiency = efficiency # How well the armor works on a miss

    @property
    def armor_count(self):
        # Body armor provides constant protection
        return self._armor_count if random.random() <= self.coverage else\
            self.efficiency * self._armor_count

    @armor_count.setter
    def armor_count(self, val):
        self._armor_count = val


class SSh68(Helmet, FullyImplemented):
    """
    Based on the Soviet SSh-68 helmet
    """
    name: str = "SSh-68"

    def __init__(self):
        super().__init__(coverage=.50,
                         armor_count=1,
                         name=self.name,
                         weightlb=3.31)


class Helm6B27(Helmet, FullyImplemented):
    """
    Based on the Soviet 6B27/6B26/6B28
    """
    name: str = "6B27"

    def __init__(self):
        super().__init__(coverage=.50,
                         armor_count=3,
                         name=self.name,
                         weight_lb=2.0)  # est


class Chest6B45(ChestArmor):
    """
    Based on the Soviet 6B45
    """
    name: str = "6B45"

    def __init__(self):
        super().__init__(coverage=.70,
                         armor_count=10,
                         name=self.name,
                         weight_lb=16.5)