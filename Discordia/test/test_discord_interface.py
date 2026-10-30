import asyncio
from types import SimpleNamespace
from typing import Any, cast

import discord
import pytest
from discord import app_commands

from Discordia.GameLogic import Actors, GameSpace, Weapons
from Discordia.Interface.DiscordInterface import (
    SUPERSEDED,
    DiscordInterface,
    GameCheckFailure,
    WrongChannel,
    _defer,
    _send,
    _stock_choices,
    _stock_listing,
)
from Discordia.Interface.WorldAdapter import (
    InvalidSpaceException,
    NotRegisteredException,
    NotSpawnedException,
    GuildSettings,
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
    "inventory pouch",
    "town status",
    "town inn",
    "town recruit",
    "town store list",
    "town store buy",
    "town store sell",
    "stash list",
    "stash put",
    "stash take",
    "hideout build",
    "raid",
    "camp",
    "help",
    "weblogin",
    "settings",
}


class StubAdapter:
    """Stands in for WorldAdapter: hands back one character, or refuses like the real one."""

    def __init__(self, character):
        self.character = character
        self.guild_settings = {}

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


def test_every_command_but_register_settings_and_help_requires_a_character():
    interface = loaded_cog()
    unchecked = {
        cmd.qualified_name
        for cmd in interface.bot.tree.walk_commands()
        if isinstance(cmd, app_commands.Command) and not cmd.checks
    }
    assert unchecked == {"register", "settings", "help"}, unchecked


def run_checks(command, interaction) -> bool:
    """Every prerequisite on the command, in whatever order they were stacked. Raises the game exception
    a check refused with."""
    try:
        return all(asyncio.run(check(interaction)) for check in command.checks)
    except GameCheckFailure as failure:
        raise failure.original


def test_a_refusing_check_reaches_the_error_handler():
    """The tree only handles AppCommandErrors. A bare game exception escapes it, and the player is left
    with "The application did not respond" instead of being told to /register."""
    _, command, interaction = build(None)
    interaction.guild_id = None  # a DM: no server's channel settings to pass first
    with pytest.raises(GameCheckFailure) as caught:  # an AppCommandError, so the tree handles it
        asyncio.run(command._invoke_with_namespace(cast(Any, interaction), cast(Any, None)))
    assert isinstance(caught.value.original, NotRegisteredException)


def channel_check(channels, channel_id, parent_id=None, command="look", guild_id: int | None = 5):
    """Run the cog's channel gate for a command typed in `channel_id` of a server that allows `channels`."""
    adapter = SimpleNamespace(guild_settings={5: GuildSettings(channels=channels)})
    interface = loaded_cog(adapter)
    interaction = SimpleNamespace(
        guild_id=guild_id,
        channel_id=channel_id,
        channel=SimpleNamespace(parent_id=parent_id),
        command=command_named(interface, command),
    )
    return asyncio.run(interface.interaction_check(cast(Any, interaction)))


def test_commands_only_work_in_the_channels_a_server_picked():
    assert channel_check([], 1), "no channels picked means everywhere"
    assert channel_check([1, 2], 2)
    assert channel_check([1, 2], 99, parent_id=1), "a thread counts as its channel"
    assert channel_check([1], 99, guild_id=6), "another server's settings don't apply"
    assert channel_check([1], 99, guild_id=None), "nor in DMs"
    assert channel_check([1], 99, command="settings"), "admins can always get back to the settings"
    with pytest.raises(WrongChannel, match="<#1>, <#2>"):
        channel_check([1, 2], 99)


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


@pytest.mark.parametrize("name", ["stash list", "stash put", "stash take", "hideout build", "raid"])
def test_the_stash_is_only_reachable_from_a_town(name):
    wilds = GameSpace.Wilds(0, 0, "Nowhere")
    _, command, interaction = build(SimpleNamespace(registered=True, location=wilds), name)
    with pytest.raises(InvalidSpaceException, match="town"):
        run_checks(command, interaction)


def _little_store():
    from Discordia.GameLogic import Armor, Items

    # Out of order on purpose: the listing sorts, but the #s stay the store's own.
    return GameSpace.Store([Weapons.MosinNagant(), Weapons.Ammo9mm(), Weapons.Hammer(), Items.Salvage(), Armor.SSh68()])


def test_the_stock_listing_groups_sorts_and_marks_what_you_cannot_afford():
    character = Actors.PlayerCharacter(None, name="Shopper")
    character.currency = 150
    text = _stock_listing(_little_store(), character)
    rows = [line for line in text.splitlines() if line.startswith("#")]
    assert [row.split()[0] for row in rows] == ["#2", "#0", "#4", "#1", "#3"]  # weapons cheapest first, then armor...
    assert rows[1].endswith("$370 ✗") and not rows[0].endswith("✗")
    assert text.startswith("You have $150.") and "```" in text
    assert [line.split()[0] for line in _stock_listing(_little_store(), character, "ammo").splitlines()[2:-1]] == [
        "AMMO",
        "#1",
    ]


def test_buying_autocompletes_by_name_cheapest_first():
    store = _little_store()
    prices = [store.get_price(store.inventory[c.value]) for c in _stock_choices(store, "")]
    assert len(prices) == len(store.inventory) and prices == sorted(prices)
    hammer = _stock_choices(store, "ham")
    assert [(c.name, c.value) for c in hammer] == [("Hammer · $100", 2)]
    assert [c.value for c in _stock_choices(store, "#0")] == [0]  # typing the old index still finds it


def test_buy_autocomplete_only_suggests_in_a_town():
    town = GameSpace.Town(0, 0, "Testville", store=_little_store())
    for location, expected in [(town, 1), (GameSpace.Wilds(0, 0, "Nowhere"), 0)]:
        interface, _, interaction = build(SimpleNamespace(location=location), "town store buy")
        assert len(asyncio.run(cast(Any, interface)._buy_choices(interaction, "ham"))) == expected
    interface, _, interaction = build(None, "town store buy")  # not registered
    assert asyncio.run(cast(Any, interface)._buy_choices(interaction, "ham")) == []


def test_space_check_passes_inside_a_town():
    town = GameSpace.Town(0, 0, "Testville")
    _, command, interaction = build(
        SimpleNamespace(registered=True, location=town), "town inn"
    )
    assert run_checks(command, interaction)


PLAYER = cast(Actors.PlayerCharacter, "a player")  # orders only ever key on identity


def ticking_interface(on_world_tick=lambda: []) -> DiscordInterface:
    """A cog whose world does nothing but record that it ticked and report its events."""
    adapter = SimpleNamespace(
        world=SimpleNamespace(tick=on_world_tick, stats=GameSpace.Stats()),
        get_member_id=lambda character: 7,
    )
    return DiscordInterface(world_adapter=cast(WorldAdapter, adapter))


def test_orders_wait_for_the_tick_instead_of_resolving_when_typed():
    done = []
    interface = ticking_interface()

    async def scenario():
        future = interface.order(PLAYER, lambda: done.append("moved") or "arrived")
        assert not done, "the order ran before the tick"
        await interface.tick()
        assert await future == "arrived"

    asyncio.run(scenario())
    assert done == ["moved"]


def test_a_second_order_replaces_the_first_so_spamming_buys_nothing():
    ran = []
    interface = ticking_interface()

    async def scenario():
        first = interface.order(PLAYER, lambda: ran.append("north"))
        second = interface.order(PLAYER, lambda: ran.append("south"))
        await interface.tick()
        assert await first is SUPERSEDED
        assert await second is None

    asyncio.run(scenario())
    assert ran == ["south"]


def test_orders_resolve_before_the_world_acts():
    sequence = []
    interface = ticking_interface(on_world_tick=lambda: sequence.append("world") or [])

    async def scenario():
        future = interface.order(PLAYER, lambda: sequence.append("player"))
        await interface.tick()
        await future

    asyncio.run(scenario())
    assert sequence == ["player", "world"]


def test_a_rejected_order_raises_in_the_command_that_asked_for_it():
    interface = ticking_interface()

    async def scenario():
        def blocked():
            raise InvalidSpaceException("You can't go that way.")

        future = interface.order(PLAYER, blocked)
        await interface.tick()
        with pytest.raises(InvalidSpaceException):
            await future

    asyncio.run(scenario())


def stub_user(interface: DiscordInterface, sent: list, raises=None):
    """Point the bot's user lookup at a recorder, so a DM lands in `sent` instead of on Discord."""

    async def send(text):
        if raises is not None:
            raise raises
        sent.append(text)

    interface.bot.get_user = lambda member_id: SimpleNamespace(send=send)  # type: ignore[method-assign]


def hit_by_an_npc():
    return [
        GameSpace.PlayerActionResponse(
            is_successful=True, damage=2, target=PLAYER, text="A raider hits you."
        )
    ]


def test_a_player_gets_dmd_about_what_happened_while_they_werent_looking():
    sent = []
    interface = ticking_interface(on_world_tick=hit_by_an_npc)
    stub_user(interface, sent)

    asyncio.run(interface.tick())
    assert sent == ["A raider hits you."]


class Body:
    """Something a fight can be keyed on: hashable, unlike a SimpleNamespace."""

    deaths = 0


def test_a_fight_dms_its_first_hit_and_its_death_not_every_blow():
    sent = []
    raider, player = cast(Any, Body()), cast(Any, Body())  # stand-ins for Actors
    script = iter(["first", "second", "third", None, "again", "fourth", "you black out"])

    def world_tick():
        text = next(script)
        if text == "you black out":
            player.deaths += 1  # handle_player_death runs inside the world tick
        return [GameSpace.PlayerActionResponse(damage=2, source=raider, target=player, text=text)] if text else []

    interface = ticking_interface(on_world_tick=world_tick)
    stub_user(interface, sent)
    for _ in range(3):
        asyncio.run(interface.tick())
    assert sent == ["first"]  # one raider, one fight, one DM
    asyncio.run(interface.tick())  # it let up
    asyncio.run(interface.tick())
    assert sent == ["first", "again"]  # a new fight is news again
    asyncio.run(interface.tick())
    asyncio.run(interface.tick())
    assert sent == ["first", "again", "you black out"]  # and how it ended always is


def test_a_tick_full_of_npcs_is_one_dm_not_ten():
    sent = []
    interface = ticking_interface(
        on_world_tick=lambda: [
            GameSpace.PlayerActionResponse(target=PLAYER, text=f"Raider {i} hits you.")
            for i in range(10)
        ]
    )
    stub_user(interface, sent)

    asyncio.run(interface.tick())
    assert len(sent) == 1
    assert sent[0].splitlines() == [f"Raider {i} hits you." for i in range(10)]


def test_an_oversized_batch_is_split_to_discords_limit():
    sent = []
    interface = ticking_interface(
        on_world_tick=lambda: [
            GameSpace.PlayerActionResponse(target=PLAYER, text="x" * 1500)
            for _ in range(2)
        ]
    )
    stub_user(interface, sent)

    asyncio.run(interface.tick())
    assert [len(chunk) for chunk in sent] == [2000, 1001]  # 1500 + "\n" + 1500


def test_a_closed_dm_doesnt_take_the_tick_down():
    sent = []
    interface = ticking_interface(on_world_tick=hit_by_an_npc)
    closed_dms = SimpleNamespace(status=403, reason="Forbidden")
    stub_user(interface, sent, raises=discord.HTTPException(closed_dms, "DMs closed"))  # type: ignore[arg-type]

    asyncio.run(interface.tick())  # the exception stays inside _dm
    assert sent == []


def test_the_digest_goes_to_each_server_that_picked_a_channel():
    adapter = SimpleNamespace(
        guild_settings={
            1: GuildSettings(digest_channel=10),
            2: GuildSettings(),  # didn't pick one
            3: GuildSettings(digest_channel=30),  # the bot may not post there
            4: GuildSettings(digest_channel=40),  # deleted
        }
    )
    interface = DiscordInterface(world_adapter=cast(WorldAdapter, adapter))
    sent = []

    async def send(channel_id, text):
        if channel_id == 30:
            raise discord.HTTPException(SimpleNamespace(status=403, reason="Forbidden"), "Missing Access")  # type: ignore[arg-type]
        sent.append((channel_id, text))

    channels = {c: SimpleNamespace(send=lambda text, c=c: send(c, text)) for c in (10, 30)}
    interface.bot.get_channel = channels.get  # type: ignore[method-assign]

    asyncio.run(interface.post_digest("A quiet day."))  # one server's trouble stays its own
    assert sent == [(10, "A quiet day.")]


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
    test_every_command_but_register_settings_and_help_requires_a_character()
    test_check_rejects_unregistered()
    test_check_rejects_unspawned()
    test_check_passes_for_spawned_character()
    test_space_check_rejects_character_outside_a_town()
    test_space_check_passes_inside_a_town()
    print("ok")


class DeadResponse:
    """An interaction Discord has already forgotten: every reply route 404s."""

    def __init__(self):
        self.attempts = 0

    def is_done(self):
        return False

    def _dead(self):
        self.attempts += 1
        raise discord.NotFound(
            cast(Any, SimpleNamespace(status=404, reason="Not Found")),
            {"code": 10062, "message": "Unknown interaction"},
        )

    async def defer(self):
        self._dead()

    async def send_message(self, *args, **kwargs):
        self._dead()


def test_expired_interaction_does_not_abort_the_command():
    """A dropped reply channel must cost the reply, not the world change: /move used to raise out of
    defer() before it could queue the order, so the character silently never moved."""
    response = DeadResponse()
    interaction = cast(
        discord.Interaction, SimpleNamespace(command="move", response=response)
    )

    asyncio.run(_defer(interaction))
    asyncio.run(_send(interaction, "you move north"))

    assert response.attempts == 2  # both were tried, neither was allowed to propagate


class Replies:
    """An interaction's reply routes, recording what the command said back."""

    def __init__(self):
        self.deferred = False
        self.sent = []

    def is_done(self):
        return self.deferred

    async def defer(self):
        self.deferred = True

    async def send_message(self, content, **kwargs):
        self.sent.append(content)

    async def send(self, content, **kwargs):  # the followup, once deferred
        self.sent.append(content)


def test_attack_with_a_melee_weapon_hits_the_raider_beside_you():
    """/attack always takes a direction, and every melee /attack used to be refused: 'You need a ranged
    weapon to attack at a distance.' A raider beside you was one you could see and never hit."""
    adapter = WorldAdapter(GameSpace.World("Arena", 40, 40, seed=0))
    world = adapter.world
    adapter.register_player(1, "Fighter")
    player = adapter.get_player(1)
    player.location = next(
        s
        for s in adapter.iter_spaces()
        if s.y > 0
        and not isinstance(s, GameSpace.Town)
        and world.is_space_valid(s)
        and world.is_space_valid(world.space_at(s.x, s.y - 1))
    )
    raider = Actors.Raider(world, 50, "Neighbour")
    world.add_actor(raider, world.space_at(player.location.x, player.location.y - 1))

    interface = loaded_cog(adapter)
    stub_user(interface, [])
    replies = Replies()
    interaction = SimpleNamespace(command="attack", user=SimpleNamespace(id=1), response=replies, followup=replies)

    async def scenario():
        swing = asyncio.create_task(
            command_named(interface, "attack").callback(
                interface, interaction, app_commands.Choice(name="north", value="n")  # type: ignore[arg-type]
            )
        )
        await asyncio.sleep(0)  # the command queues its order
        await interface.tick()
        await swing

    asyncio.run(scenario())
    assert raider.hit_points < raider.hit_points_max
    assert "to Neighbour" in replies.sent[0]


def weblogin(web_url):
    adapter = WorldAdapter(GameSpace.World("Linkland", 40, 40, seed=0))
    adapter.register_player(1, "Surfer")
    interface = DiscordInterface(world_adapter=adapter, web_url=web_url)
    asyncio.run(interface.bot.add_cog(interface))
    sent = []

    async def send_message(content, **kwargs):
        sent.append((content, kwargs))

    response = SimpleNamespace(is_done=lambda: False, send_message=send_message)
    interaction = SimpleNamespace(command="weblogin", user=SimpleNamespace(id=1), response=response)
    asyncio.run(command_named(interface, "weblogin").callback(interface, interaction))  # type: ignore[arg-type]
    return adapter, sent


def test_weblogin_privately_sends_a_link_that_logs_you_in():
    adapter, [(content, kwargs)] = weblogin("https://map.example/")
    assert kwargs["ephemeral"]
    link = content.splitlines()[-1]
    assert link.startswith("<https://map.example/login?t=") and link.endswith(">")  # <>: no preview fetch
    session = adapter.web_logins.redeem(link[len("<https://map.example/login?t=") : -1])
    assert session is not None and adapter.web_logins.member_id(session) == 1


def test_weblogin_says_so_when_there_is_no_web_map():
    _, [(content, _)] = weblogin(None)
    assert "isn't running" in content


def test_what_the_bot_dms_is_kept_for_the_website():
    adapter = WorldAdapter(GameSpace.World("Newsland", 40, 40, seed=0))
    adapter.register_player(1, "Reader")
    player = adapter.get_player(1)
    adapter.world.tick = lambda: [  # type: ignore[method-assign]
        GameSpace.PlayerActionResponse(target=player, text="A raider hits you.")
    ]
    interface = DiscordInterface(world_adapter=adapter)
    stub_user(interface, [])

    asyncio.run(interface.tick())
    assert [text for _, text in adapter.news(player)] == ["A raider hits you."]


def test_joining_a_server_says_where_to_start():
    interface = DiscordInterface(world_adapter=cast(WorldAdapter, SimpleNamespace()))
    sent = []

    async def send(text):
        sent.append(text)

    guild = SimpleNamespace(name="S", id=1, system_channel=SimpleNamespace(send=send))
    asyncio.run(interface.on_guild_join(cast(Any, guild)))
    assert "/register" in sent[0] and "/settings" in sent[0]
    guild.system_channel = None  # nowhere to say it
    asyncio.run(interface.on_guild_join(cast(Any, guild)))
    assert len(sent) == 1


def test_town_status_introduces_the_residents():
    character = Actors.PlayerCharacter(parent_world=None, name="Visitor")
    character.location = GameSpace.Town(0, 0, "Hub", population=40)
    interface = loaded_cog(StubAdapter(character))
    replies = Replies()
    interaction = SimpleNamespace(command="town status", user=SimpleNamespace(id=1), response=replies)
    asyncio.run(command_named(interface, "town status").callback(interface, interaction))  # type: ignore[arg-type]
    [text] = replies.sent
    assert text.startswith("You're in Hub, population 40.") and "the shopkeeper" in text and "the guard" in text


def test_help_lists_every_command_privately_starting_with_register():
    interface = loaded_cog()
    sent = []

    async def send_message(content, **kwargs):
        sent.append(kwargs)

    response = SimpleNamespace(is_done=lambda: False, send_message=send_message)
    interaction = SimpleNamespace(command="help", user=SimpleNamespace(id=1), response=response)
    asyncio.run(command_named(interface, "help").callback(interface, interaction))  # type: ignore[arg-type]
    [kwargs] = sent
    lines = kwargs["embed"].description.splitlines()
    assert kwargs["ephemeral"] and lines[0].startswith("`/register`")
    assert {line.split("`")[1][1:] for line in lines} >= EXPECTED


def test_equipping_a_box_of_rounds_says_no_instead_of_going_unanswered():
    character = Actors.PlayerCharacter(parent_world=None, name="Gunner")
    character.inventory.append(Weapons.Ammo9mm())
    interface = loaded_cog(StubAdapter(character))
    replies = Replies()
    interaction = SimpleNamespace(
        command="inventory equip", user=SimpleNamespace(id=1), response=replies
    )
    asyncio.run(command_named(interface, "inventory equip").callback(interface, interaction, 0))  # type: ignore[arg-type]
    assert replies.sent == ["9mm rounds isn't something you wear or hold."]
