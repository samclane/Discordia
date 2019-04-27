# Note: NEVER EVER import Discord here, this defeats the whole point of an ADAPTER

from typing import Dict

from Discordia.GameLogic import Actors
from Discordia.GameLogic.GameSpace import World, Space, Town, Wilds


class NullWorldException(Exception):
    pass


class AlreadyRegisteredException(Exception):
    pass


class NotRegisteredException(Exception):
    pass


class WorldAdapter:
    """
    Provides a public API for the game world for interfaces (like DiscordInterface) to connect to.
    """
    def __init__(self, gameworld: World = None):
        self.world: World = gameworld
        self._discord_player_map: Dict[int, Actors.PlayerCharacter] = {}

    def register_player(self, member_id: int, player_name: str):
        if not self.world:
            raise NullWorldException("Tried to register PlayerCharacter to empty world.")
        if self.is_registered(member_id):
            raise AlreadyRegisteredException("Member is already registered!")

        # Create new PlayerCharacter and add him into the existing world
        new_player = Actors.PlayerCharacter(parent_world=self.world, name=player_name)
        self._discord_player_map[member_id] = new_player
        self.world.add_actor(new_player, self.world.starting_town)

    def is_registered(self, member_id: int) -> bool:
        return member_id in self._discord_player_map.keys()

    def get_player(self, member_id) -> Actors.PlayerCharacter:
        if not self.is_registered(member_id):
            raise NotRegisteredException

        # Sanity check
        assert member_id in self._discord_player_map.keys()

        return self._discord_player_map[member_id]

    def is_town(self, location: Space) -> bool:
        return isinstance(self.world.map[location.y][location.x], Town)

    def is_wilds(self, location: Space) -> bool:
        return isinstance(self.world.map[location.y][location.x], Wilds)