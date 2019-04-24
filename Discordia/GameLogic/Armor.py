from Discordia.GameLogic.Items import Armor, HeadArmor, ChestArmor, LegArmor, FootArmor, MainHandEquipment, \
    OffHandEquipment, FullyImplemented
from random import random


class Helmet(HeadArmor):
    def __init__(self, coverage: float = 0., *args, **kwargs):
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


ImplementedArmorList: list = FullyImplemented.__subclasses__()  # TODO This sucks delete it

ImplementedArmorDict: dict = {cls.__name__: cls for cls in FullyImplemented.__subclasses__()}
