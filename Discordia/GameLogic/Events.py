from __future__ import annotations

import random
from abc import ABC
from typing import List, Iterator, Type

from Discordia.GameLogic import Actors, GameSpace, Items
from Discordia.GameLogic.Procedural import normal


class Event(ABC):

    def __init__(self, probability: float, flavor_text: str):
        self.probability: float = probability
        self.flavor_text: str = flavor_text

    @classmethod
    def null_event(cls):
        evt = cls(1.0, "<Null Event>")
        evt.run = lambda player_character: iter([])
        return evt

    def run(
        self, player_character: Actors.PlayerCharacter
    ) -> Iterator[GameSpace.PlayerActionResponse]:
        raise NotImplementedError("Tried to run a generic event")

    @classmethod
    def generate(cls, level):
        raise NotImplementedError("Tried to initialize a generic event")


class CombatEvent(Event):

    def __init__(self, probability: float, flavor_text: str, enemies: List[Actors.NPC]):
        super().__init__(probability, flavor_text)
        self.enemies: List[Actors.NPC] = enemies

    @classmethod
    def generate(cls, level):
        probability = random.random()
        num_enemies = normal(level, positive=True, integer=True)
        flavor_text = "<Generated CombatEvent>"
        enemies = [Actors.NPC.generate(level) for _ in range(num_enemies)]
        return cls(probability, flavor_text, enemies)

    def run(
        self, player_character: Actors.PlayerCharacter
    ) -> Iterator[GameSpace.PlayerActionResponse]:
        # Just mow the enemies down in order
        victory_response = GameSpace.PlayerActionResponse(source=player_character)
        for enemy in self.enemies:
            kill_response = GameSpace.PlayerActionResponse(source=player_character)

            while not enemy.is_dead:
                # WARN An infinite loop can appear here.
                attack_response = GameSpace.PlayerActionResponse(
                    source=player_character
                )
                # Damage is always calculated at full power (min distance)
                if player_character.weapon is None:
                    attack_response.is_successful = False
                    attack_response.text = (
                        f"{player_character.name} has no weapon to attack with!"
                    )
                    yield attack_response
                    break
                dmg = int(player_character.weapon.damage)
                player_character.weapon.on_damage()
                enemy.take_damage(dmg)
                attack_response.is_successful = True
                attack_response.damage = dmg
                attack_response.target = enemy
                attack_response.text = (
                    f"{player_character.name} does {dmg} dmg to {enemy.name}."
                )
                yield attack_response

                defense_response = GameSpace.PlayerActionResponse(
                    source=player_character
                )
                dmg = enemy.brain.update(player_character)
                if dmg is None:  # the enemy disengaged; on to the next one
                    defense_response.is_successful = True
                    defense_response.target = enemy
                    defense_response.text = f"{enemy.name} flees the fight."
                    yield defense_response
                    break
                defense_response.damage = dmg
                defense_response.target = enemy
                defense_response.text = (
                    f"{player_character.name} takes {dmg} dmg from {enemy.name}."
                )
                defense_response.is_successful = True
                yield defense_response
                if player_character.is_dead:
                    break

            if enemy.is_dead:
                enemy.on_death()
                drops = player_character.loot(enemy, kill_response)
                kill_response.is_successful = True
                kill_response.text = f"{player_character.name} kills {enemy.name}" + (
                    f", receiving {drops}" if drops else ""
                )
                yield kill_response
            # A live enemy means the player died or can't fight; either way, stop.
            elif player_character.is_dead or player_character.weapon is None:
                break

        if not player_character.is_dead:
            victory_response.is_successful = True
            victory_response.text = (
                f"{player_character.name} has successfully slain their foes."
            )

        else:
            victory_response.is_successful = False
            victory_response.text = (
                f"{player_character.name} has fallen in combat. "
                f"They'll be revived in the starting town."
                + GameSpace.death_toll_text(player_character)
            )

        yield victory_response


class EncounterEvent(Event):
    """A stranger on the road who waits for the player to decide what to do about them.

    Unlike a CombatEvent, this does not resolve where it is raised: it parks itself on the character
    and waits for a `/choose`. Walking on drops it, which is what "ignore" means by default.
    """

    CHOICES = ("talk", "rob", "ignore")

    def __init__(self, probability: float, flavor_text: str, npc: Actors.NPC):
        super().__init__(probability, flavor_text)
        self.npc_involved: Actors.NPC = npc

    def run(self, player_character) -> Iterator[GameSpace.PlayerActionResponse]:
        player_character.pending_encounter = self
        yield GameSpace.PlayerActionResponse(
            is_successful=True, text=self.flavor_text, source=player_character
        )

    @classmethod
    def generate(cls, level) -> EncounterEvent:
        npc = Actors.NPC.generate(level)
        flavor_text = (
            f"{npc.name} is on the road ahead, watching you come. "
            f"Use /choose to talk, rob, or ignore them."
        )
        return cls(random.random(), flavor_text, npc)

    def resolve(
        self, player_character: Actors.PlayerCharacter, choice: str
    ) -> List[GameSpace.PlayerActionResponse]:
        """Play out the player's decision. One encounter, one outcome, whichever way it goes."""
        if choice not in self.CHOICES:
            raise ValueError(f"{choice!r} is not one of {self.CHOICES}")
        player_character.pending_encounter = None
        npc = self.npc_involved
        response = GameSpace.PlayerActionResponse(
            is_successful=True, source=player_character, target=npc
        )

        if choice == "ignore":
            response.text = f"You walk on. {npc.name} watches you go."
        elif choice == "talk":
            response.text = f"{npc.name} says: {self._directions(player_character)}"
        else:
            self._rob(player_character, response)
        return [response]

    def _directions(self, player_character: Actors.PlayerCharacter) -> str:
        """The one thing a stranger in the wilds is reliably good for: where the nearest town is."""
        here = player_character.location
        world = player_character.parent_world
        towns = [town for town in getattr(world, "towns", []) if town != here]
        if not towns or here is None:
            return "nothing you did not already know."
        nearest = min(towns, key=here.distance)
        return (
            f'"{nearest.name} is {round(here.distance(nearest))} squares '
            f'{GameSpace.bearing(here, nearest)} of here."'
        )

    def _rob(
        self,
        player_character: Actors.PlayerCharacter,
        response: GameSpace.PlayerActionResponse,
    ):
        """A contest between the player's level and the stranger's, who is only as tough as their hide."""
        npc = self.npc_involved
        npc_level = max(1, npc.hit_points_max // Actors.HIT_POINTS_PER_LEVEL)
        odds = player_character.level / (player_character.level + npc_level)
        if random.random() >= odds:
            hurt = max(1, npc.hit_points_max // 5)
            player_character.take_damage(hurt)
            response.is_successful = False
            response.damage = hurt
            response.text = (
                f"{npc.name} was ready for that. You take {hurt} damage, "
                f"and they are gone by the time you are up."
            )
            return
        if not npc.currency:
            response.text = (
                f"You put {npc.name} on the ground and find nothing worth taking."
            )
            return
        response.currency = npc.currency
        player_character.currency += npc.currency
        npc.currency = 0
        response.text = (
            f"You take ${response.currency} off {npc.name} and leave them in the dirt."
        )


class MerchantEvent(Event):

    def __init__(
        self, probability: float, flavor_text: str, items: dict[str, Items.Equipment]
    ):
        super().__init__(probability, flavor_text)
        self.items: dict[str, Items.Equipment] = items

    def run(self, player_character):
        yield GameSpace.PlayerActionResponse(
            is_successful=True, text=self.flavor_text, source=player_character
        )

    @classmethod
    def generate(cls, level) -> MerchantEvent:
        probability = random.random()
        flavor_text = f"<Generated MerchantEvent>"
        items = {}
        return cls(probability, flavor_text, items)


def generate_event(level) -> Event:
    event_class: Type[Event] = random.choice(Event.__subclasses__())

    event = event_class.generate(level)

    return event
