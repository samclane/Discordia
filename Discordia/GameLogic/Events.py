from __future__ import annotations

import random
from abc import ABC
from typing import List, Iterator, Type

from Discordia.GameLogic import Actors, GameSpace


class Event(ABC):

    def __init__(self, probability: float, flavor_text: str):
        self.probability: float = probability
        self.flavor_text: str = flavor_text

    @classmethod
    def null_event(cls):
        return cls(1.0, "<Null Event>")

    def run(self, player_character: Actors.PlayerCharacter) -> Iterator[GameSpace.PlayerActionResponse]:
        pass

    @classmethod
    def generate(cls):
        raise NotImplementedError("Tried to initialize a generic event")


NUM_ENEMIES = 5  # TODO Un-hardcode this


class CombatEvent(Event):

    def __init__(self, probability: float, flavor_text: str,
                 enemies: List[Actors.Enemy], conditions=None):
        super().__init__(probability, flavor_text)
        self.enemies: List[Actors.Enemy] = enemies
        self.special_conditions: [] = conditions

    def run(self, player_character: Actors.PlayerCharacter) -> Iterator[GameSpace.PlayerActionResponse]:
        print("We're in event combat!")
        # Just mow the enemies down in order
        victory_response = GameSpace.PlayerActionResponse()
        for enemy in self.enemies:
            kill_response = GameSpace.PlayerActionResponse()

            while not enemy.is_dead:
                attack_response = GameSpace.PlayerActionResponse()
                # Damage is always calculated at full power (min distance)
                dmg = player_character.weapon.damage or 0
                player_character.weapon.on_damage()
                enemy.take_damage(dmg)
                attack_response.is_successful = True
                attack_response.damage = dmg
                attack_response.target = enemy
                attack_response.text = f"{player_character.name} does {dmg} dmg to {enemy.name}."
                yield attack_response

                defense_response = GameSpace.PlayerActionResponse()
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
                kill_response.text = f"{player_character.name} kills {enemy.name}, receiving {','.join(kill_response.items)}"
                yield kill_response
            else:
                break

        if not player_character.is_dead:
            victory_response.is_successful = True
            victory_response.text = f"{player_character.name} has successfully slain their foes."

        else:
            victory_response.is_successful = False
            victory_response.text = f"{player_character.name} has fallen in combat. They'll be revived in the starting town."

        return victory_response

    @classmethod
    def generate(cls):
        probability = random.random()
        flavor_text = "<Generated CombatEvent>"
        enemies = [Actors.Enemy.generate() for _ in range(random.randint(1, NUM_ENEMIES))]
        return cls(probability, flavor_text, enemies)


class EncounterEvent(Event):

    def __init__(self, probability: float, flavor_text: str, choices_dict: dict,
                 npc=None):
        super().__init__(probability, flavor_text)
        self.choice_dict = choices_dict
        self.npc_involved = npc

    def run(self, player_character):
        if self.flavor_text:
            yield GameSpace.PlayerActionResponse(text=self.flavor_text)

    @classmethod
    def generate(cls):
        probability = random.random()
        npc_involved = Actors.NPC.generate()
        flavor_text = f"<Encountered NPC {npc_involved.name} (p={probability})>"
        choices = {"<test>": "<test>"}
        return cls(probability, flavor_text, choices, npc_involved)


class MerchantEvent(Event):

    def __init__(self, probability, flavor_text, items):
        super().__init__(probability, flavor_text)
        self.items: {} = items

    def run(self, player_character):
        yield GameSpace.PlayerActionResponse(text=self.flavor_text)

    @classmethod
    def generate(cls):
        probability = random.random()
        flavor_text = f"<Generated MerchantEvent>"
        items = {}
        return cls(probability, flavor_text, items)


def generate_event() -> Event:
    event_class: Type[Event] = random.choice(Event.__subclasses__())

    event = event_class.generate()

    return event
