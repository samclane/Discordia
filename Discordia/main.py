import asyncio
import logging
import os
import sys
import pickle

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from Discordia import ConfigParser
from Discordia.GameLogic import GameSpace
from Discordia.Interface.DiscordInterface import DiscordInterface
from Discordia.Interface.Rendering.DesktopApp import MainWindow
from Discordia.Interface.WorldAdapter import WorldAdapter

LOG = logging.getLogger("Discordia")
logging.basicConfig(level=logging.INFO)


async def update_display(display):
    while True:
        display.on_draw()
        await asyncio.sleep(1 / 60)


def main():
    if os.path.isfile(r'./world.p'):
        world: GameSpace.World = pickle.load(open(r'./world.p', 'rb'))
    else:
        world = GameSpace.World(ConfigParser.WORLD_NAME, ConfigParser.WORLD_WIDTH, ConfigParser.WORLD_HEIGHT)
    adapter = WorldAdapter(world)

    display = MainWindow(adapter)
    display.set_visible(0)
    display.on_draw()

    discord_interface = DiscordInterface(adapter)
    discord_interface.bot.loop.create_task(update_display(display))
    discord_interface.bot.run(ConfigParser.DISCORD_TOKEN)
    # TODO Figure out how to exit
    # TODO Add an arcade window for viewing the world render


if __name__ == '__main__':
    main()
