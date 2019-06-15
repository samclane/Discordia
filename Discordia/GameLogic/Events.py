from __future__ import annotations

import random
from abc import ABC
from typing import List, Iterator, Type

from Discordia.GameLogic import Actors, GameSpace
from Discordia.GameLogic.Procedural import normal


class Event(ABC):

    def __init__(self, probability: float, flavor_text: str):
        self.probability: float = probability
        self.flavor_text: str = flavor_text

    @classmethod
    def null_event(cls):
        evt = cls(1.0, "<Null Event>")
        evt.run = lambda _: None
        return evt

    def run(self, player_character: Actors.PlayerCharacter) -> Iterator[GameSpace.PlayerActionResponse]:
        raise NotImplementedError("Tried to run a generic event")

    @classmethod
    def generate(cls, level):
        raise NotImplementedError("Tried to initialize a generic event")


class CombatEvent(Event):

    def __init__(self, probability: float, flavor_text: str,
                 enemies: List[Actors.NPC], conditions=None):
        super().__init__(probability, flavor_text)
        self.enemies: List[Actors.NPC] = enemies
        self.special_conditions: [] = conditions

    @classmethod
    def generate(cls, level):
        probability = random.random()
        num_enemies = normal(level, positive=True, integer=True)
        flavor_text = "<Generated CombatEvent>"
        enemies = [Actors.NPC.generate(level) for _ in range(num_enemies)]
        return cls(probability, flavor_text, enemies)

    def run(self, player_character: Actors.PlayerCharacter) -> Iterator[GameSpace.PlayerActionResponse]:
        # Just mow the enemies down in order
        victory_response = GameSpace.PlayerActionResponse(source=player_character)
        for enemy in self.enemies:
            kill_response = GameSpace.PlayerActionResponse(source=player_character)

            while not enemy.is_dead:
                # WARN An infinite loop can appear here.
                attack_response = GameSpace.PlayerActionResponse(source=player_character)
                # Damage is always calculated at full power (min distance)
                assert player_character.has_weapon_equipped
                dmg = player_character.weapon.damage
                player_character.weapon.on_damage()
                enemy.take_damage(dmg)
                attack_response.is_successful = True
                attack_response.damage = dmg
                attack_response.target = enemy
                attack_response.text = f"{player_character.name} does {dmg} dmg to {enemy.name}."
                yield attack_response

                defense_response = GameSpace.PlayerActionResponse(source=player_character)
                dmg = enemy.base_attack
                player_character.take_damage(dmg)
                defense_response.damage = dmg
                defense_response.target = enemy
                defense_response.text = f"{player_character.name} takes {dmg} dmg from {enemy.name}."
                defense_response.is_successful = True
                yield defense_response
                if player_character.is_dead:
                    break

            if not player_character.is_dead:
                kill_response.items += enemy.on_death()
                kill_response.is_successful = True
                player_character.inventory += kill_response.items
                kill_response.text = f"{player_character.name} kills {enemy.name}, " \
                    f"receiving {','.join([str(item) for item in kill_response.items])}"
                yield kill_response
            else:
                break

        if not player_character.is_dead:
            victory_response.is_successful = True
            victory_response.text = f"{player_character.name} has successfully slain their foes."

        else:
            victory_response.is_successful = False
            victory_response.text = f"{player_character.name} has fallen in combat. " \
                f"They'll be revived in the starting town."

        return victory_response


class EncounterEvent(Event):

    def __init__(self, probability: float, flavor_text: str, choices_dict: dict,
                 npc=None):
        super().__init__(probability, flavor_text)
        self.choice_dict = choices_dict
        self.npc_involved = npc

    def run(self, player_character) -> Iterator[GameSpace.PlayerActionResponse]:
        yield GameSpace.PlayerActionResponse(is_successful=True, text=self.flavor_text, source=player_character)

    @classmethod
    def generate(cls, level) -> EncounterEvent:
        probability = random.random()
        npc_involved = Actors.NPC.generate(level)
        flavor_text = f"<Encountered NPC {npc_involved.name} (p={probability})>"
        choices = {"<test>": "<test>"}
        return cls(probability, flavor_text, choices, npc_involved)


class MerchantEvent(Event):

    def __init__(self, probability, flavor_text, items):
        super().__init__(probability, flavor_text)
        self.items: {} = items

    def run(self, player_character):
        yield GameSpace.PlayerActionResponse(is_successful=True, text=self.flavor_text, source=player_character)

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
