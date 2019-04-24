import configparser
import logging

LOG = logging.getLogger("Discordia.ConfigParser")

config = configparser.ConfigParser()
config.read('../config.ini')

try:
    DISCORD_TOKEN = config['Discord']['Token']
    DISCORD_PREFIX = config['Discord']['Prefix']
except Exception as exc:
    LOG.exception("Error loading config file:")
    raise exc
