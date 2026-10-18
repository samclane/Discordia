"""
Draws the world map. Output device independent: WebApp.py serves it a chunk at a time over HTTP, the
Discord interface asks for the few squares around a player.
Inspired by PyOverheadGame's architecture: https://github.com/albertz/PyOverheadGame/blob/master/game/app.py

"""

from __future__ import annotations

import io
import logging
import threading
from pathlib import Path
from functools import lru_cache
from itertools import chain
from typing import Any, Callable, Iterable

from PIL import Image

from Discordia import SPRITE_FOLDER
from Discordia.GameLogic import Actors, GameSpace
from Discordia.Interface.WorldAdapter import WorldAdapter

LOG = logging.getLogger("Discordia.Interface.DesktopApp")
WINDOW_NAME = "Discordia"
# cv2 used to fail silently on a missing dir
VIEW_FOLDER = Path("./Discordia/PlayerViews")

# Kenney's RPG Urban pack (CC0), as a packed sheet of 16px tiles, 27 to a row.
TILESHEET = SPRITE_FOLDER / "Terrain" / "kenney_rpg_urban.png"
SHEET_COLUMNS = 27
TILE = 16
# Pavement goes down under every square; other terrain is laid on top of it, kerbed where it meets
# something else.
GROUND = 117
# Top-left tile of each terrain's block in the sheet. Every block has the same layout: a 3x3 of corners,
# edges and middle at columns 0-2, and inside corners at columns 5-6 of the top two rows.
BLOCKS = {"water": 170, "grass": 0, "mountain": 81}
# Pixels a square in the zoomed-out overview: still reads as coast and towns, at a tenth of the bytes.
MINI_TILE = 2


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def _quarters(block: int):
    """Per quarter of a square: the neighbour bits it looks at, the sheet tiles it can come from, and
    which 8px of them to take. A quarter only cares about the two sides and the corner it touches.
    (vertical bit, horizontal bit, diagonal bit, outside corner, vertical edge, horizontal edge, inside
    corner, box)
    """
    b, row = block, SHEET_COLUMNS
    half = TILE // 2
    return [
        (1, 3, 0, b, b + row, b + 1, b + row + 6, (0, 0, half, half)),  # nw
        (1, 4, 2, b + 2, b + row + 2, b + 1, b + row + 5, (half, 0, TILE, half)),  # ne
        (
            6,
            3,
            5,
            b + 2 * row,
            b + row,
            b + 2 * row + 1,
            b + 6,
            (0, half, half, TILE),
        ),  # sw
        (
            6,
            4,
            7,
            b + 2 * row + 2,
            b + row + 2,
            b + 2 * row + 1,
            b + 5,
            (half, half, TILE, TILE),
        ),  # se
    ]


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
        # Web requests and Discord commands both trigger draws.
        self._draw_lock = threading.Lock()
        self._sheet = Image.open(TILESHEET).convert("RGBA")
        self._terrain_cache = keydefaultdict(lambda key: self._terrain_tile(*key))
        self._ground = self._sheet_tile(GROUND)
        self.base_cell_width, self.base_cell_height = self._ground.size

    def _sheet_tile(self, index: int) -> Image.Image:
        row, col = divmod(index, SHEET_COLUMNS)
        return self._sheet.crop(
            (col * TILE, row * TILE, (col + 1) * TILE, (row + 1) * TILE)
        )

    def _terrain_tile(self, name: str, neighbours: int) -> Image.Image | None:
        """A terrain square shaped to its neighbours, from quarters of its block: a quarter with both
        sides and the corner the same terrain is middle, both sides but not the corner an inside corner,
        one side an edge, neither an outside corner. None for terrain drawn as bare ground.
        """
        if name not in BLOCKS:
            return None
        block = BLOCKS[name]
        tile = Image.new("RGBA", (TILE, TILE))
        for v, h, d, outside, v_edge, h_edge, inside, box in _quarters(block):
            same_v, same_h = neighbours >> v & 1, neighbours >> h & 1
            if same_v and same_h:
                source = (
                    inside if not neighbours >> d & 1 else block + SHEET_COLUMNS + 1
                )
            else:
                source = v_edge if same_v else h_edge if same_h else outside
            tile.paste(self._sheet_tile(source).crop(box), box[:2])
        return tile

    def _paste(self, sprite_path: str, x: int, y: int, target: Image.Image):
        """Blit a tile-sized sprite at grid position (x, y) of target, honouring its alpha."""
        sprite = self._sprite_cache[sprite_path]
        target.paste(
            sprite, (x * self.base_cell_width, y * self.base_cell_height), sprite
        )

    def _draw(
        self,
        spaces: Iterable[GameSpace.Space],
        x0: int,
        y0: int,
        width: int,
        height: int,
    ) -> Image.Image:
        """The squares given, drawn into a width x height tile image whose top left is (x0, y0)."""
        image = Image.new(
            "RGB", (width * self.base_cell_width, height * self.base_cell_height)
        )
        with self._draw_lock:
            for space in spaces:
                x, y = space.x - x0, space.y - y0
                pos = (x * self.base_cell_width, y * self.base_cell_height)
                # Rounded corners are see-through, so there has to be ground under them.
                image.paste(self._ground, pos)
                terrain = space.terrain
                tile = self._terrain_cache[terrain.name, terrain.neighbours]
                if tile is not None:
                    image.paste(tile, pos, tile)
                if isinstance(
                    space, (GameSpace.Town, GameSpace.Wilds, GameSpace.Cache)
                ):
                    self._paste(space.sprite_path_string, x, y, image)
        return image

    def chunk_png(self, cx: int, cy: int, mini: bool = False) -> bytes | None:
        """One chunk's terrain, towns and wilds as PNG, or None if nobody has been there yet. `mini` is
        the overview a zoomed-out map uses, MINI_TILE pixels a square.

        Never generates the chunk: this is called from the web server's threads, and generation belongs
        to the game loop. A chunk never changes once generated, so neither does its picture.
        """
        if self.world_adapter.world.loaded_chunk(cx, cy) is None:
            return None
        return self._chunk_mini_png(cx, cy) if mini else self._chunk_png(cx, cy)

    def _chunk_image(self, cx: int, cy: int) -> Image.Image:
        rows = self.world_adapter.world.loaded_chunk(cx, cy) or []
        size = GameSpace.CHUNK_SIZE
        return self._draw(chain.from_iterable(rows), cx * size, cy * size, size, size)

    # Zoomed in, a screenful is under 200 chunks, so these never thrash.
    @lru_cache(maxsize=256)  # ~35 KB each
    def _chunk_png(self, cx: int, cy: int) -> bytes:
        return _png(self._chunk_image(cx, cy))

    # A zoomed-out map shows every explored chunk at once: cache them all, or every page load redraws
    # the lot (an LRU smaller than one view's worth never hits).
    # ponytail: past ~4000 explored chunks a fit view thrashes this and puts that many <img>s on the page.
    # Then: overview tiles of 8x8 chunks, built from these.
    @lru_cache(maxsize=4096)  # ~3 KB each
    def _chunk_mini_png(self, cx: int, cy: int) -> bytes:
        size = GameSpace.CHUNK_SIZE * MINI_TILE
        return _png(self._chunk_image(cx, cy).resize((size, size), Image.Resampling.BOX))

    def draw_region(self, x0: int, y0: int, x1: int, y1: int) -> Image.Image:
        """Squares [x0, x1) x [y0, y1), clipped to the map, with the actors standing on them.
        Generates any chunk it touches, so call it from the game loop."""
        world = self.world_adapter.world
        x0, y0 = max(x0, 0), max(y0, 0)
        x1, y1 = min(x1, world.width), min(y1, world.height)
        image = self._draw(
            (world.space_at(x, y) for y in range(y0, y1) for x in range(x0, x1)),
            x0,
            y0,
            x1 - x0,
            y1 - y0,
        )
        for actor in [*world.npcs, *self.world_adapter.iter_players()]:
            loc = actor.location
            if loc is not None and x0 <= loc.x < x1 and y0 <= loc.y < y1:
                self._paste(actor.sprite_path_string, loc.x - x0, loc.y - y0, image)
        return image

    def get_player_view(self, character: Actors.PlayerCharacter) -> str:
        x, y, fov = character.location.x, character.location.y, character.fov
        LOG.info(f"Getting PlayerView: {character.name} at ({x}, {y})")
        img = self.draw_region(x - fov, y - fov, x + fov + 1, y + fov + 1)
        img_path = VIEW_FOLDER / f"{character.name}_screenshot.png"
        img.save(img_path)
        return str(img_path)
