import logging
import os
import random
import threading
import unittest
from pathlib import Path

import arcade
from PIL import Image

import Discordia.ConfigParser as ConfigParser
from Discordia.GameLogic import GameSpace
from Discordia.Interface.DiscordInterface import DiscordInterface
from Discordia.Interface.WorldAdapter import WorldAdapter
from Discordia.Interface.Rendering import DesktopApp

LOG = logging.getLogger("Discordia")
logging.basicConfig(level=logging.INFO)


def windowed_test(test):
    def test_wrapper(*args, **kwargs):
        test(*args, **kwargs)
        arcade.close_window()
    return test_wrapper


class TestGeneral(unittest.TestCase):

    def setUp(self):
        """Change to the directory where main.py will be ran"""
        os.chdir("../Discordia/")
        self.discord_interface = None

    def test_connect_disconnect(self):
        # Start bot
        world = GameSpace.World(ConfigParser.WORLD_NAME, 10, 10)
        adapter = WorldAdapter(world)
        self.discord_interface = DiscordInterface(adapter)
        run_thread = threading.Thread(target=lambda: self.discord_interface.bot.run(ConfigParser.DISCORD_TOKEN))
        run_thread.start()

        # Wait for 1 second then exit
        run_thread.join(1)

    def test_world_creation(self):
        world = GameSpace.World(ConfigParser.WORLD_NAME, ConfigParser.WORLD_WIDTH, ConfigParser.WORLD_HEIGHT)
        self.discord_interface = DiscordInterface(WorldAdapter(world))
        discord_thread = threading.Thread(target=lambda: self.discord_interface.bot.run(ConfigParser.DISCORD_TOKEN))
        discord_thread.start()

        # Wait for 1 second then exit
        discord_thread.join(1)

    @windowed_test
    def test_rendering(self):

        world = GameSpace.World(ConfigParser.WORLD_NAME, ConfigParser.WORLD_WIDTH, ConfigParser.WORLD_HEIGHT)
        adapter = WorldAdapter(world)
        window = DesktopApp.MainWindow(adapter)
        window.test()

    def test_screenshot(self):

        for n in range(10):
            from Discordia.Interface.Rendering import DesktopApp

            print(f"Test {n}:")
            world = GameSpace.World(ConfigParser.WORLD_NAME, ConfigParser.WORLD_WIDTH, ConfigParser.WORLD_HEIGHT)
            adapter = WorldAdapter(world)
            window = DesktopApp.MainWindow(adapter, 10000, 10000)
            window.set_visible(False)
            pid = random.randint(0, 65535)
            adapter.register_player(pid, "<test>")
            actor = adapter.get_player(pid)
            window.on_draw()
            window.update(1/60)
            window.get_player_view(actor)
            im: Image = Image.open(Path("./PlayerViews/test_screenshot.png"))
            self.assertFalse(all(p == (0, 0, 0, 255) for p in im.getdata()), "Black screenshot taken")
            self.assertFalse(any(p == (0, 0, 0, 0) for p in im.getdata()), "Transparent screenshot pixels found.")
            # Note: Screenshots appear distorted. But they're not transparent. Using a giant window might work.
            arcade.close_window()

    def doCleanups(self) -> None:
        super().doCleanups()
        if self.discord_interface is not None:
            self.discord_interface.bot.loop.create_task(self.discord_interface.bot.close())
