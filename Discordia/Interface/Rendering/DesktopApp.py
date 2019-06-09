"""
Holds classes for the basic window and rendering surface for a Desktop view. Image rendering should be independent.
Inspired by PyOverheadGame's architecture: https://github.com/albertz/PyOverheadGame/blob/master/game/app.py

"""
from __future__ import annotations

import logging
import time
from collections import defaultdict

import numpy as np
import pixelhouse as ph

from Discordia.ConfigParser import WORLD_HEIGHT, WORLD_WIDTH
from Discordia.GameLogic import Actors, GameSpace

LOG = logging.getLogger("Discordia.Interface.DesktopApp")
WINDOW_NAME = "Discordia"


def black_to_transparent(canvas: ph.Canvas) -> ph.Canvas:
    # TODO This is still needed for some reason. Let ph dev know.
    black_pixels = np.all(canvas.img == [0, 0, 0, 0], axis=-1)
    transparent_canvas = canvas.copy()
    transparent_canvas[~black_pixels, 3] = 255  # Change alpha to 255
    return transparent_canvas


class keydefaultdict(defaultdict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._miss_count = 0

    def __missing__(self, key):
        self._miss_count += 1

        if self.default_factory is None:
            raise KeyError(key)
        else:
            ret = self[key] = self.default_factory(key)
            return ret

    @property
    def miss_count(self):
        return self._miss_count


class MainWindow:
    def __init__(self, world_adapter: WorldAdapter):
        self.world_adapter = world_adapter
        self.world_adapter.add_renderer(self)

        # DEBUG: Call a function on every draw to check if things are alright.
        self._draw_callback = lambda: None

        self.terrain_map = [[ph.Canvas().load(self.world_adapter.world.map[y][x].terrain.sprite_path_string) for x in
                             range(WORLD_WIDTH)] for y in range(WORLD_HEIGHT)]

        self.rendered_canvas = ph.gridstack(self.terrain_map)
        self.rendered_canvas.name = WINDOW_NAME

        self.base_cell_width = self.terrain_map[0][0].width
        self.base_cell_height = self.terrain_map[0][0].height

        self._sprite_cache = keydefaultdict(lambda k: black_to_transparent(ph.load(k)))

    def on_draw(self, show_window=False):
        for y, row in enumerate(self.terrain_map):
            for x, cnv in enumerate(row):
                with cnv.layer() as layer:
                    layer += self._sprite_cache[self.world_adapter.world.map[y][x].sprite_path_string]
        for player in self.world_adapter.iter_players():
            x, y = player.location.x, player.location.y
            with self.terrain_map[y][x].layer() as layer:
                layer += self._sprite_cache[player.sprite_path_string]

        self.rendered_canvas: ph.Canvas = ph.gridstack(self.terrain_map)
        self.rendered_canvas.name = WINDOW_NAME

        self._draw_callback()

        if show_window:
            self.rendered_canvas.show(40)

    def get_player_view(self, character: Actors.PlayerCharacter) -> str:
        # Need to find top left coordinate
        # Find tile first
        top_left_tile: GameSpace.Space = character.location - (character.fov, character.fov)
        assert top_left_tile.x >= 0 and top_left_tile.y >= 0, "Negative coordinates"

        # Then convert game-coordinates to pixel (x, y, width, height)
        # x = max(top_left_tile.x * self.base_cell_width, 0)
        # y = max(top_left_tile.y * self.base_cell_height, 0)
        # width = ((character.fov * 2) + 1) * self.base_cell_width
        # height = ((character.fov * 2) + 1) * self.base_cell_height
        x1 = min(max(top_left_tile.x, 0), WORLD_WIDTH)
        y1 = min(max(top_left_tile.y, 0), WORLD_HEIGHT)
        width = height = ((character.fov * 2) + 1)
        x2 = min(max(top_left_tile.x + width, 0), WORLD_WIDTH)
        y2 = min(max(top_left_tile.y + height, 0), WORLD_HEIGHT)

        # Debugging
        LOG.info(f"Getting PlayerView: {character.name} {x1} {y1} {x2} {y2}")
        view = [self.terrain_map[i][x1:x2] for i in range(y1, y2)]
        img = ph.gridstack(view)
        img_path = f'./PlayerViews/{character.name}_screenshot.png'
        img.save(img_path)
        return str(img_path)

    def get_world_view(self) -> str:
        img_path = f"./PlayerViews/world_{int(time.time())}.png"
        self.rendered_canvas.save(img_path)
        return str(img_path)


def update_display(display: MainWindow, show_window=False):
    while True:
        display.on_draw(show_window=show_window)