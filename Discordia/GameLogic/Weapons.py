from __future__ import annotations
from abc import ABC
from typing import Optional

from Discordia.GameLogic import Actors, GameSpace
from Discordia.GameLogic.Items import Equipment, MainHandEquipment, OffHandEquipment, FullyImplemented


class ProjectileType:
    Thrown = 0
    Bullet = 1
    Rocket = 2
    Grenade = 3
    Other = 4


class Caliber:
    BB = 0
    MM_9 = IN_38 = 1  # Pistol & SMG
    MM_762 = 2  # AK47
    IN_577 = 3  # Rifles
    IN_45 = 4


class FiringAction:
    SingleShot = 0
    BoltAction = 1
    SemiAutomatic = 2
    BurstFireOnly = 3
    FullyAutomatic = 4


class Weapon(Equipment, ABC):
    _base_damage: int

    def __init__(self, base_damage: int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if base_damage < 0:
            raise ValueError("base_damage must be 0 or greater.")
        self._base_damage = base_damage
        self.base_value = 10 * self._base_damage

    def __eq__(self, other):
        return self.name == other.name

    def __hash__(self):
        return hash(self.name)

    def __str__(self):
        return "{}\t{}dmg".format(self.name, self.damage)

    @property
    def damage(self):
        return self._base_damage

    def on_damage(self):
        pass


class RangedWeapon(Weapon, ABC):

    def __init__(self, range_: int = 1, range_falloff: float = 1., *args, **kwargs):
        """
        Any weapon that can strike >1 squares away from the player.
        """
        super().__init__(*args, **kwargs)
        if range_ < 1:
            raise ValueError("Range must be 1 or greater.")
        self.range_ = range_
        if not (0 <= range_falloff <= 1):
            raise ValueError("range_falloff must be between 0 and 1")
        self._range_falloff = range_falloff
        self.base_value = int(self.base_value + (50 * range_) * (1 - range_falloff))

    def __repr__(self):
        return super().__repr__() + " {}sq {}%-falloff".format(self.range_, self.range_falloff)

    def calc_damage(self, distance: int) -> int:
        damage = self.damage * ((1. - self.range_falloff) ** distance)
        return int(damage)

    @property
    def range_falloff(self) -> float:
        return self._range_falloff

    @range_falloff.setter
    def range_falloff(self, val: float):
        val = min(max(val, 0), 1)  # Clamp val between 0 and 1
        self._range_falloff = val


class ProjectileWeapon(RangedWeapon, ABC):

    def __init__(self, projectile_type: int, capacity: int = 1, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ammo_type = projectile_type
        if capacity < 1:
            raise ValueError("Capacity must be 1 or greater.")
        self.capacity = capacity
        self._current_capacity = capacity

    def __repr__(self):
        return super().__repr__() + " AmmoTypeEnum:{} {}/{} shots".format(self.ammo_type, self.current_capacity,
                                                                          self.capacity)

    @property
    def is_single_shot(self) -> bool:
        return self.capacity == 1

    @property
    def current_capacity(self) -> int:
        return self._current_capacity

    @property
    def is_empty(self) -> bool:
        return self.current_capacity == 0

    def on_damage(self):
        self.fire()

    def fire(self):
        self._current_capacity -= 1

    def reload(self):
        self._current_capacity = self.capacity


class Firearm(ProjectileWeapon, ABC):

    def __init__(self, caliber: int, action: int = FiringAction.SingleShot, burst_size: int = 1, *args, **kwargs):
        super().__init__(ProjectileType.Bullet, *args, **kwargs)
        self.caliber = caliber
        self._action = action
        if self.action < FiringAction.BurstFireOnly and burst_size > 1:
            raise ValueError("Firing action must be BurstFireOnly or FullyAutomatic to have a burst > 1")
        if self.is_single_shot:
            self._action = FiringAction.SingleShot
        self.burst_size = burst_size
        self.base_value += (10 * self._action)  # Better firing action => Costs more

    def __repr__(self):
        return super().__repr__() + " CaliberEnum:{} ActionEnum:{} {} shots-per-attack".format(self.caliber,
                                                                                               self._action,
                                                                                               self.burst_size)

    def fire(self):
        self._current_capacity -= self.burst_size

    @property
    def damage(self):
        return super().damage * self.burst_size

    @property
    def action(self):
        return self._action

    def on_damage(self):
        self.fire()


class SelectiveFire(Firearm, ABC):

    def toggle_action(self):
        if self._action == FiringAction.SemiAutomatic:
            self._action = FiringAction.FullyAutomatic
        else:
            self._action = FiringAction.SemiAutomatic


class Pistol(Firearm, MainHandEquipment, ABC):
    pass


class WeblyRevolver(Pistol, FullyImplemented):
    """
    Based on the Webly Mk. IV
    """
    name: str = "Webly Mk. IV Revolver"

    def __init__(self):
        super().__init__(caliber=Caliber.IN_38,
                         action=FiringAction.SemiAutomatic,
                         capacity=6,
                         range_falloff=.5,
                         base_damage=10,
                         name=self.name,
                         weightlb=2.4)


class M1911(Pistol, FullyImplemented):
    """
    Based on the M1911
    """
    name: str = "M1911 Pistol"

    def __init__(self):
        super().__init__(caliber=Caliber.IN_45,
                         action=FiringAction.SemiAutomatic,
                         capacity=7,
                         range_falloff=.4,
                         base_damage=8,
                         name=self.name,
                         weightlb=2.44)


class APS(Pistol, SelectiveFire, FullyImplemented):
    """
    Based on the Stechkin automatic pistol (APS)
    """
    name: str = "Stechkin Automatic Pistol"

    def __init__(self):
        super().__init__(caliber=Caliber.MM_9,
                         action=FiringAction.SemiAutomatic,
                         capacity=20,
                         range_falloff=.7,
                         base_damage=4,
                         name=self.name,
                         weightlb=2.69)


class SMG(Firearm, MainHandEquipment, OffHandEquipment, ABC):
    pass


class PPSh41(SMG, SelectiveFire, FullyImplemented):
    """
    Based on the PPSh-41 (Shpagin machine pistol)
    """
    name: str = "PPSh-41 (Shpagin machine pistol)"

    def __init__(self):
        super().__init__(caliber=Caliber.MM_762,
                         action=FiringAction.FullyAutomatic,
                         capacity=35,
                         range_falloff=.55,
                         base_damage=7,
                         name=self.name,
                         weightlb=8.0)


class OwenSMG(SMG, FullyImplemented):
    """
    Based on the Owen Machine Carbine (Australian)
    """
    name: str = "Owen Machine Carbine"

    def __init__(self):
        super().__init__(caliber=Caliber.MM_9,
                         action=FiringAction.FullyAutomatic,
                         capacity=33,
                         range_falloff=.7,
                         base_damage=4,
                         name=self.name,
                         weightlb=9.33)


class Rifle(Firearm, MainHandEquipment, OffHandEquipment, ABC):
    pass


class AK47(Rifle, SelectiveFire, FullyImplemented):
    """
    Based on the AK-47
    """
    name: str = "AK-47"

    def __init__(self):
        super().__init__(caliber=Caliber.MM_762,
                         action=FiringAction.FullyAutomatic,
                         capacity=30,
                         range_falloff=.35,
                         base_damage=15,
                         name=self.name,
                         weightlb=7.7)


class HKG3(Rifle, SelectiveFire, FullyImplemented):
    """
    Based on the Heckler & Koch G3
    """
    name: str = "Heckler & Koch G3"

    def __init__(self):
        super().__init__(caliber=Caliber.MM_762,
                         action=FiringAction.FullyAutomatic,
                         capacity=20,
                         range_falloff=.3,
                         base_damage=14,
                         name=self.name,
                         weightlb=9.7)


class Jezail(Rifle, FullyImplemented):
    """
    Based on the Jezail Musket. Does 2x dmg if user is on a mountain.
    https://en.wikipedia.org/wiki/Jezail
    """
    name: str = "Jezail Musket"

    def __init__(self):
        super().__init__(caliber=Caliber.BB,
                         action=FiringAction.SingleShot,
                         capacity=1,
                         range_falloff=.3,
                         base_damage=20,
                         name=self.name,
                         weightlb=12)

        self.player: Optional[Actors.PlayerCharacter] = None

    def on_equip(self, player_character: Actors.PlayerCharacter):
        self.player = player_character

    def on_unequip(self, player_character: Actors.PlayerCharacter):
        self.player = None

    def calc_damage(self, distance: int) -> int:
        damage = super().calc_damage(distance)
        if self.player and isinstance(self.player.location.terrain, GameSpace.MountainTerrain):
            damage *= 2
        return damage


class MachineGun(Firearm, MainHandEquipment, OffHandEquipment, ABC):

    def __init__(self, mountable: bool = False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mountable = mountable
        self._mounted = False

    @property
    def mounted(self) -> bool:
        return self._mounted

    @property
    def mountable(self) -> bool:
        return self._mountable

    @mounted.setter
    def mounted(self, new: bool):
        if self.mounted == new:  # no change; don't do anything
            return
        if not self.mountable:
            raise AttributeError("Cannot change mounting status of unmountable MachineGun.")
        if self.mounted:
            self.range_falloff -= .1
        else:
            self.range_falloff += .1
        self._mounted = new


class FNMinimi(MachineGun, FullyImplemented):
    """
    Based on the FN Minimi
    """
    name: str = "FN Minimi"

    def __init__(self):
        super().__init__(mountable=True,
                         caliber=Caliber.MM_762,
                         action=FiringAction.FullyAutomatic,
                         capacity=100,
                         range_falloff=.25,
                         base_damage=13,
                         name=self.name,
                         weightlb=15.1)


class Shotgun(Firearm, MainHandEquipment, OffHandEquipment, ABC):
    pellet_count: int

    def __init__(self, pellet_count: int = 2, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if pellet_count < 2:
            raise ValueError("Must have at least 2 pellets per shot.")
        self.pellet_count = pellet_count

    @property
    def damage(self):
        return super().damage * self.pellet_count


class MeleeWeapon(Weapon, ABC):
    pass


class BladedWeapon(MeleeWeapon, ABC):

    def __init__(self, bleed_chance: float, bleed_factor: float, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not (0 <= bleed_chance <= 1):
            raise ValueError("BleedChance must be between 0 and 1.")
        self.bleed_chance: float = bleed_chance
        if not (0 <= bleed_factor <= 1):
            raise ValueError("BleedFactor must be between 0 and 1.")
        self.bleed_factor: float = bleed_factor


class Knife(BladedWeapon, MainHandEquipment):
    pass


class Machete(BladedWeapon, MainHandEquipment):
    pass


class BluntWeapon(MeleeWeapon, ABC):
    cripple_chance: float

    def __init__(self, cripple_chance: float, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not (0 <= cripple_chance <= 1):
            raise ValueError("CrippleChance must be between 0 and 1.")
        self.cripple_chance = cripple_chance


class Hammer(BluntWeapon, MainHandEquipment, FullyImplemented):

    def __init__(self):
        super().__init__(cripple_chance=0.4,
                         base_damage=10)


class Fist(BluntWeapon, MainHandEquipment, OffHandEquipment):

    def __init__(self):
        super().__init__(base_value=0,
                         cripple_chance=0.1,
                         base_damage=2)