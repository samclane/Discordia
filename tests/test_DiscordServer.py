import logging
import unittest
import threading

import Discordia.DiscordInterface.Interface as Interface
import Discordia.ConfigParser as ConfigParser

LOG = logging.getLogger("Discordia")
logging.basicConfig(level=logging.INFO)


class TestDiscordServer(unittest.TestCase):

    def test_connect_disconnect(self):
        # Start bot
        interface = Interface.DiscordInterface()
        run_thread = threading.Thread(target=lambda: interface.bot.run(ConfigParser.DISCORD_TOKEN))
        run_thread.start()

        # Wait for 1 second then exit
        run_thread.join(1)
        interface.bot.loop.create_task(interface.bot.close())
