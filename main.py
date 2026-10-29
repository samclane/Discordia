import asyncio
import datetime
import logging
import threading
import argparse
from typing import Callable, cast

import ConfigParser
from Discordia import VERSION
from Discordia.GameLogic import GameSpace
from Discordia.Interface import Alerts
from Discordia.Interface.Database import Database, DEFAULT_PATH
from Discordia.Interface.DiscordInterface import DiscordInterface
from Discordia.Interface.Rendering.DesktopApp import WindowRenderer
from Discordia.Interface.Rendering.WebApp import serve
from Discordia.Interface.WorldAdapter import WorldAdapter

LOG = logging.getLogger("Discordia")
logging.basicConfig(level=logging.INFO)

AUTOSAVE_SECONDS = 60
TICK_SECONDS = 5


def main():
    parser = argparse.ArgumentParser(description="Run an instance of a Discordia server",
                                     prog="Discordia")
    parser.add_argument('-W', '--web-port', dest='web_port', type=int, default=None, metavar='PORT',
                        help="Serve a live view of the entire world at http://localhost:PORT")
    parser.add_argument('--database', default=DEFAULT_PATH, help="Path to the server's SQLite save file.")
    args = parser.parse_args()

    if not ConfigParser.DISCORD_TOKEN:
        raise SystemExit("No Discord token: set DISCORD_TOKEN or fill in Token under [Discord] in config.ini")
    alerts = Alerts.install(ConfigParser.ALERT_WEBHOOK_URL) if ConfigParser.ALERT_WEBHOOK_URL else None

    database = Database(args.database)
    adapter = database.load(TICK_SECONDS)
    if adapter is None:
        LOG.info("No save found, generating a new world")
        adapter = WorldAdapter(GameSpace.World(ConfigParser.WORLD_NAME,
                                               ConfigParser.WORLD_WIDTH,
                                               ConfigParser.WORLD_HEIGHT))
        database.save(adapter)

    display = WindowRenderer(adapter)

    web_url = None
    if args.web_port:
        web_url = ConfigParser.WEB_PUBLIC_URL or f"http://localhost:{args.web_port}"
        threading.Thread(target=serve, args=(display, args.web_port), daemon=True).start()
    # The tick and the autosave run on the bot's event loop, in lockstep with the commands: no locking
    # needed, and a crash loses at most AUTOSAVE_SECONDS of play.
    jobs: list[tuple[float | datetime.time, Callable[[], None], str]] = [
        (AUTOSAVE_SECONDS, lambda: database.save(adapter), "Autosave")
    ]
    webhook = ConfigParser.ALERT_WEBHOOK_URL

    async def send_digest():
        text = Alerts.digest(adapter.world)
        if text:
            await discord_interface.post_digest(text)  # to each server that picked a channel; best effort
            if webhook:  # posted off the loop, so a slow Discord can't stall a tick
                await asyncio.to_thread(Alerts.post, webhook, text)

    # ponytail: Stats aren't saved, so the day after a deploy only counts from the restart. Servers' channels
    # lose that part; the webhook gets it from the shutdown digest below. Save Stats if the undercount matters.
    jobs.append((Alerts.DIGEST_TIME, cast(Callable[[], None], send_digest), "Daily digest"))
    discord_interface = DiscordInterface(adapter, jobs=jobs, tick_seconds=TICK_SECONDS, web_url=web_url)
    LOG.info("Discordia %s has successfully started. Press Ctrl+C to quit.", VERSION)
    try:
        discord_interface.bot.run(ConfigParser.DISCORD_TOKEN)
    except Exception:
        LOG.exception("Discordia crashed")  # through logging, so the crash that takes the bot down is alerted
        raise
    finally:
        database.save(adapter)
        database.close()
        LOG.info("World saved.")
        if webhook:  # only: the bot is gone by now, and servers would get a partial day on every deploy
            try:
                text = Alerts.digest(adapter.world)
                if text:
                    Alerts.post(webhook, text)
            except Exception:
                LOG.exception("Shutdown digest failed")
        if alerts:
            alerts.stop()  # flush anything still queued before the process goes


if __name__ == '__main__':
    main()
