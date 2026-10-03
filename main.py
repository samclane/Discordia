import asyncio
import logging
import threading
import argparse
from typing import Callable, cast

import ConfigParser
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
    adapter = database.load()
    if adapter is None:
        LOG.info("No save found, generating a new world")
        adapter = WorldAdapter(GameSpace.World(ConfigParser.WORLD_NAME,
                                               ConfigParser.WORLD_WIDTH,
                                               ConfigParser.WORLD_HEIGHT))
        database.save(adapter)

    display = WindowRenderer(adapter)

    if args.web_port:
        threading.Thread(target=serve, args=(display, args.web_port), daemon=True).start()
    # The tick and the autosave run on the bot's event loop, in lockstep with the commands: no locking
    # needed, and a crash loses at most AUTOSAVE_SECONDS of play.
    jobs: list[tuple[float, Callable[[], None], str]] = [
        (AUTOSAVE_SECONDS, lambda: database.save(adapter), "Autosave")
    ]
    webhook = ConfigParser.ALERT_WEBHOOK_URL
    if webhook:
        async def send_digest():
            # Summed on the loop, beside the game; posted off it, so a slow Discord can't stall a tick.
            text = Alerts.digest(adapter.world)
            if text:
                await asyncio.to_thread(Alerts.post, webhook, text)

        # ponytail: the day restarts with the process. The shutdown digest below keeps a deploy from
        # throwing a partial day away; a crash still does.
        jobs.append((Alerts.DIGEST_SECONDS, cast(Callable[[], None], send_digest), "Daily digest"))
    discord_interface = DiscordInterface(adapter, jobs=jobs, tick_seconds=TICK_SECONDS)
    LOG.info("Discordia Server has successfully started. Press Ctrl+C to quit.")
    try:
        discord_interface.bot.run(ConfigParser.DISCORD_TOKEN)
    except Exception:
        LOG.exception("Discordia crashed")  # through logging, so the crash that takes the bot down is alerted
        raise
    finally:
        database.save(adapter)
        database.close()
        LOG.info("World saved.")
        if webhook:
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
