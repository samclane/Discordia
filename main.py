import logging
import threading
import time
import argparse

import ConfigParser
from Discordia.GameLogic import GameSpace
from Discordia.Interface.Database import Database, DEFAULT_PATH
from Discordia.Interface.DiscordInterface import DiscordInterface
from Discordia.Interface.Rendering.DesktopApp import WindowRenderer, update_display
from Discordia.Interface.WorldAdapter import WorldAdapter

LOG = logging.getLogger("Discordia")
logging.basicConfig(level=logging.INFO)

AUTOSAVE_SECONDS = 60
TICK_SECONDS = 5


def every(seconds: float, action, name: str):
    # ponytail: a plain timer loop, so a crash loses at most AUTOSAVE_SECONDS of play, and ticks
    # drift by however long the action took. Both fine at these intervals.
    while True:
        time.sleep(seconds)
        try:
            action()
        except Exception:
            LOG.exception("%s failed", name)


def main():
    parser = argparse.ArgumentParser(description="Run an instance of a Discordia server",
                                     prog="Discordia")
    parser.add_argument('-W --show_window', dest='show_window', action='store_const', const=True, default=False,
                        help="Show a window containing a live view of the entire world. WARNING: CPU-intensive.")
    parser.add_argument('--database', default=DEFAULT_PATH, help="Path to the server's SQLite save file.")
    args = parser.parse_args()

    if not ConfigParser.DISCORD_TOKEN:
        raise SystemExit("No Discord token: set DISCORD_TOKEN or fill in Token under [Discord] in config.ini")

    database = Database(args.database)
    adapter = database.load()
    if adapter is None:
        LOG.info("No save found, generating a new world")
        adapter = WorldAdapter(GameSpace.World(ConfigParser.WORLD_NAME,
                                               ConfigParser.WORLD_WIDTH,
                                               ConfigParser.WORLD_HEIGHT))
        database.save(adapter)

    display = WindowRenderer(adapter)

    threading.Thread(target=update_display, args=(display, args.show_window), daemon=True).start()
    threading.Thread(
        target=every,
        args=(AUTOSAVE_SECONDS, lambda: database.save(adapter), "Autosave"),
        daemon=True,
    ).start()
    threading.Thread(
        target=every,
        args=(TICK_SECONDS, adapter.world.tick, "World tick"),
        daemon=True,
    ).start()
    discord_interface = DiscordInterface(adapter)
    # discord_interface.bot.loop.create_task(update_display(display))
    # threading.Thread(target=discord_interface.bot.run, args=(ConfigParser.DISCORD_TOKEN,), daemon=True).start()
    LOG.info("Discordia Server has successfully started. Press Ctrl+C to quit.")
    try:
        discord_interface.bot.run(ConfigParser.DISCORD_TOKEN)
    finally:
        database.save(adapter)
        database.close()
        LOG.info("World saved.")


if __name__ == '__main__':
    main()
