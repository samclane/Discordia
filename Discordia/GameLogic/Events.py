from __future__ import annotations

import uuid
from abc import ABC
from typing import List

from Discordia.GameLogic import Actors


class Event(ABC):

    def __init__(self, probability: float, flavor_text: str):
        self.probability: float = probability
        self.uid: str = str(uuid.uuid4())
        self.flavor_text: str = flavor_text

    @classmethod
    def null_event(cls):
        return cls(1.0, "<Null Event>")

    def run(self, player_character: Actors.PlayerCharacter):
        raise NotImplementedError("Player {} tried to run a <Null Event>", player_character.name)


class CombatEvent(Event):

    def __init__(self, probability: float, flavor_text: str, enemies: list, conditions=None):
        super().__init__(probability, flavor_text)
        self.enemies: List[Actors.Enemy] = enemies
        self.SpecialConditions: [] = conditions

    def run(self, player_character: Actors.PlayerCharacter):
        print("We're in combat!")


class EncounterEvent(Event):

    def __init__(self, probability: float, flavor_text: str, choices_dict: dict, npc=None):
        super().__init__(probability, flavor_text)
        self.ChoiceDict = choices_dict
        self.NPCInvolved = npc

    def run(self, player_character):
        print("Ahh, encounter!")
        if self.flavor_text:
            print(self.flavor_text)


class MerchantEvent(Event):

    def __init__(self, probability, flavor_text, items):
        super().__init__(probability, flavor_text)
        self.Items: {} = items

    def run(self, player_character):
        print("Merchant encountered!")
