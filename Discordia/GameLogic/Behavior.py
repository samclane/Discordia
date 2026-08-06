from __future__ import annotations

from abc import ABC
from typing import Optional, TYPE_CHECKING

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


class Fleeing(State):
    """Disengaged: deals no damage and asks the fight to end."""

    def update(self, state_machine: FiniteStateMachine, target: "Actors.Actor") -> None:
        # ponytail: no map movement, combat is abstract (no positions). Add a step
        # away from the target here once NPCs move on the world grid.
        return None
