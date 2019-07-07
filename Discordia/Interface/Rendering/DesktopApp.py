"""
Holds classes for the basic window and rendering surface for a Desktop view. Image rendering should be independent.
Inspired by PyOverheadGame's architecture: https://github.com/albertz/PyOverheadGame/blob/master/game/app.py

"""
from __future__ import annotations

import logging
import time
from collections import defaultdict

import cv2
import pixelhouse as ph

from Discordia.GameLogic import Actors, GameSpace

LOG = logging.getLogger("Discordia.Interface.DesktopApp")
WINDOW_NAME = "Discordia"


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

        self.terrain_map = [[ph.Canvas().load(self.world_adapter.world.map[y][x].terrain.sprite_path_string) for x in
                             range(self.world_adapter.width)] for y in range(self.world_adapter.height)]

        self.rendered_canvas = ph.gridstack(self.terrain_map)
        self.rendered_canvas.name = WINDOW_NAME

        self.base_cell_width = self.terrain_map[0][0].width
        self.base_cell_height = self.terrain_map[0][0].height

        self._sprite_cache = keydefaultdict(lambda k: ph.Canvas().load(k))

    def on_draw(self, show_window=False) -> int:
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

        if show_window:
            return self.rendered_canvas.show(1, return_status=True)
        else:
            return -1

    def get_player_view(self, character: Actors.PlayerCharacter) -> str:
        # Need to find top left coordinate
        # Find tile first
        top_left_tile: GameSpace.Space = character.location - (character.fov, character.fov)
        assert top_left_tile.x >= 0 and top_left_tile.y >= 0, "Negative coordinates"

        # Then convert game-coordinates to pixel (x, y, width, height)
        x1 = min(max(top_left_tile.x, 0), self.world_adapter.width)
        y1 = min(max(top_left_tile.y, 0), self.world_adapter.height)
        width = height = ((character.fov * 2) + 1)
        x2 = min(max(top_left_tile.x + width, 0), self.world_adapter.width)
        y2 = min(max(top_left_tile.y + height, 0), self.world_adapter.height)

        # Debugging
        LOG.info(f"Getting PlayerView: {character.name} {x1} {y1} {x2} {y2}")

        view = [self.terrain_map[i][x1:x2] for i in range(y1, y2)]
        img = ph.gridstack(view)
        img_path = f'./Discordia/PlayerViews/{character.name}_screenshot.png'
        img.save(img_path)
        return str(img_path)

    def get_world_view(self, title: str = None) -> str:
        if title is None:
            title = int(time.time())
        img_path = f"./PlayerViews/world_{title}.png"
        self.rendered_canvas.save(img_path)
        return str(img_path)


def update_display(display: MainWindow, show_window=False):
    k = -1
    while k != 27:
        k = display.on_draw(show_window=show_window)
