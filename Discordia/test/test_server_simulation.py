"""
Discord server simulator: a cast of members plays the bot across two servers through the real slash commands
(discord.py's own checks, argument transforms and error handlers, against a fake Discord), with the world ticking
in lockstep the way the bot runs it. Every message the bot sends is recorded, and the run is checked against the
rules a server admin would care about: spam, posts outside the allowed channels, leaked links, mass pings, and
interactions left hanging.

The test is a short run. For a longer one to dig through:

    python -m Discordia.test.test_server_simulation --ticks 500 --out server.jsonl

which prints a summary of every rule broken and writes every message the bot sent as JSON lines.
"""

import argparse
import asyncio
import json
import logging
import random
import tempfile
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Tuple

import discord
from discord import app_commands
from PIL import Image

from Discordia.GameLogic import Events, GameSpace
from Discordia.Interface import Alerts
from Discordia.Interface.DiscordInterface import DiscordInterface
from Discordia.Interface.WorldAdapter import DIRECTION_NAMES, GuildSettings, WorldAdapter

TICK_SECONDS = 5.0  # simulated seconds a tick, as main.py runs it
LIMIT = 2000  # characters Discord takes in one message
RATE = 5  # messages Discord takes per channel per 5 seconds (one tick) before it rate-limits the bot
CHATTY = 5  # messages one command may answer with before it's flooding the channel
DM_STREAK = 6  # ticks in a row a player may be DM'd (30 seconds) before it's spam
ACK_SECONDS = 3.0  # Discord's deadline to answer or defer an interaction
SOMETHING_WRONG = "Something went wrong on the server."
# Rules already on ROADMAP.md, so the test stays green until they're fixed. Delete one when its fix lands.
KNOWN: Tuple[str, ...] = ("dm spam",)


@dataclass
class Sent:
    """One message the bot sent."""

    tick: int
    where: str  # reply | followup | dm | channel
    content: str
    channel: Optional[int] = None  # None for a DM
    user: Optional[int] = None  # whose command or DM it was
    command: Optional[str] = None
    ephemeral: bool = False


@dataclass
class Problem:
    tick: int
    rule: str
    detail: str


def _http(status: int, text: str) -> discord.HTTPException:
    error = discord.Forbidden if status == 403 else discord.HTTPException
    return error(SimpleNamespace(status=status, reason=text), text)  # type: ignore[arg-type]


class Discord:
    """The fake Discord: records what the bot sends, refuses what the real one refuses, and flags the rest."""

    def __init__(self, interface: DiscordInterface):
        self.interface = interface
        self.tick = 0
        self.sent: List[Sent] = []
        self.problems: List[Problem] = []
        self.closed_dms: set = set()
        self.guilds: Dict[int, SimpleNamespace] = {}
        self.channels: Dict[int, SimpleNamespace] = {}  # channel id -> its guild id, name, parent

    def flag(self, rule: str, detail: str):
        self.problems.append(Problem(self.tick, rule, detail))

    def add_guild(self, guild_id: int, name: str, channels: List[str], system: str):
        guild = SimpleNamespace(id=guild_id, name=name, channels={})
        for n, channel_name in enumerate(channels):
            channel_id = guild_id * 100 + n
            channel = SimpleNamespace(id=channel_id, name=channel_name, guild=guild_id, parent_id=None)
            channel.send = self._channel_sender(channel)
            guild.channels[channel_name] = self.channels[channel_id] = channel
        guild.system_channel = guild.channels[system]
        self.guilds[guild_id] = guild
        return guild

    def thread(self, parent: SimpleNamespace) -> SimpleNamespace:
        """A thread hanging off `parent`: Discord reports it as its own channel with a parent_id."""
        thread = SimpleNamespace(id=parent.id + 50, name=f"{parent.name} thread", guild=parent.guild, parent_id=parent.id)
        thread.send = self._channel_sender(thread)
        self.channels[thread.id] = thread
        return thread

    def post(self, sent: Sent):
        """Everything the bot says comes through here."""
        if len(sent.content) > LIMIT:
            self.flag("too long", f"{len(sent.content)} characters in a {sent.where} to /{sent.command}")
            raise _http(400, "Must be 2000 or fewer in length.")
        if not sent.content.strip():
            self.flag("empty message", f"{sent.where} to /{sent.command}")
            raise _http(400, "Cannot send an empty message")
        public = not sent.ephemeral and sent.where != "dm"
        if public and "login?t=" in sent.content:
            self.flag("leaked login link", f"a one-time login link in public, from /{sent.command}")
        mentions = self.interface.bot.allowed_mentions
        if ("@everyone" in sent.content or "@here" in sent.content) and (mentions is None or mentions.everyone):
            self.flag("mass ping", f"{sent.where} pings everyone: {sent.content[:80]!r}")
        if SOMETHING_WRONG in sent.content:
            self.flag("unhandled error", f"/{sent.command} hit a bug (see the log)")
        if public and sent.channel is not None:
            self._check_channel(sent)
        self.sent.append(sent)

    def _check_channel(self, sent: Sent):
        channel = self.channels[sent.channel]
        settings = self.interface.world_adapter.guild_settings.get(channel.guild)
        guild = self.guilds[channel.guild]
        if sent.where == "channel":  # unprompted: only the welcome and the digest may do that
            allowed = {guild.system_channel.id} | ({settings.digest_channel} if settings else set())
            if sent.channel not in allowed:
                self.flag("unprompted post", f"in #{channel.name}: {sent.content[:60]!r}")
        elif settings and settings.channels and sent.command != "settings":
            if not {channel.id, channel.parent_id} & set(settings.channels):
                self.flag("outside allowed channels", f"/{sent.command} answered publicly in #{channel.name}")

    def _channel_sender(self, channel):
        async def send(content: str, **_):
            self.post(Sent(self.tick, "channel", content, channel=channel.id))

        return send

    def get_user(self, member_id: int):
        async def send(content: str, **_):
            if member_id in self.closed_dms:
                raise _http(403, "Cannot send messages to this user")
            self.post(Sent(self.tick, "dm", content, user=member_id))

        return SimpleNamespace(id=member_id, send=send)

    def get_channel(self, channel_id: int):
        return self.channels.get(channel_id)

    def get_guild(self, guild_id: int):
        return self.guilds.get(guild_id)


class Interaction:
    """Just enough of discord.Interaction for the cog, holding Discord's rules for answering one."""

    _ids = 0

    def __init__(self, discord_: Discord, member: "Member", channel: SimpleNamespace, command):
        Interaction._ids += 1
        self.id = Interaction._ids
        self.discord = discord_
        self.user = SimpleNamespace(id=member.id, display_name=member.name)
        self.guild_id = channel.guild
        self.channel_id = channel.id
        self.channel = channel
        self.command = command
        self.permissions = SimpleNamespace(manage_guild=member.admin)
        self.tick = discord_.tick
        self.acknowledged = False  # answered or deferred: what Discord wants within 3 seconds
        self.deferred = False
        self.messages = 0
        self.response = SimpleNamespace(is_done=lambda: self.acknowledged, send_message=self._respond, defer=self._defer)
        self.followup = SimpleNamespace(send=self._followup)

    def _sent(self, where: str, content: str, ephemeral: bool, files=()):
        for file in files:  # uploaded, as far as anyone can tell; the real client closes them after
            file.close()
        self.messages += 1
        self.discord.post(
            Sent(self.discord.tick, where, content, self.channel_id, self.user.id, self.command.qualified_name, ephemeral)
        )

    async def _respond(self, content: str, ephemeral: bool = False, files=(), **_):
        if self.acknowledged:
            raise discord.InteractionResponded(self)  # type: ignore[arg-type]
        self._sent("reply", content, ephemeral, files)
        self.acknowledged = True

    async def _defer(self, **_):
        if self.acknowledged:
            raise discord.InteractionResponded(self)  # type: ignore[arg-type]
        self.acknowledged = self.deferred = True

    async def _followup(self, content: str, ephemeral: bool = False, files=(), **_):
        if not self.acknowledged:
            raise _http(404, "Unknown Webhook")  # a followup needs a response to follow
        self._sent("followup", content, ephemeral, files)


# What a member might type: (command, weight, arguments). Arguments are raw option values, as Discord sends them.
PLAY: List[Tuple[str, float, Callable[[], Dict[str, Any]]]] = [
    ("move", 8, lambda: {"direction": random.choice(list(DIRECTION_NAMES))}),
    ("attack", 1, lambda: {"direction": random.choice(list(DIRECTION_NAMES))}),
    ("choose", 1, lambda: {"choice": random.choice(Events.EncounterEvent.CHOICES)}),
    ("look", 1, lambda: {}),
    ("equipment", 1, lambda: {}),
    ("inventory list", 1, lambda: {}),
    ("inventory equip", 0.5, lambda: {"index": random.randrange(4)}),
    ("inventory pouch", 0.3, lambda: {"index": random.randrange(3)}),
    ("town status", 0.5, lambda: {}),
    ("town inn", 0.5, lambda: {}),
    ("town store list", 0.5, lambda: {}),
    ("town store buy", 0.5, lambda: {"index": random.randrange(12)}),
    ("town store sell", 0.3, lambda: {"index": random.randrange(3)}),
    ("trade list", 0.3, lambda: {}),
    ("stash list", 0.3, lambda: {}),
    ("stash put", 0.3, lambda: {"money": random.randrange(100)}),
    ("hideout build", 0.2, lambda: {}),
    ("weblogin", 0.2, lambda: {}),
]


@dataclass
class Member:
    """Someone in a server, and their habits."""

    id: int
    name: str
    home: SimpleNamespace  # where they normally type
    activity: float = 0.5  # chance of typing a command in a tick
    burst: int = 1  # commands at once, when they do
    elsewhere: Optional[SimpleNamespace] = None  # a channel they sometimes type in by mistake
    admin: bool = False
    registers: bool = True
    closed_dms: bool = False
    registered: bool = field(default=False, init=False)

    def wants(self) -> List[Tuple[SimpleNamespace, str, Dict[str, Any]]]:
        """This tick's commands: (channel, command, arguments)."""
        channel = self.elsewhere if self.elsewhere and random.random() < 0.4 else self.home
        if self.registers and not self.registered:
            self.registered = True
            return [(channel, "register", {"name": self.name})]
        if random.random() > self.activity:
            return []
        if self.admin and random.random() < 0.1:
            return [(channel, "settings", {})]
        name, _, args = random.choices(PLAY, weights=[w for _, w, _ in PLAY])[0]
        return [(channel, name, args()) for _ in range(self.burst)]


def cast_of_members(discord_: Discord) -> List[Member]:
    locked = discord_.add_guild(1, "Locked Server", ["general", "play", "news", "offtopic"], system="general")
    open_ = discord_.add_guild(2, "Open Server", ["general", "memes"], system="general")
    play, thread = locked.channels["play"], discord_.thread(locked.channels["play"])
    return [
        Member(11, "Alice", play),
        Member(12, "Bob", thread, closed_dms=True),
        Member(13, "Carol", play, admin=True),
        Member(14, "Dave", play, elsewhere=locked.channels["offtopic"]),  # keeps forgetting which channel
        Member(15, "Eve", play, activity=0.9, burst=8),  # spams /move
        Member(16, "@everyone", play),  # what a troll would call themselves
        Member(17, "Newbie", locked.channels["general"], registers=False, activity=0.3),
        Member(21, "Frank", open_.channels["general"]),
        Member(22, "Grace", open_.channels["memes"], activity=0.8),
    ]


async def invoke(discord_: Discord, interaction: Interaction, args: Dict[str, Any]):
    """What discord.py's CommandTree does with an interaction, minus parsing Discord's JSON."""
    command = interaction.command
    try:
        await command._invoke_with_namespace(interaction, SimpleNamespace(**args))
    except app_commands.AppCommandError as error:
        await command._invoke_error_handlers(interaction, error)
    except Exception as error:  # the tree lets these escape: the player sees "The application did not respond"
        discord_.flag("escaped exception", f"/{command.qualified_name}: {type(error).__name__}: {error}")


async def _simulate(ticks: int, seed: int, size: int) -> Discord:
    world = GameSpace.World("Server Sim", size, size, seed=seed)  # seeds `random` too, so a run replays
    adapter = WorldAdapter(world)
    view = Path(tempfile.mkdtemp()) / "view.png"
    Image.new("RGB", (8, 8)).save(view)
    adapter.add_renderer(SimpleNamespace(get_player_view=lambda character: str(view)))  # /look attaches a picture
    interface = DiscordInterface(adapter, web_url="https://discordia.example")
    await interface.bot.add_cog(interface)
    discord_ = Discord(interface)
    bot: Any = interface.bot  # the fake stands in for Discord's caches and API behind the bot
    bot.get_user, bot.get_channel, bot.get_guild = discord_.get_user, discord_.get_channel, discord_.get_guild

    members = cast_of_members(discord_)
    locked = discord_.guilds[1]
    adapter.guild_settings[1] = GuildSettings(
        channels=[locked.channels["play"].id], digest_channel=locked.channels["news"].id
    )
    discord_.closed_dms = {m.id for m in members if m.closed_dms}
    commands = {c.qualified_name: c for c in interface.bot.tree.walk_commands() if isinstance(c, app_commands.Command)}
    for guild in discord_.guilds.values():
        await interface.on_guild_join(guild)  # type: ignore[arg-type]

    for tick in range(ticks):
        discord_.tick = tick
        running = []
        for member in members:
            for channel, name, args in member.wants():
                interaction = Interaction(discord_, member, channel, commands[name])
                running.append((interaction, asyncio.create_task(invoke(discord_, interaction, args))))
        for _ in range(10):  # let every command run up to where it waits for the tick
            await asyncio.sleep(0)
        # The tick is up to TICK_SECONDS away: anything not answered or deferred by now would time out.
        for interaction, _ in running:
            if not interaction.acknowledged:
                discord_.flag("too slow", f"/{interaction.command.qualified_name} not answered within {ACK_SECONDS}s")
        await interface.tick()
        await asyncio.gather(*(task for _, task in running))
        for interaction, _ in running:
            name = interaction.command.qualified_name
            if not interaction.acknowledged:
                discord_.flag("no answer", f"/{name} never answered: 'The application did not respond'")
            elif interaction.deferred and not interaction.messages:
                discord_.flag("stuck thinking", f"/{name} deferred and never followed up")
            if interaction.messages > CHATTY:
                discord_.flag("chatty", f"/{name} answered with {interaction.messages} messages")
        if tick == ticks // 2:  # midnight, as far as the digest knows
            await interface.post_digest(Alerts.digest(world) or "Nothing happened today.")
    _check_rates(discord_)
    return discord_


def _check_rates(discord_: Discord):
    """Rules over the whole run: Discord's per-channel rate limit, and DMs that never let up."""
    per_tick = Counter((s.tick, s.channel if s.where == "channel" else f"dm {s.user}") for s in discord_.sent if s.where in ("dm", "channel"))
    for (tick, where), count in sorted(per_tick.items(), key=lambda kv: str(kv[0])):
        if count > RATE:
            discord_.problems.append(Problem(tick, "rate limited", f"{count} messages to {where} in {TICK_SECONDS}s"))
    dm_ticks = defaultdict(set)
    for s in discord_.sent:
        if s.where == "dm":
            dm_ticks[s.user].add(s.tick)
    for user, ticks in dm_ticks.items():
        streak = 0
        for tick in range(min(ticks), max(ticks) + 2):
            streak = streak + 1 if tick in ticks else 0
            if streak == DM_STREAK + 1:
                discord_.problems.append(Problem(tick, "dm spam", f"user {user} DM'd every tick for {streak}+ ticks"))


def simulate(ticks: int = 120, seed: int = 0, size: int = 128) -> Discord:
    return asyncio.run(_simulate(ticks, seed, size))


def summary(discord_: Discord) -> str:
    by_where = Counter(s.where for s in discord_.sent)
    lines = [f"{len(discord_.sent)} messages sent over {discord_.tick + 1} ticks: {dict(by_where)}"]
    lines.append(f"  busiest commands: {Counter(s.command for s in discord_.sent if s.command).most_common(5)}")
    rules = Counter(p.rule for p in discord_.problems)
    lines.append(f"  rules broken: {dict(rules.most_common()) or 'none'}")
    seen = set()
    for p in discord_.problems:
        if p.rule not in seen:  # one example of each
            seen.add(p.rule)
            lines.append(f"    {p.rule} (tick {p.tick}): {p.detail}")
    return "\n".join(lines)


def test_the_bot_keeps_to_server_rules():
    discord_ = simulate(ticks=60)
    bad = [p for p in discord_.problems if not p.rule.startswith(KNOWN)]
    assert not bad, f"{len(bad)} problems\n{summary(discord_)}"
    assert any(s.where == "dm" for s in discord_.sent), "nobody was ever DM'd: the run is too tame to show anything"
    assert any(s.where == "channel" for s in discord_.sent), "no welcome or digest went out"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ticks", type=int, default=500)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--size", type=int, default=128)
    parser.add_argument("--out", help="write every message sent, then every problem, here as JSON lines")
    args = parser.parse_args()
    logging.getLogger("Discordia").setLevel(logging.ERROR)  # every refused command logs a warning otherwise
    result = simulate(args.ticks, args.seed, args.size)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.writelines(json.dumps({"sent": asdict(s)}) + "\n" for s in result.sent)
            f.writelines(json.dumps({"problem": asdict(p)}) + "\n" for p in result.problems)
    print(summary(result))
