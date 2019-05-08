"""
Holds classes for the basic window and rendering surface for a Desktop view. Image rendering should be independent.
Inspired by PyOverheadGame's architecture: https://github.com/albertz/PyOverheadGame/blob/master/game/app.py
"""
from __future__ import annotations

import collections
import logging
import time
from pathlib import Path

import arcade

from Discordia.ConfigParser import DISPLAY_WIDTH, DISPLAY_HEIGHT, WORLD_NAME, DISPLAY_SCROLL_SPEED
from Discordia.GameLogic import Actors, GameSpace

LOG = logging.getLogger("Discordia.Interface.DesktopApp")


class FPSCounter:
    """Taken from http://arcade.academy/examples/stress_test_collision.html"""

    def __init__(self):
        self.time = time.perf_counter()
        self.frame_times = collections.deque(maxlen=60)

    def tick(self):
        t1 = time.perf_counter()
        dt = t1 - self.time
        self.time = t1
        self.frame_times.append(dt)

    def get_fps(self):
        total_time = sum(self.frame_times)
        if total_time == 0:
            return 0
        else:
            return len(self.frame_times) / sum(self.frame_times)


class MainWindow(arcade.Window):
    def __init__(self, world_adapter: WorldAdapter, width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT):
        super().__init__(width=width, height=height, title=f"Discordia: {WORLD_NAME}")

        self.world_adapter = world_adapter
        self.world_adapter.add_renderer(self)

        self.terrain_list = arcade.SpriteList()
        self.town_list = arcade.SpriteList()
        self.wilds_list = arcade.SpriteList()

        # Set the viewport boundaries
        self.view_left = 0
        self.view_left_change = 0
        self.view_bottom = 0
        self.view_bottom_change = 0

        self.fps = FPSCounter()

        self._draw_callback = lambda: None

        # Statically build world sprites
        for space in self.world_adapter.iter_spaces():
            sprite = arcade.Sprite(space.terrain.sprite_path)
            sprite.left = space.x * sprite.width
            sprite.bottom = space.y * sprite.height
            self.terrain_list.append(sprite)

            if self.world_adapter.is_town(space):
                sprite = arcade.Sprite(space.sprite_path)
                sprite.left = space.x * sprite.width
                sprite.bottom = space.y * sprite.height
                self.town_list.append(sprite)

            elif self.world_adapter.is_wilds(space):
                sprite = arcade.Sprite(space.sprite_path)
                sprite.left = space.x * sprite.width
                sprite.bottom = space.y * sprite.height
                self.wilds_list.append(sprite)

            # TODO Finish drawing static content.
        self.base_cell_width = self.terrain_list[0].width
        self.base_cell_height = self.terrain_list[0].height

    def on_draw(self):
        arcade.start_render()

        # Draw static content
        self.terrain_list.draw()
        self.town_list.draw()
        self.wilds_list.draw()

        self._draw_callback()

        for player in self.world_adapter.iter_players():
            sprite = arcade.Sprite(player.sprite_path)
            sprite.left = player.location.x * sprite.width
            sprite.bottom = player.location.y * sprite.height
            sprite.draw()

        # Calculate FPS
        fps = self.fps.get_fps()
        output = f"FPS: {fps:3.0f}"
        arcade.draw_text(output, self.view_left + 10, self.view_bottom + 10, arcade.color.BLACK, 16)
        self.fps.tick()

        arcade.set_viewport(self.view_left,
                            DISPLAY_WIDTH + self.view_left,
                            self.view_bottom,
                            DISPLAY_HEIGHT + self.view_bottom)

    def on_key_press(self, symbol: int, modifiers: int):
        # Track if we need to change the viewport
        if symbol == arcade.key.UP:
            self.view_bottom_change = DISPLAY_SCROLL_SPEED
        if symbol == arcade.key.DOWN:
            self.view_bottom_change = -DISPLAY_SCROLL_SPEED
        if symbol == arcade.key.LEFT:
            self.view_left_change = -DISPLAY_SCROLL_SPEED
        if symbol == arcade.key.RIGHT:
            self.view_left_change = DISPLAY_SCROLL_SPEED
        if symbol == arcade.key.S:
            player: Actors.PlayerCharacter = next(self.world_adapter.iter_players())
            if player is not None:
                self.get_player_view(player)
            else:
                raise Exception("Player is None")

    def on_key_release(self, symbol: int, modifiers: int):
        if symbol == arcade.key.UP or symbol == arcade.key.DOWN:
            self.view_bottom_change = 0
        if symbol == arcade.key.LEFT or symbol == arcade.key.RIGHT:
            self.view_left_change = 0

    def update(self, delta_time: float):
        self.view_bottom += self.view_bottom_change
        self.view_left += self.view_left_change
        if self.view_left_change != 0 or self.view_bottom_change != 0:
            arcade.set_viewport(self.view_left,
                                DISPLAY_WIDTH + self.view_left,
                                self.view_bottom,
                                DISPLAY_HEIGHT + self.view_bottom)

    def get_player_view(self, character: Actors.PlayerCharacter) -> str:
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
        player_view = arcade.get_image(x, y, width, height)
        img_path = Path(f'./PlayerViews/{character.name}_screenshot.png')
        player_view.save(img_path, 'PNG')
        return str(img_path)
