import logging
import random
import unittest
import threading
import os
from PIL import Image
from pathlib import Path
from time import sleep

from Discordia.GameLogic import GameSpace
from Discordia.Interface.DiscordInterface import DiscordInterface
from Discordia.Interface.WorldAdapter import WorldAdapter
import Discordia.ConfigParser as ConfigParser

LOG = logging.getLogger("Discordia")
logging.basicConfig(level=logging.INFO)


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

    def test_rendering(self):
        from Discordia.Interface.Rendering import DesktopApp

        world = GameSpace.World(ConfigParser.WORLD_NAME, ConfigParser.WORLD_WIDTH, ConfigParser.WORLD_HEIGHT)
        adapter = WorldAdapter(world)
        window = DesktopApp.MainWindow(adapter)
        try:
            window.test()
        finally:
            window.close()

    def test_screenshot(self):
        from Discordia.Interface.Rendering import DesktopApp

        world = GameSpace.World(ConfigParser.WORLD_NAME, ConfigParser.WORLD_WIDTH, ConfigParser.WORLD_HEIGHT)
        adapter = WorldAdapter(world)
        window = DesktopApp.MainWindow(adapter, 10000, 10000)
        window.set_visible(False)
        for n in range(1):
            print(f"Test {n}:")
            adapter.world = GameSpace.World(ConfigParser.WORLD_NAME, ConfigParser.WORLD_WIDTH, ConfigParser.WORLD_HEIGHT)
            pid = random.randint(0, 65535)
            adapter.register_player(pid, "<test>")
            actor = adapter.get_player(pid)
            window.on_draw()
            window.on_update(0)
            window.get_player_view(actor)
            im: Image = Image.open(Path("./PlayerViews/test_screenshot.png"))
            self.assertFalse(all(p == (0, 0, 0, 255) for p in im.getdata()), "Black screenshot taken")
            self.assertFalse(any(p == (0, 0, 0, 0) for p in im.getdata()), "Transparent screenshot pixels found.")
            # Note: Screenshots appear distorted. But they're not transparent. Using a giant window might work.

    def doCleanups(self) -> None:
        super().doCleanups()
        if self.discord_interface is not None:
            self.discord_interface.bot.loop.create_task(self.discord_interface.bot.close())