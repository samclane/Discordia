"""
Holds the rendering surface for the world map. Output device independent: WebApp.py serves it over HTTP,
the Discord interface crops PNGs out of it.
Inspired by PyOverheadGame's architecture: https://github.com/albertz/PyOverheadGame/blob/master/game/app.py

"""

from __future__ import annotations

import io
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from Discordia.GameLogic import Actors, GameSpace
from Discordia.Interface.WorldAdapter import WorldAdapter

LOG = logging.getLogger("Discordia.Interface.DesktopApp")
WINDOW_NAME = "Discordia"
VIEW_FOLDER = Path("./Discordia/PlayerViews")  # both view types land here; cv2 used to fail silently on a missing dir


class keydefaultdict(dict):
    """dict that fills a missing entry by calling factory(key). defaultdict can't: its factory takes no arguments."""

    def __init__(self, factory: Callable[[Any], Any]):
        super().__init__()
        self.factory = factory
        self._miss_count = 0

    def __missing__(self, key):
        self._miss_count += 1
        ret = self[key] = self.factory(key)
        return ret

    @property
    def miss_count(self):
        return self._miss_count


class WindowRenderer:
    def __init__(self, world_adapter: WorldAdapter):
        self.world_adapter = world_adapter
        self.world_adapter.add_renderer(self)
        VIEW_FOLDER.mkdir(parents=True, exist_ok=True)

        self._sprite_cache = keydefaultdict(
            lambda path: Image.open(path).convert("RGBA")
        )
        self._draw_lock = threading.Lock()  # web requests and Discord commands both trigger draws

        water = self._sprite_cache[GameSpace.WaterTerrain().sprite_path_string]
        self.base_cell_width, self.base_cell_height = water.size

        # Terrain, towns and wilds are fixed at world generation, so bake them into the background once
        # instead of re-blitting every tile on every frame; only actors move.
        # Shoreline tiles have soft alpha edges, so they need water under them or they fringe black.
        self._background = Image.new(
            "RGB",
            (
                self.world_adapter.width * self.base_cell_width,
                self.world_adapter.height * self.base_cell_height,
            ),
        )
        for y in range(self.world_adapter.height):
            for x in range(self.world_adapter.width):
                self._background.paste(
                    water, (x * self.base_cell_width, y * self.base_cell_height), water
                )
        for y, row in enumerate(self.world_adapter.world.map):
            for x, space in enumerate(row):
                self._paste(space.terrain.sprite_path_string, x, y, self._background)
        for town in self.world_adapter.world.towns:
            self._paste(town.sprite_path_string, town.x, town.y, self._background)
        for wilds in self.world_adapter.world.wilds:
            self._paste(wilds.sprite_path_string, wilds.x, wilds.y, self._background)
        self._background_png: bytes | None = None  # encoded on first request, then never again
        self.rendered_canvas = self._background.copy()

    def _paste(
        self, sprite_path: str, x: int, y: int, target: Image.Image | None = None
    ):
        """Blit a tile-sized sprite at grid position (x, y), honouring its alpha."""
        if target is None:
            target = self.rendered_canvas
        sprite = self._sprite_cache[sprite_path]
        pos = (x * self.base_cell_width, y * self.base_cell_height)
        target.paste(sprite, pos, sprite)

    def on_draw(self) -> Image.Image:
        with self._draw_lock:
            # Start clean each frame: alpha sprites would otherwise pile up on the previous one.
            self.rendered_canvas = self._background.copy()
            for npc in self.world_adapter.world.npcs:
                if npc.location is None:  # dead, not yet reaped by the next tick
                    continue
                self._paste(npc.sprite_path_string, npc.location.x, npc.location.y)
            for player in self.world_adapter.iter_players():
                self._paste(
                    player.sprite_path_string, player.location.x, player.location.y
                )
            return self.rendered_canvas

    def background_png(self) -> bytes:
        """The static layers only, encoded once. The web client draws actors over this itself."""
        if self._background_png is None:
            buffer = io.BytesIO()
            self._background.save(buffer, "PNG")
            self._background_png = buffer.getvalue()
        return self._background_png

    def render_png(self) -> bytes:
        """The whole world as PNG bytes, freshly drawn."""
        buffer = io.BytesIO()
        self.on_draw().save(buffer, "PNG")
        return buffer.getvalue()

    def get_player_view(self, character: Actors.PlayerCharacter) -> str:
        world = self.on_draw()

        # Need to find top left coordinate
        # Find tile first
        top_left_tile: GameSpace.Space = character.location - (
            character.fov,
            character.fov,
        )
        assert top_left_tile.x >= 0 and top_left_tile.y >= 0, "Negative coordinates"

        # Then convert game-coordinates to pixel (x, y, width, height)
        x1 = min(max(top_left_tile.x, 0), self.world_adapter.width)
        y1 = min(max(top_left_tile.y, 0), self.world_adapter.height)
        width = height = (character.fov * 2) + 1
        x2 = min(max(top_left_tile.x + width, 0), self.world_adapter.width)
        y2 = min(max(top_left_tile.y + height, 0), self.world_adapter.height)

        # Debugging
        LOG.info(f"Getting PlayerView: {character.name} {x1} {y1} {x2} {y2}")

        img = world.crop(
            (
                x1 * self.base_cell_width,
                y1 * self.base_cell_height,
                x2 * self.base_cell_width,
                y2 * self.base_cell_height,
            )
        )
        img_path = VIEW_FOLDER / f"{character.name}_screenshot.png"
        img.save(img_path)
        return str(img_path)

    def get_world_view(self, title: str | None = None) -> str:
        if title is None:
            title = str(int(time.time()))
        img_path = VIEW_FOLDER / f"world_{title}.png"
        self.on_draw().save(img_path)
        return str(img_path)
