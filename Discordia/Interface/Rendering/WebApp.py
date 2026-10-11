"""
Serves the live world map over HTTP. Replaces the old desktop preview window: same WindowRenderer,
different output device.

The map is split into the half that never changes and the half that does. The static half (terrain,
towns, wilds) goes out a chunk at a time, as a PNG and a JSON description, and is cached forever; the
browser only asks for the chunks in view. Only the actors are polled, as a few hundred bytes of JSON,
and drawn on top, which keeps the server out of the per-frame PNG encode entirely.

Only explored chunks are served: a chunk nobody has walked into 404s rather than being generated, so
generation stays on the game loop and a visitor panning about can't make the server build the world.
"""

from __future__ import annotations

import gzip
import json
import logging
import re
import zlib
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from Discordia import SPRITE_FOLDER
from Discordia.GameLogic import GameSpace
from Discordia.GameLogic.Actors import PlayerCharacter
from Discordia.Interface.Rendering.DesktopApp import WindowRenderer

LOG = logging.getLogger("Discordia.Interface.WebApp")

CLIENT_JS = Path(__file__).with_name("client.js")
INDEX_HTML = Path(__file__).with_name("index.html")
SPRITES_ROOT = SPRITE_FOLDER.resolve()
# Bump when the sprites change, or browsers keep revalidating the old art against an unchanged ETag.
ART_VERSION = 2
CHUNK_ROUTE = re.compile(r"/chunk/(\d+)/(\d+)\.(png|mini\.png|json)")  # mini: the zoomed-out overview
# Text this short isn't worth the CPU, and can come out bigger than it went in.
GZIP_MIN_BYTES = 1024


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
            "chunk": GameSpace.CHUNK_SIZE,
            "spawn": {"x": world.starting_town.x, "y": world.starting_town.y},
        }
    ).encode()


def _town_json(town: GameSpace.Town) -> dict:
    return {
        "x": town.x,
        "y": town.y,
        "name": town.name,
        "population": town.population,
        "industry": town.industry.name,
        "sprite": _sprite_url(town.sprite_path_string),
    }


def _explored_json(renderer: WindowRenderer) -> bytes:
    """Which chunks exist so far, and the towns in them. Grows as players explore."""
    world = renderer.world_adapter.world
    return json.dumps(
        {
            "chunks": world.loaded_chunks(),
            "towns": [_town_json(t) for t in list(world.towns)],  # list(): the game loop appends
        }
    ).encode()


def _chunk_json(rows: list) -> bytes:
    """What the client needs to say what's under the cursor: terrain names, and which squares are wilds."""
    return json.dumps(
        {
            "terrain": [[space.terrain.name for space in row] for row in rows],
            "wilds": [
                {"x": space.x, "y": space.y, "name": space.name}
                for row in rows
                for space in row
                if isinstance(space, GameSpace.Wilds)
            ],
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
    # Keep-alive: a page load is hundreds of chunk requests, and the browser only opens six connections.
    protocol_version = "HTTP/1.1"

    def __init__(self, renderer: WindowRenderer, *args, **kwargs):
        self.renderer = renderer
        super().__init__(*args, **kwargs)  # this actually serves the request, so set attrs first

    def do_GET(self):
        path = urlsplit(self.path).path
        # A regenerated world or new art reuses these URLs, so tag the static responses with both.
        etag = f'"{self.renderer.world_adapter.world.seed}-{ART_VERSION}"'

        chunk = CHUNK_ROUTE.fullmatch(path)
        if chunk:
            cx, cy, ext = int(chunk[1]), int(chunk[2]), chunk[3]
            rows = self.renderer.world_adapter.world.loaded_chunk(cx, cy)
            if rows is None:
                self.send_error(404)  # unexplored
            elif ext.endswith("png"):
                png = self.renderer.chunk_png(cx, cy, mini=ext == "mini.png")
                self._send(png or b"", "image/png", etag=etag)
            else:
                self._send(_chunk_json(rows), "application/json", etag=etag)
        elif path == "/world.json":
            self._send(_world_json(self.renderer), "application/json", etag=etag)
        elif path == "/explored.json":
            # Towns live in chunks, so the chunk count says whether anything changed since the last poll.
            world = self.renderer.world_adapter.world
            explored_etag = f'"{world.seed}-{len(world.loaded_chunks())}"'
            self._send(_explored_json(self.renderer), "application/json", etag=explored_etag)
        elif path == "/actors.json":
            # Actors only move on a tick, and the client polls faster than that: most polls can be a 304.
            body = _actors_json(self.renderer)
            self._send(body, "application/json", etag=f'"{zlib.crc32(body):x}"')
        elif path == "/client.js":
            self._send(CLIENT_JS.read_bytes(), "text/javascript; charset=utf-8")
        elif path.startswith("/sprites/"):
            body = _read_sprite(path[len("/sprites/"):])
            if body is None:
                self.send_error(404)
            else:
                self._send(body, "image/png", etag=etag)
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
        if not ctype.startswith("image/"):
            self.send_header("Vary", "Accept-Encoding")
            if len(body) >= GZIP_MIN_BYTES and "gzip" in self.headers.get("Accept-Encoding", ""):
                body = gzip.compress(body, compresslevel=5)
                self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        if etag:
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "no-cache")  # cache it, but revalidate every time
        else:
            self.send_header("Cache-Control", "no-store")
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
