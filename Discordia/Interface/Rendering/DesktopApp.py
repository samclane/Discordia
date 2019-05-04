"""
Holds classes for the basic window and rendering surface for a Desktop view. Image rendering should be independent.
Inspired by PyOverheadGame's architecture: https://github.com/albertz/PyOverheadGame/blob/master/game/app.py
"""
import collections
import time

import arcade

from Discordia.ConfigParser import DISPLAY_WIDTH, DISPLAY_HEIGHT, WORLD_NAME, DISPLAY_SCROLL_SPEED
from Discordia.Interface.WorldAdapter import WorldAdapter


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
    def __init__(self, world_adapter: WorldAdapter):
        super().__init__(width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT, title=f"Discordia: {WORLD_NAME}")

        self.world_adapter = world_adapter

        self.terrain_list = arcade.SpriteList(use_spatial_hash=True)
        self.town_list = arcade.SpriteList()
        self.wilds_list = arcade.SpriteList()

        # Set the viewport boundaries
        self.view_left = 0
        self.view_left_change = 0
        self.view_bottom = 0
        self.view_bottom_change = 0

        self.fps = FPSCounter()

        # Statically build world sprites
        for space in self.world_adapter.iter_spaces():
            sprite = arcade.Sprite(space.terrain.sprite_path)
            sprite.right = space.x * sprite.width
            sprite.top = space.y * sprite.height
            self.terrain_list.append(sprite)

            if self.world_adapter.is_town(space):
                sprite = arcade.Sprite(space.sprite_path)
                sprite.right = space.x * sprite.width
                sprite.top = space.y * sprite.height
                self.town_list.append(sprite)

            elif self.world_adapter.is_wilds(space):
                sprite = arcade.Sprite(space.sprite_path)
                sprite.right = space.x * sprite.width
                sprite.top = space.y * sprite.height
                self.wilds_list.append(sprite)

            # TODO Finish drawing static content.

    def on_draw(self):
        arcade.start_render()

        # Draw static content
        self.terrain_list.draw()
        self.town_list.draw()
        self.wilds_list.draw()

        for player in self.world_adapter.iter_players():
            sprite = arcade.Sprite(player.sprite_path)
            sprite.right = player.location.x * sprite.width
            sprite.top = player.location.y * sprite.height
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
        elif symbol == arcade.key.DOWN:
            self.view_bottom_change = -DISPLAY_SCROLL_SPEED
        elif symbol == arcade.key.LEFT:
            self.view_left_change = -DISPLAY_SCROLL_SPEED
        elif symbol == arcade.key.RIGHT:
            self.view_left_change = DISPLAY_SCROLL_SPEED

    def on_key_release(self, symbol: int, modifiers: int):
        self.view_left_change = 0
        self.view_bottom_change = 0

    def update(self, delta_time: float):
        self.view_bottom += self.view_bottom_change
        self.view_left += self.view_left_change
        if self.view_left_change != 0 or self.view_bottom_change != 0:
            arcade.set_viewport(self.view_left,
                                DISPLAY_WIDTH + self.view_left,
                                self.view_bottom,
                                DISPLAY_HEIGHT + self.view_bottom)
