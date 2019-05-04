import logging
import os
import sys
import pickle
import threading
from typing import Dict

import arcade

from Discordia import ConfigParser
from Discordia.GameLogic import GameSpace
from Discordia.Interface.DiscordInterface import DiscordInterface
from Discordia.Interface.WorldAdapter import WorldAdapter
from Discordia.Interface.Rendering.DesktopApp import MainWindow

LOG = logging.getLogger("Discordia")
logging.basicConfig(level=logging.INFO)


def main():
    threads: Dict[str, threading.Thread] = {}
    if os.path.isfile(r'./world.p'):
        world: GameSpace.World = pickle.load(open(r'./world.p', 'rb'))
    else:
        world = GameSpace.World(ConfigParser.WORLD_NAME, ConfigParser.WORLD_WIDTH, ConfigParser.WORLD_HEIGHT)
    adapter = WorldAdapter(world)

    discord_interface = DiscordInterface(adapter)
    discord_thread = threading.Thread(target=lambda: discord_interface.bot.run(ConfigParser.DISCORD_TOKEN), daemon=True)
    threads["discord_thread"] = discord_thread
    discord_thread.start()

    display = MainWindow(adapter)
    sys.exit(arcade.run())


if __name__ == '__main__':
    main()
