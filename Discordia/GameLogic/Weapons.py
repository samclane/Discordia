"""
Weapons players can purchase and wield.

The classes here are behaviour -- how a weapon fires, falls off with range, or crits. The numbers that tell
one gun from another live in data/weapons.json, keyed by class name, and reach the class through FromData.
"""

from __future__ import annotations

import random
import sys
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
    MM_8 = 6
    IN_303 = 7
    M88 = 8
    MM_792 = 9
    IN_762 = 10  # 7.62x25 Tokarev; a pistol round, not the rifle 7.62 above


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
    _base_damage: float

    player: Optional[Actors.PlayerCharacter] = None

    def __init__(self, base_damage: int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if base_damage < 0:
            raise ValueError("base_damage must be 0 or greater.")
        self._base_damage = base_damage
        self.base_value = 10 * self._base_damage

    def on_equip(self, player_character: Actors.PlayerCharacter):
        super().on_equip(player_character)
        self.player = player_character

    def on_unequip(self, player_character: Actors.PlayerCharacter):
        super().on_unequip(player_character)
        self.player = None

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

    def calc_damage(self, distance: int) -> float:
        damage = self.damage * ((1.0 - self.range_falloff) ** distance)
        return damage

    @property
    def range_falloff(self) -> float:
        return self._range_falloff

    @range_falloff.setter
    def range_falloff(self, val: float):
        val = min(max(val, 0), 1)  # Clamp val between 0 and 1
        self._range_falloff = val


class ProjectileWeapon(RangedWeapon, ABC):
    reload_size: int = sys.maxsize  # rounds per reload; single-loaders override
    chambered: int = 0  # extra round riding in the chamber past a full magazine

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
                ammo_needed = self.capacity + self.chambered - self.current_capacity
                ammo_to_load = min(ammo_needed, item.quantity, self.reload_size)
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
    def damage(self) -> float:
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
        # A deployed gun is steadier, so it loses less damage per square, not more.
        self.range_falloff += -0.1 if new else 0.1
        self._mounted = new


class BeltFedMachineGun(MachineGun, ABC):
    """
    Fed from a belt rather than a magazine: sustained fire walks onto the target.

    Every shot without a reload is +10% damage, capped at double. Break to reload and you start over.
    """

    _consecutive_fires: int = 0

    def fire(self):
        self._consecutive_fires += 1
        super().fire()

    def reload(self, actor: Actors.Actor):
        super().reload(actor)
        self._consecutive_fires = 0

    @property
    def damage(self) -> float:
        return super().damage * min(1 + 0.1 * self._consecutive_fires, 2.0)


class Bipod(MachineGun, ABC):
    """Folding bipod: deploys itself on high ground, where there is something to rest it on."""

    def calc_damage(self, distance: int) -> float:
        if self.player:
            self.mounted = isinstance(
                self.player.location.terrain, GameSpace.MountainTerrain
            )
        return super().calc_damage(distance)


class SingleLoad(ProjectileWeapon, ABC):
    """Rounds go in one at a time -- there is no magazine to swap."""

    reload_size = 1


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
    def damage(self) -> float:
        return super().damage * self.pellet_count

    def calc_damage(self, distance: int) -> float:
        """pellet_count scales down with distance: max(1, pellet_count - distance). Free spread modelling using a field that's already there."""
        damage = super().calc_damage(distance)
        damage *= max(1, self.pellet_count - distance) / self.pellet_count
        return damage


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
    Based on the PPSh-41 (Shpagin machine pistol). The drum lets it rip while it is more than half
    full; below that it stutters back down to single shots.
    """

    _burst_size: int = 1

    @property
    def burst_size(self) -> int:
        if self.current_capacity > self.capacity / 2:
            return self._burst_size * 3
        return self._burst_size

    @burst_size.setter
    def burst_size(self, value: int):
        self._burst_size = value


class Sten(FromData, SMG, SelectiveFire, FullyImplemented):
    """
    Based on the Sten submachine gun. Stamped out of tube and sheet: one shot in five jams, and the
    shot you spend clearing it lands at half.
    """

    _jammed: bool = False

    @property
    def damage(self) -> float:
        return super().damage / 2 if self._jammed else super().damage

    def fire(self):
        # ponytail: damage is read before fire() everywhere, so a jam only spoils the *next* shot.
        self._jammed = not self._jammed and random.random() < 0.2
        super().fire()


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

    def calc_damage(self, distance: int) -> float:
        """Top-mounted magazine keeps the mud out: no falloff at all in the wet and the sand."""
        if self.player and isinstance(
            self.player.location.terrain,
            (GameSpace.WaterTerrain, GameSpace.SandTerrain),
        ):
            return self.damage if distance <= self.range_ else 0.0
        return super().calc_damage(distance)


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

    def calc_damage(self, distance: int) -> float:
        damage = super().calc_damage(distance)
        if self.player and isinstance(
            self.player.location.terrain, GameSpace.MountainTerrain
        ):
            damage *= 2
        return damage


class MartiniHenry(FromData, Rifle, FullyImplemented):
    """
    Based on the Martini-Henry rifle
    """

    def calc_damage(self, distance: int) -> float:
        """A .577 slug: double damage in its face, twice the usual falloff past that."""
        damage = super().calc_damage(distance)
        if distance <= 1:
            return damage * 2
        return max(damage * (1 - self.range_falloff * distance * 2), 0.0)


class MosinNagant(FromData, Rifle, FullyImplemented):
    """
    Based on the Mosin-Nagant rifle
    """

    def calc_damage(self, distance: int) -> float:
        """Scoped: falloff runs backwards, so it hits harder the further out you are -- to a point."""
        if distance > self.range_:
            return 0.0
        return self.damage * min(1 + self.range_falloff * distance, 2.0)


class Lebel(FromData, SingleLoad, Rifle, FullyImplemented):
    """
    Based on the Lebel Model 1886 rifle. Tube magazine: thumbed full one round at a time.
    """

    def calc_damage(self, distance: int) -> float:
        """Trench rifle: +50% on Grass/lowland, penalty on Mountain. Mirror of the Jezail, gives the two a rivalry."""
        damage = super().calc_damage(distance)
        if self.player:
            if isinstance(self.player.location.terrain, GameSpace.MountainTerrain):
                damage *= 0.5
            elif isinstance(self.player.location.terrain, GameSpace.GrassTerrain):
                damage *= 1.5
        return damage


class LeeEnfield(FromData, Rifle, FullyImplemented):
    """
    Based on the Lee-Enfield rifle. Stripper clips and a round left in the chamber: reloads to one
    over a full magazine.
    """

    chambered = 1


class M1917(FromData, Rifle, FullyImplemented):
    """
    Based on the M1917 rifle
    """


class Hanyang(FromData, SingleLoad, Rifle, FullyImplemented):
    """
    Based on the Hanyang 88 rifle. Worn out long before anyone here got hold of one: single loading.
    """


class SKS(FromData, Rifle, FullyImplemented):
    """
    Based on the SKS rifle. Stripper clips over an open bolt, one up the spout.
    """

    chambered = 1


class M1Garand(FromData, Rifle, FullyImplemented):
    """
    Based on the M1 Garand rifle. The en-bloc clip pings out when the last round goes and everyone in
    earshot knows you are empty -- the first shot after that reload lands at half.
    """

    _pinged: bool = False

    @property
    def damage(self) -> float:
        return super().damage / 2 if self._pinged else super().damage

    def fire(self):
        super().fire()
        self._pinged = self.is_empty


class RPD(FromData, BeltFedMachineGun, FullyImplemented):
    """
    Based on the RPD light machine gun
    """


class RPK(FromData, Bipod, FullyImplemented):
    """
    Based on the RPK light machine gun
    """


class ZBvz26(FromData, Bipod, FullyImplemented):
    """
    Based on the ZB vz. 26 light machine gun
    """


class PKM(FromData, BeltFedMachineGun, FullyImplemented):
    """
    Based on the PKM general-purpose machine gun
    """


class Type67(FromData, BeltFedMachineGun, FullyImplemented):
    """
    Based on the Type 67 general-purpose machine gun
    """
