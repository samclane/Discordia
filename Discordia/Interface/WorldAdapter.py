# Note: NEVER EVER import Discord here, this defeats the whole point of an ADAPTER

from typing import Dict, Tuple, List

from Discordia.GameLogic import Actors
from Discordia.GameLogic.GameSpace import World, Space, Town, Wilds, Direction, PlayerActionResponse
from Discordia.GameLogic.Weapons import RangedWeapon


class NullWorldException(Exception):
    pass


class AlreadyRegisteredException(Exception):
    pass


class NotRegisteredException(Exception):
    pass


class InvalidSpaceException(Exception):
    pass


class ItemRequirementException(Exception):
    pass


class NoWeaponEquippedException(ItemRequirementException):
    pass


class RangedAttackException(Exception):
    pass

class CombatException(Exception):
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

    def move_player(self, character: Actors.PlayerCharacter, direction: Tuple[int, int]):
        if not character.attempt_move(direction):
            raise InvalidSpaceException("Trying to move to an unwalkable space.")

    def get_nearby_npcs(self, character: Actors.PlayerCharacter) -> List[Actors.NPC]:
        location: Space = character.location
        fov: int = character.fov
        npcs: List[Actors.NPC] = self.world.get_npcs_in_region(self.world.get_adjacent_spaces(location, fov))
        return npcs

    def get_nearby_players(self, character: Actors.PlayerCharacter) -> List[Actors.PlayerCharacter]:
        location: Space = character.location
        fov: int = character.fov
        players: List[Actors.PlayerCharacter] = self.world.get_players_in_region(self.world.get_adjacent_spaces(location, fov))
        return players

    def attack(self, character: Actors.PlayerCharacter, direction: Direction) -> PlayerActionResponse:
        if not character.has_weapon_equipped:
            raise NoWeaponEquippedException
        if direction and not isinstance(character.weapon, RangedWeapon):
            raise RangedAttackException
        response: PlayerActionResponse = self.world.attack(character, direction)
        if not response.is_successful:
            raise CombatException(response.text)
        return response


