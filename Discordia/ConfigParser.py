import configparser
import logging

LOG = logging.getLogger("Discordia.ConfigParser")

config = configparser.ConfigParser()
config.read('../config.ini')

try:
    DISCORD_TOKEN = config['Discord']['Token']
    DISCORD_PREFIX = config['Discord']['Prefix']
    DISCORD_MSG_TIMEOUT = int(config['Discord']['Timeout'])

    WORLD_NAME = config['World']['Name']
    WORLD_WIDTH = int(config['World']['Width'])
    WORLD_HEIGHT = int(config['World']['Height'])

    # TODO: Allow user to specify display size, then scroll through tiles
    DISPLAY_WIDTH = int(config['Display']['Width'])
    DISPLAY_HEIGHT = int(config['Display']['Height'])
    DISPLAY_SCROLL_SPEED = int(config['Display']['ScrollSpeed'])
except Exception as exc:
    LOG.exception("Error loading config file:")
    raise exc
