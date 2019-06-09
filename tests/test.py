import logging
import os
import random
import threading
import unittest
from pathlib import Path

from PIL import Image

import Discordia.ConfigParser as ConfigParser
from Discordia.GameLogic import GameSpace
from Discordia.Interface.DiscordInterface import DiscordInterface
from Discordia.Interface.WorldAdapter import WorldAdapter
from Discordia.Interface.Rendering.DesktopApp import MainWindow, update_display

os.chdir(Path("../Discordia/"))

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
    NUM_STEPS = 100_000

    @classmethod
    def setUpClass(cls) -> None:
        assert cls.NUM_USERS > 0

        cls.world = GameSpace.World(ConfigParser.WORLD_NAME, ConfigParser.WORLD_WIDTH, ConfigParser.WORLD_HEIGHT)
        cls.adapter = WorldAdapter(cls.world)
        cls.display = MainWindow(cls.adapter)
        threading.Thread(target=update_display, args=(cls.display,), daemon=True).start()
        discord_interface = DiscordInterface(cls.adapter)
        threading.Thread(target=discord_interface.bot.run, args=(ConfigParser.DISCORD_TOKEN,), daemon=True).start()

        # discord_interface.bot.loop.create_task(update_display(cls.display))
        # discord_interface.bot.run(ConfigParser.DISCORD_TOKEN)

        LOG.info("Discordia Server has successfully started.")

        for idx in range(cls.NUM_USERS):
            cls.adapter.register_player(idx, player_name=f"User{idx}")

        cls.display.on_draw()

    def test_screenshot(self):
        for idx in range(self.NUM_USERS):
            player = self.adapter.get_player(idx)
            self.adapter.get_player_screenshot(player)
            img: Image.Image = Image.open(Path(f"./PlayerViews/User{idx}_screenshot.png"))
            self.assertFalse(all(p == (0, 0, 0, 255) for p in img.getdata()), "Black screenshot taken")
            self.assertFalse(all(p == (0, 0, 0, 0) for p in img.getdata()), "Transparent screenshot taken")
            self.assertGreater(img.height, 1)
            self.assertGreater(img.width, 1)

    def test_move_randomly(self):
        failcount = 0
        for step in range(self.NUM_STEPS):
            for idx in range(self.NUM_USERS):
                direction = random.choice(list(GameSpace.DIRECTION_VECTORS.values()))
                player = self.adapter.get_player(idx)
                result = player.attempt_move(direction)
                if len(result) == 1 and result[0].failed:
                    failcount += 1
                if result[0].damage:
                    LOG.info(result)

        self.assertLess(failcount, self.NUM_USERS * self.NUM_STEPS, "Failed every movement attempt.")
        LOG.info(f"Failcount: {failcount}")

    def tearDown(self) -> None:
        print("Miss Count: ", self.display._sprite_cache.miss_count)
        self.display.on_draw()
        self.display.get_world_view()
        clean_screenshots()
