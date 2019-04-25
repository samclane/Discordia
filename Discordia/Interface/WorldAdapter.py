# Note: NEVER EVER import Discord here, this defeats the whole point of an ADAPTER

from typing import Dict

from Discordia.GameLogic import Actors
from Discordia.GameLogic.GameSpace import World


class NullWorldException(Exception):
    pass


class AlreadyRegisteredException(Exception):
    pass


class WorldAdapter:
    """
    Provides a public API for the game world for interfaces (like DiscordInterface) to connect to.
    """
    def __init__(self, gameworld: World = None):
        self.world: World = gameworld
        self.discord_player_map: Dict[int, Actors.PlayerCharacter] = {}

    def register_player(self, member_id: int, player_name: str):
        if not self.world:
            raise NullWorldException("Tried to register PlayerCharacter to empty world.")
        if self.is_registered(member_id):
            raise AlreadyRegisteredException("Member is already registered!")
        # Create new PlayerCharacter and add him into the existing world
        new_player = Actors.PlayerCharacter(parent_world=self.world, name=player_name)
        self.discord_player_map[member_id] = new_player
        self.world.add_actor(new_player, new_player.location)  # TODO location is null_space

    def is_registered(self, member_id: int) -> bool:
        return member_id in self.discord_player_map.keys()