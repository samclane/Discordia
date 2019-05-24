from __future__ import annotations

import uuid
from abc import ABC
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
        response = GameSpace.PlayerActionResponse()
        # Just mow the enemies down in order
        for enemy in self.enemies:
            while enemy.hit_points > 0:
                # Damage is always calculated at full power (min distance)
                dmg = player_character.weapon.damage
                player_character.weapon.on_damage()
                enemy.take_damage(dmg)
                response.is_successful = True
                response.damage = dmg
                response.target = enemy
                yield response


class EncounterEvent(Event):

    def __init__(self, player: Actors.PlayerCharacter, probability: float, flavor_text: str, choices_dict: dict,
                 npc=None):
        super().__init__(player, probability, flavor_text)
        self.choice_dict = choices_dict
        self.npc_involved = npc

    def run(self, player_character):
        print("Ahh, encounter!")
        if self.flavor_text:
            yield GameSpace.PlayerActionResponse(text=self.flavor_text)


class MerchantEvent(Event):

    def __init__(self, player: Actors.PlayerCharacter, probability, flavor_text, items):
        super().__init__(player, probability, flavor_text)
        self.items: {} = items

    def run(self, player_character):
        yield GameSpace.PlayerActionResponse(text="Merchant Encountered")
