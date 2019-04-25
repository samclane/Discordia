# Note: NEVER EVER import Discord here, this defeats the whole point of an ADAPTER

from typing import Dict

from Discordia.GameLogic import Actors
from Discordia.GameLogic.GameSpace import World


class RegistrationException(Exception):
    pass


class WorldAdapter:
    """
    Provides a public API for the game world for interfaces (like DiscordInterface) to connect to.
    """
    def __init__(self, gameworld: World = None):
        self.world: World = gameworld
        self.discord_player_map: Dict[int, Actors.PlayerCharacter] = {}

    def register_player(self, member_id: int):
        if not self.world:
            raise Exception("Tried to register PlayerCharacter to empty world.")
        if self.is_registered(member_id):
            raise RegistrationException("Member is already registered!")
        self.discord_player_map[member_id] = Actors.PlayerCharacter(parent_world=self.world)

    def is_registered(self, member_id: int):
        return member_id in self.discord_player_map.keys()