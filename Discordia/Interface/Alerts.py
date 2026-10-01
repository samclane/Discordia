"""Warnings and errors, posted to a Discord channel through a webhook so a crash pings someone."""

import json
import logging
import time
import urllib.request
from logging.handlers import QueueHandler, QueueListener
from queue import SimpleQueue
from typing import Dict

# An error raised every tick would otherwise ping every 5 seconds; the same text pings once per this long.
REPEAT_SECONDS = 600
DISCORD_LIMIT = 2000  # characters per webhook message


class WebhookHandler(logging.Handler):
    """Posts each record it is given. Runs on the QueueListener's thread, never the bot's event loop."""

    def __init__(self, url: str):
        super().__init__()
        self.url = url
        # ponytail: grows by one entry per distinct alert text, fine at warning volume. Prune if it isn't.
        self._last_sent: Dict[str, float] = {}

    def emit(self, record: logging.LogRecord):
        # QueueHandler already formatted it, traceback included.
        text = record.getMessage()
        now = time.monotonic()
        if now - self._last_sent.get(text, -REPEAT_SECONDS) < REPEAT_SECONDS:
            return
        self._last_sent[text] = now
        room = DISCORD_LIMIT - 20  # the code fence and the elision marker
        # Keep what failed and where it ended up; the middle of a traceback can go.
        if len(text) > room:
            text = text[:300] + "\n...\n" + text[-(room - 305) :]
        request = urllib.request.Request(
            self.url,
            data=json.dumps({"content": f"```\n{text}\n```"}).encode(),
            # Discord turns away urllib's default User-Agent.
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Discordia (https://github.com/samclane/Discordia)",
            },
        )
        try:
            urllib.request.urlopen(request, timeout=10).close()
        except Exception:
            # To stderr, i.e. journald; never back through logging.
            self.handleError(record)


def install(url: str) -> QueueListener:
    """Send WARNING and up from every logger to `url`. Stop the returned listener to flush on shutdown."""
    queue: SimpleQueue = SimpleQueue()
    handler = QueueHandler(queue)
    handler.setLevel(logging.WARNING)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    # discord.py warns about voice support and intents on every start; only its errors are news.
    handler.addFilter(
        lambda r: r.levelno >= logging.ERROR or not r.name.startswith("discord.")
    )
    logging.getLogger().addHandler(handler)
    listener = QueueListener(queue, WebhookHandler(url))
    listener.start()
    return listener
