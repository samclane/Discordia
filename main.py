import logging
import os
import pickle
import threading

import ConfigParser
from Discordia.GameLogic import GameSpace
from Discordia.Interface.DiscordInterface import DiscordInterface
from Discordia.Interface.Rendering.DesktopApp import MainWindow, update_display
from Discordia.Interface.WorldAdapter import WorldAdapter

LOG = logging.getLogger("Discordia")
logging.basicConfig(level=logging.INFO)


def main():
    if os.path.isfile(r'./world.p'):
        world: GameSpace.World = pickle.load(open(r'./world.p', 'rb'))
    else:
        world = GameSpace.World(ConfigParser.WORLD_NAME, ConfigParser.WORLD_WIDTH, ConfigParser.WORLD_HEIGHT)
    adapter = WorldAdapter(world)

    display = MainWindow(adapter)

    threading.Thread(target=update_display, args=(display, True)).start()
    discord_interface = DiscordInterface(adapter)
    # discord_interface.bot.loop.create_task(update_display(display))
    threading.Thread(target=discord_interface.bot.run, args=(ConfigParser.DISCORD_TOKEN,), daemon=True).start()
    # discord_interface.bot.run(ConfigParser.DISCORD_TOKEN)

    LOG.info("Discordia Server has successfully started. Press ESC to quit.")


if __name__ == '__main__':
    main()
