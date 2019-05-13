"""
Holds classes for the basic window and rendering surface for a Desktop view. Image rendering should be independent.
Inspired by PyOverheadGame's architecture: https://github.com/albertz/PyOverheadGame/blob/master/game/app.py

"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np  # TODO Factor this out
import pixelhouse as ph

from Discordia.ConfigParser import WORLD_HEIGHT, WORLD_WIDTH
from Discordia.GameLogic import Actors, GameSpace

LOG = logging.getLogger("Discordia.Interface.DesktopApp")
WINDOW_NAME = "Discordia"


def black_to_transparent(canvas: ph.Canvas) -> ph.Canvas:
    # TODO Refactor this out
    black_pixels = np.all(canvas.img == [0, 0, 0, 0], axis=-1)
    transparent_canvas = canvas.copy()
    transparent_canvas[~black_pixels, 3] = 255  # Change alpha to 255
    return transparent_canvas


class MainWindow:
    def __init__(self, world_adapter: WorldAdapter):
        self.world_adapter = world_adapter
        self.world_adapter.add_renderer(self)

        self._draw_callback = lambda: None

        self.canvas_map = [[ph.Canvas().load(self.world_adapter.world.map[y][x].terrain.sprite_path_string) for y in
                            range(WORLD_HEIGHT)] for x in range(WORLD_WIDTH)]

        self.rendered_canvas = ph.gridstack(self.canvas_map)
        self.rendered_canvas.name = WINDOW_NAME

        # TODO Finish drawing static content.
        self.base_cell_width = self.canvas_map[0][0].width
        self.base_cell_height = self.canvas_map[0][0].height

    def on_draw(self):
        for y, row in enumerate(self.canvas_map):
            for x, cnv in enumerate(row):
                with cnv.layer() as layer:
                    layer += black_to_transparent(ph.load(self.world_adapter.world.map[y][x].sprite_path_string))
        for player in self.world_adapter.iter_players():
            x, y = player.location.x, player.location.y
            with self.canvas_map[y][x].layer() as layer:
                layer += black_to_transparent(ph.load(player.sprite_path_string))

        self.rendered_canvas = ph.gridstack(self.canvas_map)
        self.rendered_canvas.name = WINDOW_NAME

        self._draw_callback()

        self.rendered_canvas.show(1)

    def get_player_view(self, character: Actors.PlayerCharacter) -> str:
        # Should probably render each view from scratch, so we dont' have to deal with pixel -> grid conversion.
        # TODO

        # Need to find top left (x,y) of pixel in fov
        # Find tile first
        top_left_tile: GameSpace.Space = character.location - (character.fov, character.fov)

        # Then convert game-coordinates to pixel (x, y, width, height)
        x = max(top_left_tile.x * self.base_cell_width, 0)
        y = max(top_left_tile.y * self.base_cell_height, 0)
        width = ((character.fov * 2) + 1) * self.base_cell_width
        height = ((character.fov * 2) + 1) * self.base_cell_height

        # Debugging
        LOG.info(f"Getting PlayerView: {character.name} {x} {y} {width} {height}")
        # self._draw_callback = lambda: arcade.draw_rectangle_outline(x + width / 2, y + height / 2, width, height,
        #                                                            arcade.color.BLACK)

        # Take and save image
        # player_view = arcade.get_image(x, y, width, height)
        esp_path = Path(f'./PlayerViews/{character.name}_screenshot.eps')
        self.postscript(file=esp_path, colormode='color')
        img = Image.open(esp_path)  # TODO GhostScript isn't installed; can't open file. OSError.
        img_path = f'./PlayerViews/{character.name}_screenshot.png'
        img.save(img_path, 'PNG')
        # ImageGrab.grab((x, y, width, height)).save(img_path) # TODO doesn't select canvas
        # player_view.save(img_path, 'PNG')
        return str(img_path)


def update_display(display: MainWindow):
    while True:
        display.on_draw()
