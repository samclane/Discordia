"""
SQLite persistence for a Discordia server.

The map is *not* stored: a World is fully reproducible from its seed, so the world table holds the seed and the
generation parameters and `load()` re-generates an identical map. Only the state that can't be re-derived --
characters, where they're standing, what they're carrying -- gets rows.

NPCs are deliberately not persisted; they're spawned by Events and despawn on death.
"""
from __future__ import annotations

import json
import logging
import pydoc
import sqlite3
from dataclasses import asdict
from pathlib import Path

from Discordia.GameLogic import Actors, GameSpace
from Discordia.GameLogic.Items import Equipment, EquipmentSet
from Discordia.GameLogic.Procedural import WorldGenerationParameters
from Discordia.Interface.WorldAdapter import WorldAdapter

LOG = logging.getLogger("Discordia.Interface.Database")

DEFAULT_PATH = Path("./discordia.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS world (
    id          INTEGER PRIMARY KEY CHECK (id = 0),  -- one world per database
    name        TEXT    NOT NULL,
    width       INTEGER NOT NULL,
    height      INTEGER NOT NULL,
    seed        INTEGER NOT NULL,
    gen_params  TEXT    NOT NULL  -- JSON dump of WorldGenerationParameters
);

CREATE TABLE IF NOT EXISTS character (
    discord_id      INTEGER PRIMARY KEY,
    name            TEXT    NOT NULL,
    class_path      TEXT    NOT NULL,
    hit_points      REAL    NOT NULL,
    hit_points_max  INTEGER NOT NULL,
    currency        INTEGER NOT NULL,
    x               INTEGER NOT NULL,
    y               INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS item (
    id          INTEGER PRIMARY KEY,
    discord_id  INTEGER NOT NULL REFERENCES character (discord_id) ON DELETE CASCADE,
    class_path  TEXT    NOT NULL,
    slot        TEXT  -- an EquipmentSet slot name, or NULL for "in the backpack"
);
"""

# Classes may only be restored from these modules. The database is ours, but `pydoc.locate` imports whatever it's
# handed, and a corrupted or hand-edited file shouldn't get to pick the module.
_ALLOWED_MODULES = frozenset({
    "Discordia.GameLogic.Actors",
    "Discordia.GameLogic.Armor",
    "Discordia.GameLogic.Items",
    "Discordia.GameLogic.Weapons",
})


def _class_path(obj) -> str:
    return f"{type(obj).__module__}.{type(obj).__name__}"


def _resolve(class_path: str, expected: type) -> type:
    module, _, _ = class_path.rpartition('.')
    if module not in _ALLOWED_MODULES:
        raise ValueError(f"Refusing to load {class_path!r}: {module!r} is not a game-logic module")
    located = pydoc.locate(class_path)
    if not (isinstance(located, type) and issubclass(located, expected)):
        raise ValueError(f"{class_path!r} is not a {expected.__name__} subclass")
    return located


class Database:
    """ Loads and saves the whole server. Cheap enough to call save() on a timer; see main.py. """

    def __init__(self, path: Path | str = DEFAULT_PATH):
        # check_same_thread=False: the autosave thread and the shutdown save use the same connection, and sqlite
        # serializes them for us.
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(SCHEMA)

    def close(self):
        self.connection.close()

    def load(self) -> WorldAdapter | None:
        """ Rebuild the server from disk, or None if this database has never been saved to. """
        row = self.connection.execute("SELECT * FROM world WHERE id = 0").fetchone()
        if row is None:
            return None

        world = GameSpace.World(row["name"], row["width"], row["height"],
                                WorldGenerationParameters(**json.loads(row["gen_params"])),
                                seed=row["seed"])
        adapter = WorldAdapter(world)
        for character_row in self.connection.execute("SELECT * FROM character"):
            self._load_character(adapter, character_row)
        LOG.info(f"Loaded world '{world.name}' (seed {world.seed}) with {len(world.players)} characters")
        return adapter

    def _load_character(self, adapter: WorldAdapter, row: sqlite3.Row):
        discord_id = row["discord_id"]
        adapter.register_player(discord_id, row["name"])
        character = adapter.get_player(discord_id)

        character.player_class = _resolve(row["class_path"], Actors.PlayerClass)()  # resets hit points to the max
        character.hit_points_max = row["hit_points_max"]
        character.hit_points = row["hit_points"]
        character.currency = row["currency"]
        character.location = adapter.world.map[row["y"]][row["x"]]

        for item_row in self.connection.execute("SELECT * FROM item WHERE discord_id = ?", (discord_id,)):
            item = _resolve(item_row["class_path"], Equipment)()
            if item_row["slot"] is None:
                character.inventory.append(item)
            else:
                character.equip(item, EquipmentSet.SLOTS[item_row["slot"]])

    def save(self, adapter: WorldAdapter):
        """ Full rewrite of the mutable state, in one transaction. """
        # ponytail: rewrites every character each time. Fine for a Discord server's worth of players; if that ever
        # stops being true, save only the character whose command just ran.
        world = adapter.world
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO world VALUES (0, ?, ?, ?, ?, ?)",
                (world.name, world.width, world.height, world.seed, json.dumps(asdict(world.gen_params))))
            self.connection.execute("DELETE FROM character")  # cascades to item
            for discord_id, character in adapter.iter_registered():
                self._save_character(discord_id, character)

    def _save_character(self, discord_id: int, character: Actors.PlayerCharacter):
        self.connection.execute(
            "INSERT INTO character VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (discord_id, character.name, _class_path(character.player_class), character.hit_points,
             character.hit_points_max, character.currency, character.location.x, character.location.y))

        equipped = [(_class_path(item), slot) for slot in EquipmentSet.SLOTS
                    for item in [getattr(character.equipment_set, slot)]
                    if type(item) not in EquipmentSet.SLOTS.values()]  # the bare base classes are empty slots
        self.connection.executemany(
            "INSERT INTO item (discord_id, class_path, slot) VALUES (?, ?, ?)",
            [(discord_id, class_path, slot) for class_path, slot in equipped]
            + [(discord_id, _class_path(item), None) for item in character.inventory])
