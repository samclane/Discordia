from random import random

from Discordia.GameLogic.Items import HeadArmorAbstract, FullyImplemented


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
