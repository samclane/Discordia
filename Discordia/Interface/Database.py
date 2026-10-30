"""
SQLite persistence for a Discordia server.

The map is *not* stored: a World is fully reproducible from its seed, so the world table holds the seed and the
generation parameters and `load()` re-generates an identical map. Only the state that can't be re-derived --
characters, where they're standing, what they're carrying, each Discord server's settings -- gets rows.

The NPCs roaming the map are saved (who, where, how hurt); the ones inside wilds events aren't, since the events
themselves restock on a square's next visit.
"""

from __future__ import annotations

import json
import logging
import pydoc
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path

from Discordia.GameLogic import Actors, GameSpace
from Discordia.GameLogic.Items import Ammo, Equipment, EquipmentSet
from Discordia.GameLogic.Procedural import WorldGenerationParameters
from Discordia.Interface.WorldAdapter import GuildSettings, WorldAdapter

LOG = logging.getLogger("Discordia.Interface.Database")

DEFAULT_PATH = Path("./discordia.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS world (
    id          INTEGER PRIMARY KEY CHECK (id = 0),  -- one world per database
    name        TEXT    NOT NULL,
    width       INTEGER NOT NULL,
    height      INTEGER NOT NULL,
    seed        INTEGER NOT NULL,
    gen_params  TEXT    NOT NULL,  -- JSON dump of WorldGenerationParameters
    ticks       INTEGER NOT NULL DEFAULT 0,  -- World.ticks, so hideouts keep their pay day
    saved_at    REAL  -- unix time of the save, to pay hideouts for the downtime; NULL in older saves
);

CREATE TABLE IF NOT EXISTS character (
    discord_id      INTEGER PRIMARY KEY,
    name            TEXT    NOT NULL,
    class_path      TEXT    NOT NULL,
    hit_points      REAL    NOT NULL,
    hit_points_max  INTEGER NOT NULL,
    currency        INTEGER NOT NULL,
    experience      INTEGER NOT NULL DEFAULT 0,
    stash_currency  INTEGER NOT NULL DEFAULT 0,
    hideout_level   INTEGER NOT NULL DEFAULT 0,
    raid_home_at    INTEGER,  -- PlayerCharacter.auto_raid's World.ticks to head home at; NULL when none is on
    raid_depth      INTEGER,  -- and its depth
    camping         INTEGER NOT NULL DEFAULT 0,
    x               INTEGER NOT NULL,
    y               INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS item (
    id          INTEGER PRIMARY KEY,
    discord_id  INTEGER NOT NULL REFERENCES character (discord_id) ON DELETE CASCADE,
    class_path  TEXT    NOT NULL,
    slot        TEXT,  -- an EquipmentSet slot name, STASH, POUCH, or NULL for "in the backpack"
    state       TEXT  -- JSON of what changes in play (see _item_state), or NULL
);

CREATE TABLE IF NOT EXISTS npc (
    id              INTEGER PRIMARY KEY,
    class_path      TEXT    NOT NULL,  -- Raider, Animal...
    body_path       TEXT    NOT NULL,  -- its BodyType
    name            TEXT    NOT NULL,
    hit_points      REAL    NOT NULL,
    hit_points_max  INTEGER NOT NULL,
    currency        INTEGER NOT NULL,
    x               INTEGER NOT NULL,
    y               INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS store (
    x           INTEGER NOT NULL,  -- the town's square
    y           INTEGER NOT NULL,
    items       TEXT    NOT NULL,  -- JSON list of class paths, in shelf order (the # a player buys by)
    PRIMARY KEY (x, y)
);

CREATE TABLE IF NOT EXISTS guild (
    guild_id    INTEGER PRIMARY KEY,  -- a Discord server
    settings    TEXT    NOT NULL  -- JSON dump of GuildSettings
);
"""

# Classes may only be restored from these modules. The database is ours, but `pydoc.locate` imports whatever it's
# handed, and a corrupted or hand-edited file shouldn't get to pick the module.
_ALLOWED_MODULES = frozenset(
    {
        "Discordia.GameLogic.Actors",
        "Discordia.GameLogic.Armor",
        "Discordia.GameLogic.Items",
        "Discordia.GameLogic.Weapons",
    }
)


STASH = "stash"  # item.slot for what's banked in town rather than carried
POUCH = "pouch"  # item.slot for the one carried item a death leaves alone


# What an item changes in play, as it's set on the instance: rounds loaded, a jam, a pinged clip, a belt's ramp.
# The rest comes back from the item's stat block.
ITEM_STATE = ("_current_capacity", "_jammed", "_pinged", "_consecutive_fires")


def _item_state(item: Equipment) -> str | None:
    state = {key: value for key, value in vars(item).items() if key in ITEM_STATE}
    if isinstance(item, Ammo):
        state["quantity"] = item.quantity
    return json.dumps(state) if state else None


def _restore_item(class_path: str, state: str | None) -> Equipment:
    item = _resolve(class_path, Equipment)()
    for key, value in json.loads(state or "{}").items():
        if key == "quantity":  # drained through take(), which prices a part-used box down too
            item.take(max(0, item.quantity - value))  # type: ignore[attr-defined]
        elif key in ITEM_STATE:
            setattr(item, key, value)
    return item


def _class_path(obj) -> str:
    return f"{type(obj).__module__}.{type(obj).__name__}"


def _resolve(class_path: str, expected: type) -> type:
    module, _, _ = class_path.rpartition(".")
    if module not in _ALLOWED_MODULES:
        raise ValueError(
            f"Refusing to load {class_path!r}: {module!r} is not a game-logic module"
        )
    located = pydoc.locate(class_path)
    if not (isinstance(located, type) and issubclass(located, expected)):
        raise ValueError(f"{class_path!r} is not a {expected.__name__} subclass")
    return located


class Database:
    """Loads and saves the whole server. Cheap enough to call save() on a timer; see main.py."""

    def __init__(self, path: Path | str = DEFAULT_PATH):
        # check_same_thread=False: the periodic autosave runs on the bot's event loop and the shutdown save
        # doesn't, so the same connection gets used from more than one thread. sqlite serializes them for us.
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(SCHEMA)
        self._migrate()

    def _migrate(self):
        """Add columns a save file predates. CREATE TABLE IF NOT EXISTS leaves an existing table alone,
        so a schema change reaches old worlds only if something adds the column by hand.
        """
        added = [
            ("character", "experience", "INTEGER NOT NULL DEFAULT 0"),
            ("character", "stash_currency", "INTEGER NOT NULL DEFAULT 0"),
            ("character", "hideout_level", "INTEGER NOT NULL DEFAULT 0"),
            ("character", "raid_home_at", "INTEGER"),
            ("character", "raid_depth", "INTEGER"),
            ("character", "camping", "INTEGER NOT NULL DEFAULT 0"),
            ("item", "state", "TEXT"),
            ("world", "ticks", "INTEGER NOT NULL DEFAULT 0"),
            ("world", "saved_at", "REAL"),
        ]
        for table, column, declaration in added:
            columns = {row["name"] for row in self.connection.execute(f"PRAGMA table_info({table})")}
            if column not in columns:
                LOG.info(f"Adding {table}.{column} to a save file that predates it")
                with self.connection:
                    self.connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    def close(self):
        self.connection.close()

    def load(self, tick_seconds: float = 5.0) -> WorldAdapter | None:
        """Rebuild the server from disk, or None if this database has never been saved to. The world's clock
        then runs on for however long it sat on disk, at `tick_seconds` a tick, paying hideouts as it goes."""
        row = self.connection.execute("SELECT * FROM world WHERE id = 0").fetchone()
        if row is None:
            return None

        world = GameSpace.World(
            row["name"],
            row["width"],
            row["height"],
            WorldGenerationParameters(**json.loads(row["gen_params"])),
            seed=row["seed"],
        )
        world.ticks, saved_at = row["ticks"], row["saved_at"]
        adapter = WorldAdapter(world)
        for character_row in self.connection.execute("SELECT * FROM character"):
            self._load_character(adapter, character_row)
        for npc_row in self.connection.execute("SELECT * FROM npc"):
            npc = _resolve(npc_row["class_path"], Actors.NPC)(
                None, npc_row["hit_points_max"], npc_row["name"], _resolve(npc_row["body_path"], Actors.BodyType)()
            )
            npc.hit_points, npc.currency = npc_row["hit_points"], npc_row["currency"]
            world.add_actor(npc, world.space_at(npc_row["x"], npc_row["y"]))
        for store_row in self.connection.execute("SELECT * FROM store"):
            town = world.space_at(store_row["x"], store_row["y"])
            if isinstance(town, GameSpace.Town):  # always, unless the map generator changed under the save
                town.store.inventory = [_resolve(path, Equipment)() for path in json.loads(store_row["items"])]
                town.store.traded = True
        adapter.guild_settings = {
            row["guild_id"]: GuildSettings(**json.loads(row["settings"]))
            for row in self.connection.execute("SELECT * FROM guild")
        }
        if saved_at is not None:  # after the characters: it pays their hideouts
            world.advance(max(0, int((time.time() - saved_at) / tick_seconds)))
        LOG.info(
            f"Loaded world '{world.name}' (seed {world.seed}) with {len(world.players)} characters"
        )
        return adapter

    def _load_character(self, adapter: WorldAdapter, row: sqlite3.Row):
        discord_id = row["discord_id"]
        adapter.register_player(discord_id, row["name"])
        character = adapter.get_player(discord_id)

        # Experience first: setting the class reads the level to work out the hit point ceiling.
        character.experience = row["experience"]
        character.player_class = _resolve(
            row["class_path"], Actors.PlayerClass
        )()  # resets hit points to the max
        character.hit_points_max = row["hit_points_max"]
        character.hit_points = row["hit_points"]
        character.currency = row["currency"]
        character.stash_currency = row["stash_currency"]
        character.hideout_level = row["hideout_level"]
        character.location = adapter.world.space_at(row["x"], row["y"])
        character.camping = bool(row["camping"])  # World.advance heals it for the downtime
        if row["raid_home_at"] is not None:  # deaths aren't saved, so the raid counts them from here
            character.auto_raid = (row["raid_home_at"], character.deaths, row["raid_depth"])

        for item_row in self.connection.execute(
            "SELECT * FROM item WHERE discord_id = ?", (discord_id,)
        ):
            item = _restore_item(item_row["class_path"], item_row["state"])
            if item_row["slot"] is None:
                character.inventory.append(item)
            elif item_row["slot"] == STASH:
                character.stash.append(item)
            elif item_row["slot"] == POUCH:
                character.pouch = item
            else:
                character.equip(item, EquipmentSet.SLOTS[item_row["slot"]])
        if not isinstance(character.location, GameSpace.Town):  # mid-raid: the haul counts from the restart
            character.raid_start = (character.currency, character.carried, character.experience)

    def save(self, adapter: WorldAdapter):
        """Full rewrite of the mutable state, in one transaction."""
        # ponytail: rewrites every character each time. Fine for a Discord server's worth of players; if that ever
        # stops being true, save only the character whose command just ran.
        world = adapter.world
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO world (id, name, width, height, seed, gen_params, ticks, saved_at)"
                " VALUES (0, ?, ?, ?, ?, ?, ?, ?)",
                (
                    world.name,
                    world.width,
                    world.height,
                    world.seed,
                    json.dumps(asdict(world.gen_params)),
                    world.ticks,
                    time.time(),
                ),
            )
            self.connection.execute("DELETE FROM character")  # cascades to item
            for discord_id, character in getattr(adapter, "players").items():
                self._save_character(discord_id, character)
            self.connection.execute("DELETE FROM npc")
            self.connection.executemany(
                "INSERT INTO npc (class_path, body_path, name, hit_points, hit_points_max, currency, x, y)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        _class_path(npc), _class_path(npc.body_type), npc.name, npc.hit_points, npc.hit_points_max,
                        npc.currency, npc.location.x, npc.location.y,
                    )
                    for npc in world.npcs
                    if not npc.is_dead  # a kill despawns it, but it stays listed until the next tick
                ],
            )
            self.connection.execute("DELETE FROM store")
            self.connection.executemany(
                "INSERT INTO store VALUES (?, ?, ?)",
                [
                    (town.x, town.y, json.dumps([_class_path(item) for item in town.store.inventory]))
                    for town in list(world.towns)
                    if town.store.traded
                ],
            )
            self.connection.execute("DELETE FROM guild")
            self.connection.executemany(
                "INSERT INTO guild VALUES (?, ?)",
                # list(): the website changes settings from its own thread.
                [(guild_id, json.dumps(asdict(settings))) for guild_id, settings in list(adapter.guild_settings.items())],
            )

    def _save_character(self, discord_id: int, character: Actors.PlayerCharacter):
        # Columns named, not positional: a migrated column lands at the end of the table, wherever it
        # sits in SCHEMA.
        self.connection.execute(
            "INSERT INTO character (discord_id, name, class_path, hit_points, hit_points_max,"
            " currency, experience, stash_currency, hideout_level, raid_home_at, raid_depth, camping, x, y)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                discord_id,
                character.name,
                _class_path(character.player_class),
                character.hit_points,
                character.hit_points_max,
                character.currency,
                character.experience,
                character.stash_currency,
                character.hideout_level,
                *((character.auto_raid[0], character.auto_raid[2]) if character.auto_raid else (None, None)),
                character.camping,
                character.location.x,
                character.location.y,
            ),
        )

        equipped = [
            (item, slot)
            for slot in EquipmentSet.SLOTS
            for item in [getattr(character.equipment_set, slot)]
            if type(item) not in EquipmentSet.SLOTS.values()
        ]  # the bare base classes are empty slots
        self.connection.executemany(
            "INSERT INTO item (discord_id, class_path, slot, state) VALUES (?, ?, ?, ?)",
            [
                (discord_id, _class_path(item), slot, _item_state(item))
                for item, slot in equipped
                + [(item, None) for item in character.inventory]
                + [(item, STASH) for item in character.stash]
                + ([(character.pouch, POUCH)] if character.pouch is not None else [])
            ],
        )
