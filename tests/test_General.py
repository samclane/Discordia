import logging
import os
import random
import threading
import unittest
from pathlib import Path

import Discordia.ConfigParser as ConfigParser
from Discordia.GameLogic import GameSpace
from Discordia.Interface.DiscordInterface import DiscordInterface
from Discordia.Interface.WorldAdapter import WorldAdapter
from Discordia.Interface.Rendering.DesktopApp import MainWindow, update_display

LOG = logging.getLogger("Discordia")
logging.basicConfig(level=logging.INFO)


def clean_screenshots():
    folder = "../Discordia/PlayerViews"
    for file_ in os.listdir(folder):
        file_path = os.path.join(folder, file_)
        try:
            if os.path.isfile(file_path):
                os.unlink(file_path)
        except Exception as e:
            raise e


class TestGeneral(unittest.TestCase):
    NUM_USERS = 10

    def setUp(self) -> None:
        os.chdir(Path("../Discordia/"))

        self.world = GameSpace.World(ConfigParser.WORLD_NAME, ConfigParser.WORLD_WIDTH, ConfigParser.WORLD_HEIGHT)
        self.adapter = WorldAdapter(self.world)
        self.display = MainWindow(self.adapter)
        threading.Thread(target=update_display, args=(self.display,)).start()
        discord_interface = DiscordInterface(self.adapter)
        threading.Thread(target=discord_interface.bot.run, args=(ConfigParser.DISCORD_TOKEN,), daemon=True).start()

        # discord_interface.bot.loop.create_task(update_display(self.display))
        # discord_interface.bot.run(ConfigParser.DISCORD_TOKEN)

        LOG.info("Discordia Server has successfully started.")

        for idx in range(self.NUM_USERS):
            self.adapter.register_player(idx, player_name=f"User{idx}")

    def test_names(self):
        for idx in range(self.NUM_USERS):
            user = self.adapter.get_player(idx)
            self.assertEqual(user.name, f"User{idx}")

    def tearDown(self) -> None:
        clean_screenshots()