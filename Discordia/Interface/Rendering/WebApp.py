"""
Serves the live world map over HTTP. Replaces the old desktop preview window: same WindowRenderer,
different output device.

The map is split into the half that never changes and the half that does. The static half (terrain,
towns, wilds) goes out once as /background.png and is cached forever; only the actors are polled, as
a few hundred bytes of JSON. The browser draws them on top, which keeps the server out of the
per-frame PNG encode entirely.
"""

from __future__ import annotations

import json
import logging
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from Discordia import SPRITE_FOLDER
from Discordia.GameLogic.Actors import PlayerCharacter
from Discordia.Interface.Rendering.DesktopApp import WindowRenderer

LOG = logging.getLogger("Discordia.Interface.WebApp")

CLIENT_JS = Path(__file__).with_name("client.js")
INDEX_HTML = Path(__file__).with_name("index.html")
SPRITES_ROOT = SPRITE_FOLDER.resolve()


def _sprite_url(sprite_path: str) -> str:
    """Map an on-disk sprite path to the URL the client fetches it from."""
    return "/sprites/" + Path(sprite_path).resolve().relative_to(SPRITES_ROOT).as_posix()


def _read_sprite(rel: str) -> bytes | None:
    """Sprite bytes for a client-supplied path, or None if it escapes the sprite folder."""
    path = (SPRITES_ROOT / unquote(rel)).resolve()
    if not path.is_relative_to(SPRITES_ROOT) or path.suffix.lower() != ".png" or not path.is_file():
        return None
    return path.read_bytes()


def _world_json(renderer: WindowRenderer) -> bytes:
    """Everything that is fixed at world generation. Fetched once, then cached by the browser."""
    world = renderer.world_adapter.world
    return json.dumps(
        {
            "name": world.name,
            "seed": world.seed,
            "width": world.width,
            "height": world.height,
            "tile": renderer.base_cell_width,
            "terrain": [[space.terrain.name for space in row] for row in world.map],
            "towns": [
                {"x": t.x, "y": t.y, "name": t.name, "population": t.population,
                 "industry": t.industry.name, "sprite": _sprite_url(t.sprite_path_string)}
                for t in world.towns
            ],
            "wilds": [{"x": w.x, "y": w.y, "name": w.name} for w in world.wilds],
        }
    ).encode()


def _actors_json(renderer: WindowRenderer) -> bytes:
    adapter = renderer.world_adapter
    # This runs on an HTTP thread while the bot loop mutates the world. list() snapshots each
    # collection in one step, and location is read once so a death mid-poll can't leave it None.
    # ponytail: no lock; a stale hp/position for one poll is fine. Lock if torn reads ever matter.
    tagged = [("npc", n) for n in list(adapter.world.npcs)] + [("player", p) for p in list(adapter.iter_players())]
    actors = []
    for kind, actor in tagged:
        loc = actor.location
        if loc is None:  # dead, or registered but not yet spawned
            continue
        actors.append(
            {
                # Identity has to survive a poll so the client can slide the sprite instead of respawning it,
                # and generated names are not unique. The object address is, for as long as the actor lives.
                "id": f"{kind}:{id(actor)}",
                "kind": kind,
                "name": actor.name,
                "x": loc.x,
                "y": loc.y,
                "sprite": _sprite_url(actor.sprite_path_string),
                "hp": actor.hit_points,
                "hp_max": actor.hit_points_max,
                **({"level": actor.level, "class": actor.player_class.name} if isinstance(actor, PlayerCharacter) else {}),
            }
        )
    return json.dumps({"actors": actors}).encode()


class _Handler(BaseHTTPRequestHandler):
    def __init__(self, renderer: WindowRenderer, *args, **kwargs):
        self.renderer = renderer
        super().__init__(*args, **kwargs)  # this actually serves the request, so set attrs first

    def do_GET(self):
        path = urlsplit(self.path).path
        # A regenerated world reuses these URLs, so tag the static responses with its seed.
        etag = f'"{self.renderer.world_adapter.world.seed}"'

        if path == "/background.png":
            self._send(self.renderer.background_png(), "image/png", etag=etag)
        elif path == "/world.json":
            self._send(_world_json(self.renderer), "application/json", etag=etag)
        elif path == "/actors.json":
            self._send(_actors_json(self.renderer), "application/json")
        elif path == "/client.js":
            self._send(CLIENT_JS.read_bytes(), "text/javascript; charset=utf-8")
        elif path.startswith("/sprites/"):
            body = _read_sprite(path[len("/sprites/"):])
            if body is None:
                self.send_error(404)
            else:
                self._send(body, "image/png", etag=etag)
        elif path.startswith("/world.png"):
            # The whole map composited server-side. Nothing needs it any more; handy for a screenshot.
            self._send(self.renderer.render_png(), "image/png")
        elif path == "/":
            self._send(INDEX_HTML.read_bytes(), "text/html; charset=utf-8")
        else:
            self.send_error(404)

    def _send(self, body: bytes, ctype: str, etag: str | None = None):
        if etag and self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if etag:
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "no-cache")  # cache it, but revalidate against the seed
        else:
            self.send_header("Cache-Control", "no-store")  # actors move every tick
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        LOG.debug(format, *args)


def serve(renderer: WindowRenderer, port: int, host: str = "127.0.0.1"):
    """Blocks forever. Run me in a daemon thread."""
    # ponytail: client polls actors every 2s. Swap in SSE if that feels laggy.
    server = ThreadingHTTPServer((host, port), partial(_Handler, renderer))
    LOG.info("World map: http://%s:%d", host, port)
    server.serve_forever()
