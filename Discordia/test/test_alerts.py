import json
import logging
from logging.handlers import QueueHandler

import pytest

from Discordia.GameLogic import GameSpace
from Discordia.Interface import Alerts
from Discordia.Interface.WorldAdapter import WorldAdapter


@pytest.fixture
def alerts(monkeypatch):
    """Alerts installed against a fake webhook. Stop the listener before reading the posts."""
    posts = []
    monkeypatch.setattr(
        Alerts.urllib.request,
        "urlopen",
        lambda request, timeout: posts.append(json.loads(request.data)["content"])
        or open(__file__),  # anything with .close()
    )
    listener = Alerts.install("https://discord.invalid/webhook")
    yield posts, listener
    listener.stop()
    root = logging.getLogger()
    root.handlers = [h for h in root.handlers if not isinstance(h, QueueHandler)]


def test_errors_reach_the_webhook_once_and_noise_does_not(alerts):
    posts, listener = alerts
    log = logging.getLogger("Discordia.test")
    log.info("Player Tester has died")  # below WARNING
    logging.getLogger("discord.client").warning("PyNaCl is not installed")
    for _ in range(3):  # the same failure every tick
        log.error("World tick failed")
    logging.getLogger("discord.app_commands").error("Ignoring exception in /move")
    listener.stop()

    assert len(posts) == 2
    assert "World tick failed" in posts[0]
    assert "Ignoring exception" in posts[1]


def test_a_huge_traceback_still_fits_in_one_message(alerts):
    posts, listener = alerts
    logging.getLogger("Discordia.test").error(
        "boom\n" + "x" * 10_000 + "\nValueError: the end"
    )
    listener.stop()

    [post] = posts
    assert len(post) <= Alerts.DISCORD_LIMIT
    assert "boom" in post and "ValueError: the end" in post


def test_a_quiet_day_sends_no_digest():
    world = GameSpace.World("Quiet", 8, 8, seed=1)
    assert Alerts.digest(world) is None


def test_the_digest_sums_up_the_day_and_starts_over():
    world = GameSpace.World("Busy", 8, 8, seed=1)
    adapter = WorldAdapter(world)
    adapter.register_player(1, "Tester")
    adapter.get_player(1).currency = 1240
    world.stats.active_players.add(adapter.get_player(1))
    world.stats.kills = 31
    world.stats.deaths_by_level.update({2: 5, 1: 2})

    text = Alerts.digest(world)
    assert "1 players active · 31 kills · 7 deaths" in text
    assert "Deaths by danger level: L1 2 · L2 5" in text
    assert "Tester L1 $1,240" in text
    assert Alerts.digest(world) is None  # counted once
