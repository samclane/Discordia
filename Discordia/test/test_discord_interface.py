import asyncio
from types import SimpleNamespace
from typing import cast

import pytest
from discord import app_commands

from Discordia.GameLogic import Actors, GameSpace
from Discordia.Interface.DiscordInterface import SUPERSEDED, DiscordInterface
from Discordia.Interface.WorldAdapter import (
    InvalidSpaceException,
    NotRegisteredException,
    NotSpawnedException,
    WorldAdapter,
)

EXPECTED = {
    "register",
    "look",
    "move",
    "attack",
    "equipment",
    "inventory list",
    "inventory equip",
    "inventory unequip",
    "town status",
    "town inn",
    "town recruit",
    "town store list",
    "town store buy",
    "town store sell",
}


class StubAdapter:
    """Stands in for WorldAdapter: hands back one character, or refuses like the real one."""

    def __init__(self, character):
        self.character = character

    def get_player(self, member_id):
        if self.character is None:
            raise NotRegisteredException
        return self.character


def loaded_cog(adapter=None) -> DiscordInterface:
    """A DiscordInterface with its cog registered. The adapter is a stub, hence the cast."""
    interface = DiscordInterface(world_adapter=cast(WorldAdapter, adapter))
    asyncio.run(interface.bot.add_cog(interface))
    return interface


def command_named(
    interface: DiscordInterface, qualified_name: str
) -> app_commands.Command:
    """Look a command up by qualified name, so nested ones ('town inn') need no group walking."""
    return next(
        cmd
        for cmd in interface.bot.tree.walk_commands()
        if isinstance(cmd, app_commands.Command)
        and cmd.qualified_name == qualified_name
    )


def build(character, command_name="look"):
    """A cog wired to a stub adapter, plus a fake interaction the checks can read."""
    interface = loaded_cog(StubAdapter(character))
    command = command_named(interface, command_name)
    interaction = SimpleNamespace(command=command, user=SimpleNamespace(id=1))
    return interface, command, interaction


def test_slash_commands_registered():
    """The cog's app commands (and nested groups) all land in the bot's command tree."""
    interface = loaded_cog()
    names = {cmd.qualified_name for cmd in interface.bot.tree.walk_commands()}
    assert EXPECTED <= names, EXPECTED - names


def test_every_command_but_register_requires_a_character():
    interface = loaded_cog()
    unchecked = {
        cmd.qualified_name
        for cmd in interface.bot.tree.walk_commands()
        if isinstance(cmd, app_commands.Command) and not cmd.checks
    }
    assert unchecked == {"register"}, unchecked


def run_checks(command, interaction) -> bool:
    """Every prerequisite on the command, in whatever order they were stacked."""
    return all(asyncio.run(check(interaction)) for check in command.checks)


def test_check_rejects_unregistered():
    _, command, interaction = build(None)
    with pytest.raises(NotRegisteredException):
        run_checks(command, interaction)


def test_check_rejects_unspawned():
    _, command, interaction = build(SimpleNamespace(registered=False))
    with pytest.raises(NotSpawnedException):
        run_checks(command, interaction)


def test_check_passes_for_spawned_character():
    _, command, interaction = build(SimpleNamespace(registered=True))
    assert run_checks(command, interaction)


def test_space_check_rejects_character_outside_a_town():
    wilds = GameSpace.Wilds(0, 0, "Nowhere")
    _, command, interaction = build(
        SimpleNamespace(registered=True, location=wilds), "town inn"
    )
    with pytest.raises(InvalidSpaceException, match="town"):
        run_checks(command, interaction)


def test_space_check_passes_inside_a_town():
    town = GameSpace.Town(0, 0, "Testville")
    _, command, interaction = build(
        SimpleNamespace(registered=True, location=town), "town inn"
    )
    assert run_checks(command, interaction)


PLAYER = cast(Actors.PlayerCharacter, "a player")  # orders only ever key on identity


def ticking_interface(on_world_tick=lambda: None) -> DiscordInterface:
    """A cog whose world does nothing but record that it ticked."""
    adapter = SimpleNamespace(world=SimpleNamespace(tick=on_world_tick))
    return DiscordInterface(world_adapter=cast(WorldAdapter, adapter))


def test_orders_wait_for_the_tick_instead_of_resolving_when_typed():
    done = []
    interface = ticking_interface()

    async def scenario():
        future = interface.order(PLAYER, lambda: done.append("moved") or "arrived")
        assert not done, "the order ran before the tick"
        interface.tick()
        assert await future == "arrived"

    asyncio.run(scenario())
    assert done == ["moved"]


def test_a_second_order_replaces_the_first_so_spamming_buys_nothing():
    ran = []
    interface = ticking_interface()

    async def scenario():
        first = interface.order(PLAYER, lambda: ran.append("north"))
        second = interface.order(PLAYER, lambda: ran.append("south"))
        interface.tick()
        assert await first is SUPERSEDED
        assert await second is None

    asyncio.run(scenario())
    assert ran == ["south"]


def test_orders_resolve_before_the_world_acts():
    sequence = []
    interface = ticking_interface(on_world_tick=lambda: sequence.append("world"))

    async def scenario():
        future = interface.order(PLAYER, lambda: sequence.append("player"))
        interface.tick()
        await future

    asyncio.run(scenario())
    assert sequence == ["player", "world"]


def test_a_rejected_order_raises_in_the_command_that_asked_for_it():
    interface = ticking_interface()

    async def scenario():
        def blocked():
            raise InvalidSpaceException("You can't go that way.")

        future = interface.order(PLAYER, blocked)
        interface.tick()
        with pytest.raises(InvalidSpaceException):
            await future

    asyncio.run(scenario())


def test_jobs_run_on_the_bots_event_loop():
    ticks = []
    interface = DiscordInterface(
        world_adapter=cast(WorldAdapter, None),
        jobs=[(0.01, lambda: ticks.append(1), "Test job")],
    )

    async def run_a_few_ticks():
        interface._start_job(*interface.jobs[0])
        await asyncio.sleep(0.05)

    asyncio.run(run_a_few_ticks())
    assert len(ticks) > 1


def test_a_failing_job_keeps_ticking():
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError("job blew up")

    interface = DiscordInterface(world_adapter=cast(WorldAdapter, None))

    async def run_a_few_ticks():
        interface._start_job(0.01, boom, "Exploding job")
        await asyncio.sleep(0.05)

    asyncio.run(run_a_few_ticks())
    assert len(calls) > 1


if __name__ == "__main__":
    test_slash_commands_registered()
    test_every_command_but_register_requires_a_character()
    test_check_rejects_unregistered()
    test_check_rejects_unspawned()
    test_check_passes_for_spawned_character()
    test_space_check_rejects_character_outside_a_town()
    test_space_check_passes_inside_a_town()
    print("ok")
