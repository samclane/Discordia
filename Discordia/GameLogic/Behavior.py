from __future__ import annotations

from abc import ABC
from typing import Optional, TYPE_CHECKING

from Discordia.GameLogic import GameSpace

if TYPE_CHECKING:
    from Discordia.GameLogic import Actors


class State(ABC):
    """
    Represents a state in a state machine.
    """

    def on_enter(self, state_machine: "FiniteStateMachine"):
        """
        Called when the state is entered.
        """
        pass

    def on_exit(self, state_machine: "FiniteStateMachine"):
        """
        Called when the state is exited.
        """
        pass

    def update(
        self, state_machine: "FiniteStateMachine", *args, **kwargs
    ) -> Optional[int]:
        """
        Called once per turn. Returns the damage dealt, or None if the actor
        disengaged. May call state_machine.change_state() to transition.
        """
        return None

    def see(self, state_machine: "FiniteStateMachine", player: "Actors.PlayerCharacter") -> Optional[str]:
        """
        A player is in sight: move in response. Returns a warning to send them, if any.
        """
        return None


class FiniteStateMachine:

    def __init__(self, owner: "Actors.NPC", initial_state: Optional[State] = None):
        self.owner = owner
        self.current_state: Optional[State] = None
        if initial_state is not None:
            self.change_state(initial_state)

    def change_state(self, new_state: State):
        if self.current_state is not None:
            self.current_state.on_exit(self)
        self.current_state = new_state
        self.current_state.on_enter(self)

    def update(self, *args, **kwargs):
        if self.current_state is None:
            return None
        return self.current_state.update(self, *args, **kwargs)

    def see(self, player: "Actors.PlayerCharacter") -> Optional[str]:
        if self.current_state is None:
            return None
        return self.current_state.see(self, player)


class Aggressive(State):
    """Hits the target every turn, until badly hurt."""

    flee_at = 0.25

    def update(
        self, state_machine: FiniteStateMachine, target: "Actors.Actor"
    ) -> Optional[int]:
        npc = state_machine.owner
        if npc.hit_points <= npc.hit_points_max * self.flee_at:
            state_machine.change_state(Fleeing())
            return state_machine.update(target)
        target.take_damage(npc.base_attack)
        return npc.base_attack

    def see(self, state_machine: FiniteStateMachine, player: "Actors.PlayerCharacter") -> Optional[str]:
        """Close in. The first time it picks you, you hear about it: a raider walks no faster than you,
        so the warning is your chance to run."""
        npc = state_machine.owner
        warning = None
        if npc.quarry is not player:
            npc.quarry = player
            squares = max(abs(npc.location.x - player.location.x), abs(npc.location.y - player.location.y))
            where = GameSpace.bearing(player.location, npc.location)
            warning = f"{npc.name} has spotted you, {squares} square{'s' * (squares != 1)} to the {where}."
        npc.step(player.location)
        return warning


class Fleeing(State):
    """Disengaged: deals no damage and asks the fight to end."""

    def update(self, state_machine: FiniteStateMachine, target: "Actors.Actor") -> None:
        return None

    def see(self, state_machine: FiniteStateMachine, player: "Actors.PlayerCharacter") -> None:
        """Keep away, so a wounded raider is one you have to run down for its kit."""
        state_machine.owner.step(player.location, toward=False)
