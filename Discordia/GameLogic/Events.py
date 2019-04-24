import uuid
from abc import ABC
from typing import List

from Discordia.GameLogic import Actors


class Event(ABC):

    def __init__(self, probability: float, flavor: str):
        self.probability: float = probability
        self.uid: str = str(uuid.uuid4())
        self.flavor_text: str = flavor

    def run(self, player_character):
        print("Error: Tried to run a generic event or class didn't implement run. Please use an event subclass.")


class CombatEvent(Event):

    def __init__(self, probability: float, flavor: str, enemies: list, conditions=None):
        super().__init__(probability, flavor)
        self.enemies: List[Actors.Enemy] = enemies
        self.SpecialConditions: [] = conditions

    def run(self, player_character: Actors.PlayerCharacter):
        print("We're in combat!")


class EncounterEvent(Event):

    def __init__(self, probability: float, flavor: str, choices_dict: dict, npc=None):
        super().__init__(probability, flavor)
        self.ChoiceDict = choices_dict
        self.NPCInvolved = npc

    def run(self, player_character):
        print("Ahh, encounter!")
        if self.flavor_text:
            print(self.flavor_text)


class MerchantEvent(Event):

    def __init__(self, probability, flavor, items):
        super().__init__(probability, flavor)
        self.Items: {} = items

    def run(self, player_character):
        print("Merchant encountered!")
