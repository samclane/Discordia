import json
import logging
from logging.handlers import QueueHandler

import pytest

from Discordia.Interface import Alerts


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
