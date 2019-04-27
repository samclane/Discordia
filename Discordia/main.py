import logging
import os
import pickle
import threading
from typing import Dict

from Discordia import ConfigParser
from Discordia.GameLogic import GameSpace
from Discordia.Interface.DiscordInterface import DiscordInterface
from Discordia.Interface.WorldAdapter import WorldAdapter

LOG = logging.getLogger("Discordia")
logging.basicConfig(level=logging.INFO)


def main():
    threads: Dict[str, threading.Thread] = {}
    if os.path.isfile(r'./world.p'):
        world: GameSpace.World = pickle.load(open(r'./world.p', 'rb'))
    else:
        world = GameSpace.World(ConfigParser.WORLD_NAME, ConfigParser.WORLD_WIDTH, ConfigParser.WORLD_HEIGHT)
        # world.add_town(GameSpace.Town(0, 0, "TODO_NAME"), True)
    discord_interface = DiscordInterface(WorldAdapter(world))
    discord_thread = threading.Thread(target=lambda: discord_interface.bot.run(ConfigParser.DISCORD_TOKEN))
    threads["discord_thread"] = discord_thread
    discord_thread.start()


if __name__ == '__main__':
    main()
