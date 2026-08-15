"""
Weapons players can purchase and wield.

The classes here are behaviour -- how a weapon fires, falls off with range, or crits. The numbers that tell
one gun from another live in data/weapons.json, keyed by class name, and reach the class through FromData.
"""

from __future__ import annotations

from abc import ABC
from typing import Any, Dict, Optional

from Discordia.GameLogic import Actors, Data, GameSpace
from Discordia.GameLogic.Data import DATA_FOLDER
from Discordia.GameLogic.Items import (
    Ammo,
    Equipment,
    MainHandEquipment,
    OffHandEquipment,
    FullyImplemented,
)

STATS_PATH = DATA_FOLDER / "weapons.json"


class ProjectileType:
    Thrown = 0
    Bullet = 1
    Rocket = 2
    Grenade = 3
    Other = 4


class Caliber:
    BB = 0
    MM_9 = IN_38 = 1
    MM_762 = 2
    IN_577 = 3
    IN_45 = 4
    MM_556 = 5


class FiringAction:
    SingleShot = 0
    BoltAction = 1
    SemiAutomatic = 2
    BurstFireOnly = 3
    FullyAutomatic = 4


_ENUM_FIELDS = {
    "caliber": Caliber,
    "action": FiringAction,
    "projectile_type": ProjectileType,
}


def load_stats(path=STATS_PATH) -> Dict[str, Dict[str, Any]]:
    """Stat blocks by class name, with this module's enum fields decoded."""
    return Data.load(path, _ENUM_FIELDS)


STATS = load_stats()


class FromData(Data.FromData):
    STATS = STATS


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

    def __init__(self, range_: int = 1, range_falloff: float = 1.0, *args, **kwargs):
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
        return super().__repr__() + " {}sq {}%-falloff".format(
            self.range_, self.range_falloff
        )

    def calc_damage(self, distance: int) -> int:
        damage = self.damage * ((1.0 - self.range_falloff) ** distance)
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
        self.projectile_type = projectile_type
        if projectile_type is ProjectileType.Bullet:
            self.caliber: int = kwargs.get("caliber", Caliber.MM_9)
        if capacity < 1:
            raise ValueError("Capacity must be 1 or greater.")
        self.capacity = capacity
        self._current_capacity = capacity

    def __repr__(self):
        return super().__repr__() + " AmmoTypeEnum:{} {}/{} shots".format(
            self.projectile_type, self.current_capacity, self.capacity
        )

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

    def reload(self, actor: Actors.Actor):
        for item in actor.inventory:
            if isinstance(item, Ammo) and item.caliber == self.caliber:
                ammo_needed = self.capacity - self.current_capacity
                ammo_to_load = min(ammo_needed, item.quantity)
                self._current_capacity += ammo_to_load
                item.quantity -= ammo_to_load
                if item.quantity <= 0:
                    actor.inventory.remove(item)
                return


class Firearm(ProjectileWeapon, ABC):

    def __init__(
        self,
        caliber: int,
        action: int = FiringAction.SingleShot,
        burst_size: int = 1,
        *args,
        **kwargs,
    ):
        super().__init__(ProjectileType.Bullet, *args, **kwargs)
        self.caliber = caliber
        self._action = action
        if self.action < FiringAction.BurstFireOnly and burst_size > 1:
            raise ValueError(
                "Firing action must be BurstFireOnly or FullyAutomatic to have a burst > 1"
            )
        if self.is_single_shot:
            self._action = FiringAction.SingleShot
        self.burst_size = burst_size
        self.base_value += 10 * self._action  # Better firing action => Costs more

    def __repr__(self):
        return (
            super().__repr__()
            + " CaliberEnum:{} ActionEnum:{} {} shots-per-attack".format(
                self.caliber, self._action, self.burst_size
            )
        )

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
            raise AttributeError(
                "Cannot change mounting status of unmountable MachineGun."
            )
        if self.mounted:
            self.range_falloff -= 0.1
        else:
            self.range_falloff += 0.1
        self._mounted = new


class FNMinimi(FromData, MachineGun, FullyImplemented):
    """
    Based on the FN Minimi
    """


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


class Hammer(FromData, BluntWeapon, MainHandEquipment, FullyImplemented):
    pass


class Fist(FromData, BluntWeapon, MainHandEquipment, OffHandEquipment):
    """Everyone starts with these; not FullyImplemented, so no store stocks them."""


class SMG(Firearm, MainHandEquipment, OffHandEquipment, ABC):
    pass


class MachinePistol(Firearm, MainHandEquipment, OffHandEquipment, ABC):
    pass


class Rifle(Firearm, MainHandEquipment, OffHandEquipment, ABC):
    pass


class WeblyRevolver(FromData, Pistol, FullyImplemented):
    """
    Based on the Webly Mk. IV
    """


class TT33(FromData, Pistol, FullyImplemented):
    """
    Based on the TT-33
    """


class Makarov(FromData, Pistol, FullyImplemented):
    """
    Based on the Makarov PM
    """


class M1911(FromData, Pistol, FullyImplemented):
    """
    Based on the M1911
    """


class StechkinAPS(FromData, MachinePistol, SelectiveFire, FullyImplemented):
    """
    Based on the Stechkin automatic pistol (APS)
    """


class CarlGustafm45(FromData, SMG, FullyImplemented):
    """
    Based on the Carl Gustaf m/45
    """


class PPSh41(FromData, SMG, SelectiveFire, FullyImplemented):
    """
    Based on the PPSh-41 (Shpagin machine pistol)
    """


class Sten(FromData, SMG, SelectiveFire, FullyImplemented):
    """
    Based on the Sten submachine gun
    """


class NorincoCQ(FromData, SMG, FullyImplemented):
    """
    Based on the Norinco CQ
    """


class L1A1(FromData, Rifle, FullyImplemented):
    """
    Based on the L1A1 (FN FAL)
    """


class OwenSMG(FromData, SMG, FullyImplemented):
    """
    Based on the Owen Machine Carbine (Australian)
    """


class AK47(FromData, Rifle, SelectiveFire, FullyImplemented):
    """
    Based on the AK-47
    """


class AKM(FromData, Rifle, SelectiveFire, FullyImplemented):
    """
    Based on the AKM
    """


class Type56(FromData, Rifle, SelectiveFire, FullyImplemented):
    """
    Based on the Type 56
    """


class HKG3(FromData, Rifle, SelectiveFire, FullyImplemented):
    """
    Based on the Heckler & Koch G3
    """


class Jezail(FromData, Rifle, FullyImplemented):
    """
    Based on the Jezail Musket. Does 2x dmg if user is on a mountain.
    https://en.wikipedia.org/wiki/Jezail
    """

    def __init__(self):
        super().__init__()
        self.player: Optional[Actors.PlayerCharacter] = None

    def on_equip(self, player_character: Actors.PlayerCharacter):
        super().on_equip(player_character)
        self.player = player_character

    def on_unequip(self, player_character: Actors.PlayerCharacter):
        super().on_unequip(player_character)
        self.player = None

    def calc_damage(self, distance: int) -> int:
        damage = super().calc_damage(distance)
        if self.player and isinstance(
            self.player.location.terrain, GameSpace.MountainTerrain
        ):
            damage *= 2
        return damage
