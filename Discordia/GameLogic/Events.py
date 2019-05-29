from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import List, Iterator

from Discordia.GameLogic import Actors, GameSpace


class Event(ABC):

    def __init__(self, player: Actors.PlayerCharacter, probability: float, flavor_text: str):
        self.player = player
        self.probability: float = probability
        self.uid: str = str(uuid.uuid4())
        self.flavor_text: str = flavor_text

    @classmethod
    def null_event(cls):
        return cls(None, 1.0, "<Null Event>")

    @abstractmethod
    def run(self, player_character: Actors.PlayerCharacter) -> Iterator[GameSpace.PlayerActionResponse]:
        raise NotImplementedError(f"Player {player_character.name} tried to run a <Null Event>")


class CombatEvent(Event):

    def __init__(self, player: Actors.PlayerCharacter, probability: float, flavor_text: str,
                 enemies: List[Actors.Enemy], conditions=None):
        super().__init__(player, probability, flavor_text)
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
                dmg = player_character.weapon.damage
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


class EncounterEvent(Event):

    def __init__(self, player: Actors.PlayerCharacter, probability: float, flavor_text: str, choices_dict: dict,
                 npc=None):
        super().__init__(player, probability, flavor_text)
        self.choice_dict = choices_dict
        self.npc_involved = npc

    def run(self, player_character):
        if self.flavor_text:
            yield GameSpace.PlayerActionResponse(text=self.flavor_text)


class MerchantEvent(Event):

    def __init__(self, player: Actors.PlayerCharacter, probability, flavor_text, items):
        super().__init__(player, probability, flavor_text)
        self.items: {} = items

    def run(self, player_character):
        yield GameSpace.PlayerActionResponse(text="Merchant Encountered")
