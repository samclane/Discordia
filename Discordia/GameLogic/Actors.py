from __future__ import annotations

import random
from abc import ABC, abstractmethod
from typing import Any, Tuple, List, Type, Union
from enum import Enum, auto

from Discordia import SPRITE_FOLDER
from Discordia.GameLogic import Behavior, GameSpace, Items, Weapons, Procedural
from Discordia.GameLogic.Items import Equipment, MainHandEquipment, OffHandEquipment
from Discordia.GameLogic.StringGenerator import FemaleNameGenerator, MaleNameGenerator

CURRENCY_PER_LEVEL = 25  # average money a generated NPC carries, per wilds level
HIT_POINTS_PER_LEVEL = 25  # half a fresh Wanderer at level 1, and up from there
EXPERIENCE_PER_LEVEL = 100  # flat: level 2 at 100 experience, level 3 at 200, and so on
HIT_POINTS_PER_PLAYER_LEVEL = 10  # what each player level adds on top of the class base
# Each hideout level pays HIDEOUT_INCOME into the stash every HIDEOUT_PAY_TICKS world ticks: $120 an hour at the
# default 5-second tick. The first costs HIDEOUT_COST, about eight hours of what it pays, and each after costs
# HIDEOUT_GROWTH times more (Cookie Clicker's curve), so every level takes a little longer to pay for itself.
# Every HIDEOUT_SALVAGE_EVERY-th level is bartered for Items.Salvage instead, a piece more each time.
HIDEOUT_COST = 1000
HIDEOUT_GROWTH = 1.15
HIDEOUT_SALVAGE_EVERY = 5
HIDEOUT_INCOME = 10
HIDEOUT_PAY_TICKS = 60
# A camp out past the towns heals CAMP_HEAL_SHARE of your hit points every CAMP_HEAL_TICKS: full in twenty minutes
# at a 5-second tick. Slow next to an inn, which is the point: it saves the walk, not the time.
CAMP_HEAL_TICKS = 12
CAMP_HEAL_SHARE = 0.05


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

    def attempt_move(
        self, shift: Tuple[int, int]
    ) -> List[GameSpace.PlayerActionResponse]:
        return []

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
    def on_death(self) -> List[Items.Equipment]:
        pass

    @property
    def sprite_path(self) -> str:
        raise NotImplementedError


class Inventory(List[Items.Equipment]):
    """
    A list of Equipment objects that can be used by an Actor.
    """

    def add(self, item: Items.Equipment):
        self.append(item)

    def remove(self, item: Items.Equipment):
        if item in self:
            super().remove(item)

    def has_item(self, item: Items.Equipment) -> bool:
        return item in self


class Actor(AbstractActor, ABC):

    def __init__(
        self,
        parent_world: GameSpace.World,
        hp: int = 0,
        name: str = "<NONE>",
        body_type: BodyType = Humanoid(),
    ):
        self.parent_world = parent_world
        self._hit_points = self.hit_points_max = hp
        self._is_dead = False
        self.name = name
        self.body_type = body_type
        self.inventory: Inventory = Inventory()
        # None until the actor is spawned into the world; everything past that point assumes a Space
        self.location: GameSpace.Space = None  # type: ignore[assignment]
        self.fov_default = 2
        self.last_time_moved = 0.0

    def __str__(self):
        return self.name

    def __repr__(self):
        attrdict = []
        for attr in [a for a in self.__dict__ if not a.startswith("__")]:
            attrdict.append(f"{attr}: {getattr(self, attr)}")
        return f"{self.__class__.__name__}(" + ", ".join(attrdict) + ")"

    def attempt_move(
        self, shift: Tuple[int, int]
    ) -> List[GameSpace.PlayerActionResponse]:
        new_coords = self.location + shift
        if not self.parent_world.is_coords_valid(new_coords.x, new_coords.y):
            return [GameSpace.PlayerActionResponse(is_successful=False, source=self)]
        self.location = self.parent_world.space_at(new_coords.x, new_coords.y)
        if isinstance(
            self.location, (GameSpace.Wilds, GameSpace.Cache, GameSpace.Extract)
        ) and isinstance(self, PlayerCharacter):
            return self.location.run_event(player=self)
        else:
            return [GameSpace.PlayerActionResponse(is_successful=True, source=self)]

    @property
    def hit_points(self) -> int:
        return self._hit_points

    @hit_points.setter
    def hit_points(self, value):
        if not self.is_dead:
            self._hit_points = min(max(value, 0), self.hit_points_max)
            if self._hit_points <= 0:
                self._is_dead = True
                self.on_death()

    def take_damage(self, damage: int):
        self.hit_points -= damage

    @property
    def is_dead(self) -> bool:
        return self._is_dead

    def revive(self):
        """Back on your feet at full health. The hit_points setter ignores the dead, so this goes around it."""
        self._is_dead = False
        self._hit_points = self.hit_points_max

    def on_death(self):
        return []

    def step(self, space: GameSpace.Space, toward: bool = True) -> List[GameSpace.PlayerActionResponse]:
        """One square closer to `space`, or further from it. Stays put, returning [], if no step helps;
        otherwise returns what the move did."""
        # ponytail: greedy, so a coastline between it and you stops it cold. A* would go round, but the
        # pathfinder generates chunks as it searches: guard it to loaded chunks first.
        here = self.location

        def gap(d):
            return (here.x + d[0] - space.x) ** 2 + (here.y + d[1] - space.y) ** 2

        now = gap((0, 0))
        steps = [d for d in GameSpace.DIRECTION_VECTORS.values() if (gap(d) < now if toward else gap(d) > now)]
        random.shuffle(steps)  # equally good steps in any order, so it doesn't always favour one side
        for shift in sorted(steps, key=gap, reverse=not toward):
            results = self.attempt_move(shift)
            if not results or not results[0].failed:  # a wilds event can move you and have nothing to say
                return results or [GameSpace.PlayerActionResponse(is_successful=True, source=self)]
        return []

    @property
    def sprite_path(self) -> str:
        return str(SPRITE_FOLDER / "Actors" / "null_actor.png")

    @property
    def sprite_path_string(self) -> str:
        return str(self.sprite_path)


class NPC(Actor):
    BODIES: Tuple[Type[BodyType], ...] = (Humanoid,)  # what generate() picks a body from

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.flavor_text: str = "<NONE>"
        self.base_attack = 1
        self.currency: int = 0  # what the killer pockets, alongside the inventory
        self.brain = Behavior.FiniteStateMachine(self, Behavior.Aggressive())
        self.quarry: PlayerCharacter | None = None  # who it last warned it's hunting

    def on_death(self) -> Inventory:
        self.location = None  # type: ignore[assignment]  # despawns the NPC
        return self.inventory

    @property
    def level(self) -> int:
        """NPCs never learned to track their own level: they're only as tough as their hide."""
        return max(1, self.hit_points_max // HIT_POINTS_PER_LEVEL)

    def attempt_move(
        self, shift: Tuple[int, int]
    ) -> List[GameSpace.PlayerActionResponse]:
        # Only players explore. An NPC wandering into unmade ground would build map nobody visits, and
        # every chunk it made would stay in memory and on the web map for good.
        there = self.location + shift
        size = GameSpace.CHUNK_SIZE
        if self.parent_world.loaded_chunk(there.x // size, there.y // size) is None:
            return [GameSpace.PlayerActionResponse(is_successful=False, source=self)]
        return super().attempt_move(shift)

    @classmethod
    def generate(cls, level) -> NPC:
        generator = MaleNameGenerator if random.random() > 0.5 else FemaleNameGenerator
        # Wilds hand out levels from 0 up, so floor the level at 1: a 0 hit-point NPC is born unable to
        # fight (it is already under Aggressive.flee_at) and dies to the first scratch.
        hit_points = max(
            1,
            int(
                Procedural.normal(
                    HIT_POINTS_PER_LEVEL * max(level, 1), positive=True, integer=True
                )
            ),
        )
        npc = cls(
            None,
            hit_points,
            generator.generate_name(),
            random.choice(cls.BODIES)(),
        )
        # A pistol costs ~100, so a level-1 kill is worth a few percent of one. Raise CURRENCY_PER_LEVEL
        # if the grind to a first real weapon drags.
        npc.currency = int(
            Procedural.normal(CURRENCY_PER_LEVEL * level, positive=True, integer=True)
        )
        return npc

    @property
    def sprite_path(self) -> str:
        return str(SPRITE_FOLDER / "Actors" / "null_npc.png")


class Raider(NPC):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.flavor_text = "A raider, looking to take what they can from you."
        self.base_attack = 2

    @property
    def sprite_path(self) -> str:
        return str(SPRITE_FOLDER / "Actors" / "raider_class.png")


class Animal(NPC):
    """Wildlife: keeps away from players and never fights back. Carries no money, but a kill is experience, and
    running one down is how a fresh character with a gun levels without a raider shooting back."""

    BODIES = (SmallAnimal, LargeAnimal)
    KINDS = {SmallAnimal: ["rat", "feral cat", "crow", "fox"], LargeAnimal: ["stray dog", "wild boar", "deer"]}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.flavor_text = "Something wild, and wary of you."
        self.brain = Behavior.FiniteStateMachine(self, Behavior.Fleeing())  # never hits, steps away from you

    @classmethod
    def generate(cls, level) -> NPC:
        animal = super().generate(level)
        animal.name = f"a {random.choice(cls.KINDS[type(animal.body_type)])}"
        animal.currency = 0
        return animal

    @property
    def sprite_path(self) -> str:
        # By size: a rat and a wild boar shouldn't look alike. People are drawn by what they are (Raider, a class).
        small = isinstance(self.body_type, SmallAnimal)
        return str(SPRITE_FOLDER / "Actors" / ("small_animal.png" if small else "animal.png"))


class PlayerClass(ABC):

    @property
    def name(self) -> str:
        raise NotImplementedError

    @property
    def tier(self) -> int:
        return 0

    @property
    def hit_points_max_base(self) -> int:
        raise NotImplementedError

    @property
    def sprite_path(self) -> str:
        raise NotImplementedError

    def __str__(self) -> str:
        return self.name


class WandererClass(PlayerClass):
    """Default player class with nothing special."""

    @property
    def name(self) -> str:
        return "Wanderer"

    @property
    def hit_points_max_base(self) -> int:
        return 50

    @property
    def tier(self) -> int:
        return 0

    @property
    def sprite_path(self):
        return str(SPRITE_FOLDER / "Actors" / "wanderer_class.png")


class Soldier(PlayerClass):
    """After joining some military (East or West)."""

    @property
    def name(self) -> str:
        return "Soldier"

    @property
    def hit_points_max_base(self) -> int:
        return 75

    @property
    def tier(self) -> int:
        return 1

    @property
    def sprite_path(self) -> str:
        return str(SPRITE_FOLDER / "Actors" / "soldier_class.png")


class RaiderClass(PlayerClass):
    """You've taken up arms without joining a military."""

    @property
    def name(self) -> str:
        return "Raider"

    @property
    def hit_points_max_base(self) -> int:
        return 60

    @property
    def tier(self) -> int:
        return 1

    @property
    def sprite_path(self) -> str:
        return str(SPRITE_FOLDER / "Actors" / "raider_class.png")


class PlayerCharacter(Actor):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._player_class: PlayerClass = WandererClass()
        self.experience: int = 0
        self._hit_points = self.hit_points_max = self._player_class.hit_points_max_base
        self.equipment_set: Items.EquipmentSet = Items.EquipmentSet()
        self.fov: int = self.fov_default
        self.inventory: Inventory = Inventory()
        self.currency: int = 1000
        # Banked in town: out of reach on a raid, and out of reach of whatever kills you on one.
        self.stash: Inventory = Inventory()
        self.stash_currency: int = 0
        # Levels of hideout, which earn into the stash every so many ticks whether you're playing or not.
        self.hideout_level: int = 0
        # The secure pouch: one item, carried, that a death leaves on you. Filled from the backpack, anywhere.
        self.pouch: Items.Equipment | None = None
        # What the last death took, phrased for a player, so whoever narrates it can say. Transient: not worth saving.
        self.last_death_loss: str = ""
        # Deaths so far. A player is revived the moment they die, so a fight watches this to know it's over.
        self.deaths: int = 0
        # An Events.EncounterEvent waiting on a /choose, if one is. Typed loosely: Events imports
        # this module, so this module cannot import Events back.
        self.pending_event: Any = None
        # (money, backpack, experience) as you last stepped out of a town, or None when no raid is on.
        # Not saved: a load out of town starts it afresh (Database), and a death throws it away.
        self.raid_start: Tuple[int, List[Items.Equipment], int] | None = None
        # An unattended raid (World.tick walks it): (the World.ticks it heads home at, deaths when it set out,
        # the deepest danger level it goes to). Saved, so a restart picks the raid up where it was.
        self.auto_raid: Tuple[int, int, int] | None = None
        # Resting where you stand (World.advance heals it), until you move or die.
        self.camping: bool = False

        self.equipment_set.equip(Weapons.Fist(), MainHandEquipment)
        self.equipment_set.equip(Weapons.Fist(), OffHandEquipment)

    def attempt_move(
        self, shift: Tuple[int, int]
    ) -> List[GameSpace.PlayerActionResponse]:
        # Walking on is how you ignore a stranger. Cleared before the step, so an encounter raised by
        # the square you land on survives.
        self.pending_event = None
        self.camping = False
        was_out = not isinstance(self.location, GameSpace.Town)
        if not was_out:
            self.raid_start = (self.currency, self.carried, self.experience)
        responses = super().attempt_move(shift)
        if (found := self.parent_world.pick_up_remains(self)) is not None:
            responses.append(found)
        # A death on the way lands you in town too, but it already threw raid_start away: no haul to report.
        if was_out and isinstance(self.location, GameSpace.Town) and self.raid_start is not None:
            responses.append(GameSpace.PlayerActionResponse(is_successful=True, source=self, text=self.extract()))
        return responses

    def extract(self) -> str:
        """End the raid in the town you're standing in and say what it brought home."""
        money, pack, experience = self.raid_start  # type: ignore[misc]
        self.raid_start = None
        found = [str(item) for item in self.carried if not any(item is had for had in pack)]
        if self.currency > money:
            found.append(f"${self.currency - money}")
        if self.experience > experience:
            found.append(f"{self.experience - experience} XP")
        haul = ", ".join(found) if found else "nothing but the walk"
        if found:
            self.parent_world.announcements.append((self, f"{self.name} made it back to {self.location.name} with {haul}."))
        return f"You make it back to {self.location.name}. Raid over, you brought home: {haul}."

    @property
    def player_class(self):
        return self._player_class

    @property
    def registered(self) -> bool:
        return self.location is not None

    @player_class.setter
    def player_class(self, class_: PlayerClass):
        self._player_class = class_
        self._refresh_hit_points_max()
        self._hit_points = self.hit_points_max

    @property
    def level(self) -> int:
        """Levels start at 1 and cost a flat EXPERIENCE_PER_LEVEL each, so progress is easy to read."""
        return 1 + self.experience // EXPERIENCE_PER_LEVEL

    @property
    def experience_to_next_level(self) -> int:
        return EXPERIENCE_PER_LEVEL - (self.experience % EXPERIENCE_PER_LEVEL)

    def _refresh_hit_points_max(self):
        """Toughness is the class's base plus what levelling added. Both halves can change underneath."""
        self.hit_points_max = (
            self._player_class.hit_points_max_base
            + HIT_POINTS_PER_PLAYER_LEVEL * (self.level - 1)
        )

    def gain_experience(self, amount: int) -> int:
        """Award experience and return how many levels it bought.

        A new level raises the ceiling and hands over the difference, so levelling up in a bad fight
        is a lifeline rather than a number that does nothing until the next trip to an inn.
        """
        if amount <= 0:
            return 0
        before = self.level
        self.experience += amount
        levels = self.level - before
        if levels:
            previous_max = self.hit_points_max
            self._refresh_hit_points_max()
            self.hit_points += self.hit_points_max - previous_max
        return levels

    @property
    def weapon(self) -> Union[Weapons.Weapon, None]:
        wep = self.equipment_set.main_hand
        if not isinstance(wep, Weapons.Weapon):
            return None
        return wep

    @property
    def has_weapon_equipped(self) -> bool:
        return self.weapon is not None

    def ready_weapon(self) -> Union[Weapons.Weapon, None]:
        """What to hit with right now: the weapon in hand, reloaded from the pack if it has run dry, or bare
        fists if there is nothing to load. An empty gun is a club, never a reason to stand there and take it."""
        weapon = self.weapon
        if isinstance(weapon, Weapons.ProjectileWeapon) and weapon.is_empty:
            weapon.reload(self)
            if weapon.is_empty:
                return Weapons.Fist()
        return weapon

    def equip(
        self, equipment: Equipment, equipment_type: Type[Equipment] | None = None
    ):
        self.equipment_set.equip(equipment, equipment_type)
        equipment.on_equip(self)

    def unequip(self, equipment: Equipment):
        self.equipment_set.unequip(equipment)
        equipment.on_unequip(self)

    def loot(self, corpse: NPC, response: GameSpace.PlayerActionResponse) -> str:
        """Claim a kill: the corpse's kit, its money, and the experience for it, recorded on `response`.

        Returns what was taken, phrased for a player, or "" if there was nothing in it. Emptying the
        corpse is what keeps a body from paying out twice, so every kill goes through here.
        """
        taken = [str(item) for item in corpse.inventory]
        if corpse.currency:
            taken.append(f"${corpse.currency}")
        response.items += corpse.inventory
        response.currency += corpse.currency
        self.inventory += corpse.inventory
        self.currency += corpse.currency
        corpse.inventory = Inventory()
        corpse.currency = 0
        self.parent_world.stats.kills += 1

        # A tougher corpse is worth more, and one below your level pays its share of yours: levels keep pace with
        # how deep you raid, rather than piling up on the wilds next to town.
        experience = corpse.hit_points_max // 2 * min(corpse.level, self.level) // self.level
        levels = self.gain_experience(experience)
        if experience:
            taken.append(f"{experience} XP")
        if levels:
            return ", ".join(taken) + f" (level {self.level}!)"
        return ", ".join(taken)

    @property
    def camp_heal(self) -> int:
        """Hit points a camp gives back every CAMP_HEAL_TICKS."""
        return max(1, round(self.hit_points_max * CAMP_HEAL_SHARE))

    def stash_put(self, index: int | None = None, money: int = 0) -> str:
        """Bank the carried item at `index` and/or `money`. Callers check the player is in a town."""
        return self._stash_move(index, money, to_stash=True)

    def stash_take(self, index: int | None = None, money: int = 0) -> str:
        """Pick up the stashed item at `index` and/or `money`, to carry out on the next raid."""
        return self._stash_move(index, money, to_stash=False)

    def _stash_move(self, index: int | None, money: int, to_stash: bool) -> str:
        """Returns what moved, phrased for a player. Raises ValueError, checked before anything moves."""
        source, dest = (self.inventory, self.stash) if to_stash else (self.stash, self.inventory)
        available = self.currency if to_stash else self.stash_currency
        if index is not None and not 0 <= index < len(source):
            raise ValueError(f"There's nothing at #{index}.")
        if not 0 <= money <= available:
            raise ValueError(f"You can only move between $0 and ${available}.")
        moved = []
        if index is not None:
            item = source.pop(index)
            dest.append(item)
            moved.append(str(item))
        if money:
            sign = 1 if to_stash else -1
            self.currency -= sign * money
            self.stash_currency += sign * money
            moved.append(f"${money}")
        return ", ".join(moved)

    @property
    def carried(self) -> List[Items.Equipment]:
        """The backpack and the pouch: what you'd bring home from a raid."""
        return list(self.inventory) + ([self.pouch] if self.pouch is not None else [])

    def pouch_swap(self, index: int | None = None) -> str:
        """Move the backpack item at `index` into the pouch, and whatever was in it back to the backpack.
        None just empties the pouch. Returns what moved, phrased for a player. Raises ValueError first."""
        if index is not None and not 0 <= index < len(self.inventory):
            raise ValueError(f"There's nothing at #{index}.")
        out, self.pouch = self.pouch, self.inventory.pop(index) if index is not None else None
        moved = []
        if self.pouch is not None:
            if self.pouch.is_equipped:  # a pouched item isn't in your hands, or a death would strip it
                self.unequip(self.pouch)
            moved.append(f"{self.pouch} into your pouch")
        if out is not None:
            self.inventory.append(out)
            moved.append(f"{out} back into your pack")
        return ", ".join(moved)

    @property
    def hideout_price(self) -> Tuple[int, int]:
        """(money, salvage) for the next hideout level: one or the other, never both."""
        if (self.hideout_level + 1) % HIDEOUT_SALVAGE_EVERY == 0:
            return 0, (self.hideout_level + 1) // HIDEOUT_SALVAGE_EVERY
        return int(HIDEOUT_COST * HIDEOUT_GROWTH**self.hideout_level), 0

    @property
    def stash_value(self) -> int:
        """The stash's money plus what its items are worth: the idle side's score."""
        return self.stash_currency + sum(int(item.base_value) for item in self.stash)

    def build_hideout(self) -> str:
        """Buy the next hideout level, from what's carried first and the stash after. Callers check the
        player is in a town. Returns what it bought, phrased for a player; raises ValueError if it can't."""
        money, salvage = self.hideout_price
        parts = [item for item in self.inventory + self.stash if isinstance(item, Items.Salvage)][:salvage]
        if self.currency + self.stash_currency < money or len(parts) < salvage:
            cost = f"{salvage} {Items.Salvage().name.lower()}" if salvage else f"${money}"
            raise ValueError(f"The next hideout level costs {cost}, carried and stashed together.")
        from_pocket = min(self.currency, money)
        self.currency -= from_pocket
        self.stash_currency -= money - from_pocket
        for part in parts:
            self.inventory.remove(part)  # Inventory.remove skips what isn't there
            self.stash.remove(part)
        self.hideout_level += 1
        return (
            f"Your hideout is level {self.hideout_level}: ${HIDEOUT_INCOME * self.hideout_level} into your stash "
            f"every {HIDEOUT_PAY_TICKS} ticks, whether you're here or not."
        )

    def lose_carried(self) -> Tuple[List[Items.Equipment], int]:
        """Strip everything on you: money, backpack and what you were wearing. Back to bare fists; the stash
        and the pouch are untouched. Returns the (items, money) taken, for the world to leave where you fell.
        """
        worn = [
            item
            for item in self.equipment_set
            if type(item) not in Items.EquipmentSet.SLOTS.values()  # the bare base classes are empty slots
            and not isinstance(item, Weapons.Fist)
            and not any(item is carried for carried in self.inventory)
        ]
        lost = list(self.inventory) + worn, self.currency
        for item in self.equipment_set:
            item.on_unequip(self)  # it's on the ground now, not on you
        self.currency = 0
        self.inventory = Inventory()
        self.equipment_set = Items.EquipmentSet()
        self.equipment_set.equip(Weapons.Fist(), MainHandEquipment)
        self.equipment_set.equip(Weapons.Fist(), OffHandEquipment)
        return lost

    def take_damage(self, damage: float):
        damage -= self.equipment_set.armor_count
        self.hit_points -= damage

    def on_death(self):
        self.parent_world.handle_player_death(self)
        return []  # nothing drops where they fell: handle_player_death deals with their gear

    @property
    def sprite_path(self) -> str:
        return self._player_class.sprite_path
