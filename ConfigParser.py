import configparser
import logging
import os
from os import environ
from pathlib import Path
from shutil import copyfile


LOG = logging.getLogger("Discordia.ConfigParser")

if not os.path.isfile(Path("./config.ini")):
    LOG.info("No config file found, creating new one...")
    copyfile(Path("./default.ini"), Path("./config.ini"))

config = configparser.ConfigParser()
# defaults first, user config wins for whatever it actually defines
config.read([Path("./default.ini"), Path("./config.ini")])

DISCORD_TOKEN = environ.get('DISCORD_TOKEN') or config['Discord']['Token']
DISCORD_PREFIX = config['Discord']['Prefix']
DISCORD_MSG_TIMEOUT = int(config['Discord']['Timeout'])

WORLD_NAME = config['World']['Name']
WORLD_WIDTH = int(config['World']['Width'])
WORLD_HEIGHT = int(config['World']['Height'])

# TODO: Allow user to specify display size, then scroll through tiles
DISPLAY_WIDTH = int(config['Display']['Width'])
DISPLAY_HEIGHT = int(config['Display']['Height'])
DISPLAY_SCROLL_SPEED = int(config['Display']['ScrollSpeed'])
