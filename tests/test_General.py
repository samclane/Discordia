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
    NUM_STEPS = 100000

    def setUp(self) -> None:
        assert self.NUM_USERS != 0

        self.world = GameSpace.World(ConfigParser.WORLD_NAME, ConfigParser.WORLD_WIDTH, ConfigParser.WORLD_HEIGHT)
        self.adapter = WorldAdapter(self.world)
        self.display = MainWindow(self.adapter)
        threading.Thread(target=update_display, args=(self.display,), daemon=True).start()
        discord_interface = DiscordInterface(self.adapter)
        threading.Thread(target=discord_interface.bot.run, args=(ConfigParser.DISCORD_TOKEN,), daemon=True).start()

        # discord_interface.bot.loop.create_task(update_display(self.display))
        # discord_interface.bot.run(ConfigParser.DISCORD_TOKEN)

        LOG.info("Discordia Server has successfully started.")

        for idx in range(self.NUM_USERS):
            self.adapter.register_player(idx, player_name=f"User{idx}")

    def test_names(self):
        for idx in range(self.NUM_USERS):
            player = self.adapter.get_player(idx)
            self.assertEqual(player.name, f"User{idx}")
            self.assertEqual(player.location, self.world.starting_town)

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
                if len(result) == 1 and not result[0].is_successful:
                    failcount += 1
                # elif len(result[0].text):
                #     LOG.info(result)

        self.assertLess(failcount, self.NUM_USERS * self.NUM_STEPS, "Failed every single movement attempt.")
        LOG.info(f"Failcount: {failcount}")

    def tearDown(self) -> None:
        clean_screenshots()


class TestStress(unittest.TestCase):
    NUM_STEPS = 100000
    NUM_USERS = 100
    NUM_WORLDS = 3

    def setUp(self) -> None:
        assert self.NUM_USERS > 0
        assert self.NUM_WORLDS > 0
        self.worlds = []
        self.adapters = []
        self.displays = []
        self.threads = {}
        for idx in range(self.NUM_WORLDS):
            world = GameSpace.World(ConfigParser.WORLD_NAME, ConfigParser.WORLD_WIDTH, ConfigParser.WORLD_HEIGHT)
            adapter = WorldAdapter(world)
            display = MainWindow(adapter)

            self.threads[idx] = threading.Thread(target=update_display, args=(display,), daemon=True)
            self.threads[idx].start()

            for pid in range(self.NUM_USERS):
                adapter.register_player(pid, player_name=f"User{pid}")

            self.worlds.append(world)
            self.adapters.append(adapter)
            self.displays.append(display)

    def test_screenshot(self):
        for adapter in self.adapters:
            for idx in range(self.NUM_USERS):
                player = adapter.get_player(idx)
                adapter.get_player_screenshot(player)
                img: Image.Image = Image.open(Path(f"./PlayerViews/User{idx}_screenshot.png"))
                self.assertFalse(all(p == (0, 0, 0, 255) for p in img.getdata()), "Black screenshot taken")
                self.assertFalse(all(p == (0, 0, 0, 0) for p in img.getdata()), "Transparent screenshot taken")
                self.assertGreater(img.height, 1)
                self.assertGreater(img.width, 1)

    def test_move_randomly(self):
        for adapter in self.adapters:
            failcount = 0
            for step in range(self.NUM_STEPS):
                for idx in range(self.NUM_USERS):
                    direction = random.choice(list(GameSpace.DIRECTION_VECTORS.values()))
                    player = adapter.get_player(idx)
                    result = player.attempt_move(direction)
                    if len(result) == 1:
                        if not result[0].is_successful:
                            failcount += 1
            self.assertLess(failcount, self.NUM_USERS * self.NUM_STEPS, "Failed every single movement attempt.")
            LOG.info(f"Failcount: {failcount}")

    def tearDown(self) -> None:
        clean_screenshots()