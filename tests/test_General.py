import logging
import unittest
import threading

from Discordia.GameLogic import GameSpace
from Discordia.Interface.DiscordInterface import DiscordInterface
from Discordia.Interface.WorldAdapter import WorldAdapter
import Discordia.ConfigParser as ConfigParser

LOG = logging.getLogger("Discordia")
logging.basicConfig(level=logging.INFO)


class TestGeneral(unittest.TestCase):

    def test_connect_disconnect(self):
        # Start bot
        interface = DiscordInterface(WorldAdapter(gameworld=None))  # Don't construct any gameworld for now.
        run_thread = threading.Thread(target=lambda: interface.bot.run(ConfigParser.DISCORD_TOKEN))
        run_thread.start()

        # Wait for 1 second then exit
        run_thread.join(1)
        interface.bot.loop.create_task(interface.bot.close())

    def test_world_creation(self):
        world = GameSpace.World(ConfigParser.WORLD_NAME, ConfigParser.WORLD_WIDTH, ConfigParser.WORLD_HEIGHT)
        discord_interface = DiscordInterface(WorldAdapter(world))
        discord_thread = threading.Thread(target=lambda: discord_interface.bot.run(ConfigParser.DISCORD_TOKEN))
        discord_thread.start()

        # Wait for 1 second then exit
        discord_thread.join(1)
        discord_interface.bot.loop.create_task(discord_interface.bot.close())
