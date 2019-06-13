import logging
import os
import random
import threading
import unittest
from pathlib import Path

from PIL import Image

import Discordia.ConfigParser as ConfigParser
from Discordia.GameLogic import GameSpace
from Discordia.GameLogic.Actors import PlayerCharacter
from Discordia.Interface.DiscordInterface import DiscordInterface
from Discordia.Interface.Rendering.DesktopApp import MainWindow, update_display
from Discordia.Interface.WorldAdapter import WorldAdapter

os.chdir(Path("../Discordia/"))

LOG = logging.getLogger("Discordia")
logging.basicConfig(level=logging.INFO)


def clean_screenshots():
    """ Delete all files in the screenshot folder """
    folder = "../Discordia/PlayerViews"
    for file_ in os.listdir(folder):
        file_path = os.path.join(folder, file_)
        try:
            if os.path.isfile(file_path):
                os.unlink(file_path)
        except Exception as e:
            raise e


class TestGeneral(unittest.TestCase):
    WORLD_WIDTH = 100
    WORLD_HEIGHT = 100
    NUM_USERS = 25
    NUM_STEPS = 250

    @classmethod
    def setUpClass(cls) -> None:
        assert cls.NUM_USERS > 0

        clean_screenshots()

        # cls.world = GameSpace.World(ConfigParser.WORLD_NAME, ConfigParser.WORLD_WIDTH, ConfigParser.WORLD_HEIGHT)
        cls.world = GameSpace.World(ConfigParser.WORLD_NAME, cls.WORLD_WIDTH, cls.WORLD_HEIGHT)
        cls.adapter = WorldAdapter(cls.world)
        cls.display = MainWindow(cls.adapter)
        threading.Thread(target=update_display, args=(cls.display,), daemon=True).start()
        discord_interface = DiscordInterface(cls.adapter)
        threading.Thread(target=discord_interface.bot.run, args=(ConfigParser.DISCORD_TOKEN,), daemon=True).start()

        # discord_interface.bot.loop.create_task(update_display(cls.display))
        # discord_interface.bot.run(ConfigParser.DISCORD_TOKEN)

        LOG.info("Discordia server started")

        for idx in range(cls.NUM_USERS):
            cls.adapter.register_player(idx, player_name=f"User{idx}")

        cls.display.on_draw()

    def _move_randomly(self):
        """
        All users move one step in a random direction, if they can
        """
        for idx in range(self.NUM_USERS):
            direction = random.choice(list(GameSpace.DIRECTION_VECTORS.values()))
            player = self.adapter.get_player(idx)
            yield player.attempt_move(direction)

    def test_1_move_randomly(self):
        """
        Have actors move randomly about the map, triggering Events. Test `fail_count` to make sure they can move at least some of the time.
        """
        fail_count = 0
        for step in range(self.NUM_STEPS):
            for result in self._move_randomly():
                if len(result) == 1 and result[0].failed:
                    fail_count += 1

        self.assertLess(fail_count, self.NUM_USERS * self.NUM_STEPS, "Failed every movement attempt.")
        LOG.info(f"Successes: {(self.NUM_USERS * self.NUM_STEPS) - fail_count} - Failcount: {fail_count}")

    def test_2_screenshot(self):
        """
        Ensure that all actors are able to take pictures that aren't completely transparent or black
        """
        for idx in range(self.NUM_USERS):
            player = self.adapter.get_player(idx)
            self.adapter.get_player_screenshot(player)
            img: Image.Image = Image.open(Path(f"./PlayerViews/User{idx}_screenshot.png"))
            self.assertFalse(all(p == (0, 0, 0, 255) for p in img.getdata()), "Black screenshot taken")
            self.assertFalse(all(p == (0, 0, 0, 0) for p in img.getdata()), "Transparent screenshot taken")
            self.assertGreater(img.height, 1)
            self.assertGreater(img.width, 1)

    def test_3_buying_power(self):
        """
        Have randomly moving users buy weapons from towns they encounter
        """
        successes = 0
        for idx in range(self.NUM_USERS):
            player = self.adapter.get_player(idx)
            player.currency += 10000
        for step in range(self.NUM_STEPS):
            for result in self._move_randomly():
                if len(result) == 1 and result[0].failed:
                    pass
                player: PlayerCharacter = result[0].source
                if self.adapter.is_town(player.location):
                    if player.location.store.inventory:
                        town: GameSpace.Town = player.location
                        index = random.randint(0, len(set(town.store.inventory)))
                        if town.store.sell_item(index, player):
                            item = player.inventory[-1]
                            player.equip(item)
                            self.assertTrue(player.has_weapon_equipped)
                            self.assertTrue(player.weapon == item)
                            self.assertIsNotNone(player.weapon)
                            successes += 1
        LOG.info(f"Buying Successes: {successes}")
        self.assertGreater(successes, 0, "All transactions failed")

    def tearDown(self) -> None:
        LOG.info(f"Sprite-Miss Count: {self.display._sprite_cache.miss_count}")
        self.display.on_draw()
        self.display.get_world_view()
