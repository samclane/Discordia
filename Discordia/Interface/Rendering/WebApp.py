"""
Serves the live world map over HTTP. Replaces the old desktop preview window: same WindowRenderer,
different output device.

The map is split into the half that never changes and the half that does. The static half (terrain,
towns, wilds) goes out a chunk at a time, as a PNG and a JSON description, and is cached forever; the
browser only asks for the chunks in view. Only the actors are polled, as a few hundred bytes of JSON,
and drawn on top, which keeps the server out of the per-frame PNG encode entirely.

Only explored chunks are served: a chunk nobody has walked into 404s rather than being generated, so
generation stays on the game loop and a visitor panning about can't make the server build the world.

The home page (/) is public. The map (/map) and everything it fetches want the session cookie that a
/weblogin link gives (see WebLogins).
"""

from __future__ import annotations

import gzip
import html
import json
import logging
import re
import zlib
from functools import partial
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from Discordia import SPRITE_FOLDER
from Discordia.GameLogic import GameSpace
from Discordia.GameLogic.Actors import PlayerCharacter, Soldier, WandererClass
from Discordia.GameLogic.Items import EquipmentSet
from Discordia.Interface.Rendering.DesktopApp import WindowRenderer
from Discordia.Interface.WebLogins import SESSION_SECONDS
from Discordia.Interface.WorldAdapter import NotRegisteredException

LOG = logging.getLogger("Discordia.Interface.WebApp")

CLIENT_JS = Path(__file__).with_name("client.js")
INDEX_HTML = Path(__file__).with_name("index.html")
SITE_HTML = Path(__file__).with_name("site.html")  # header and footer around every page but the map
HOME_HTML = Path(__file__).with_name("home.html")
SPRITES_ROOT = SPRITE_FOLDER.resolve()
# Bump when the sprites change, or browsers keep revalidating the old art against an unchanged ETag.
ART_VERSION = 2
CHUNK_ROUTE = re.compile(r"/chunk/(\d+)/(\d+)\.(png|mini\.png|json)")  # mini: the zoomed-out overview
# Text this short isn't worth the CPU, and can come out bigger than it went in.
GZIP_MIN_BYTES = 1024
# The party on top of the one-card pages.
PARTY = """<div class="party" aria-hidden="true">
      <img class="px far" src="/sprites/Structures/wilds_0.png" alt="">
      <img class="px" src="/sprites/Actors/wanderer_class.png" alt="">
      <img class="px" src="/sprites/Actors/soldier_class.png" alt="">
      <img class="px" src="/sprites/Actors/raider_class.png" alt="">
      <img class="px far" src="/sprites/Structures/wilds_3.png" alt="">
    </div>"""
# A button, not a redeem-on-GET: link previews and scanners fetch URLs, and would spend the one use.
LOGIN_BODY = f"""<section class="solo"><div class="card">
    {PARTY}
    <h1>Ready, traveller?</h1>
    <p class="sub">You're one step from the map of {{{{WORLD}}}}.</p>
    <form method="post" action="/login">
      <input type="hidden" name="t" value="{{{{TOKEN}}}}">
      <button class="btn" autofocus>Enter the map</button>
    </form>
    <p class="fine">This link works once. Keep it to yourself.</p>
  </div></section>"""
SPENT_BODY = f"""<section class="solo"><div class="card">
    {PARTY}
    <h1>That link has run out</h1>
    <p class="sub">Login links work once, within 10 minutes of asking for them.</p>
    <ol class="steps">
      <li><span>Run <code>/weblogin</code> in Discord again.</span></li>
      <li><span>Open the new link.</span></li>
    </ol>
  </div></section>"""
# The home page's last section: logged out, logged in, and logged in with no character.
JOIN_OUT = """<p class="intro">A live view of the whole world: every explored chunk and town, every player and raider as
      they move. It's for players, and Discord gets you in: no password.</p>
    <ol class="steps">
      <li><span>In Discord, make a character with <code>/register</code> if you haven't.</span></li>
      <li><span>Run <code>/weblogin</code>. Only you see the reply.</span></li>
      <li><span>Open the link in it. It works once, within 10 minutes.</span></li>
    </ol>"""
JOIN_IN = """<p class="intro">You're logged in as <b>{{NAME}}</b>. The map opens on your character and follows it.</p>
    <a class="btn" href="/map">Open the map</a>"""
JOIN_NO_CHARACTER = """<p class="intro">You're logged in, but have no character to show. Make one with
      <code>/register</code> in Discord, and the map will follow it.</p>
    <a class="btn" href="/map">Open the map</a>"""


class Markup(str):
    """HTML for _Handler._page to put in a page as it is."""


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


def _me_json(character: PlayerCharacter) -> bytes:
    """The logged-in player's own character: what /equipment says, for the web."""
    loc = character.location
    return json.dumps(
        {
            "id": f"player:{id(character)}",  # as in actors.json, so the client can pick itself out
            "name": character.name,
            "sprite": _sprite_url(character.sprite_path_string),
            "level": character.level,
            "class": character.player_class.name,
            "hp": character.hit_points,
            "hp_max": character.hit_points_max,
            "currency": character.currency,
            "xp_to_next": character.experience_to_next_level,
            "location": {"x": loc.x, "y": loc.y} if loc else None,
            "equipment": [
                item.name
                for item in character.equipment_set
                if type(item) not in EquipmentSet.SLOTS.values()  # the bare base classes are empty slots
            ],
            "inventory": [item.name for item in list(character.inventory)],
        }
    ).encode()


class _Handler(BaseHTTPRequestHandler):
    # Keep-alive: a page load is hundreds of chunk requests, and the browser only opens six connections.
    protocol_version = "HTTP/1.1"

    def __init__(self, renderer: WindowRenderer, *args, **kwargs):
        self.renderer = renderer
        super().__init__(*args, **kwargs)  # this actually serves the request, so set attrs first

    def do_GET(self):
        path = urlsplit(self.path).path
        # The site is public; the map and everything it fetches are for players. Sprites are the game's
        # public art, and the site wears some.
        if path not in ("/", "/login") and not path.startswith("/sprites/") and self._member_id() is None:
            if path == "/map":
                self._redirect("/#join")
            else:
                self.send_error(401)
            return
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
        elif path == "/me.json":
            try:
                body = _me_json(self.renderer.world_adapter.get_player(self._member_id()))
            except NotRegisteredException:  # logged in, but no character (yet, or anymore)
                self._send(b'{"error": "no character"}', "application/json", status=404)
            else:
                self._send(body, "application/json")
        elif path == "/login":
            token = parse_qs(urlsplit(self.path).query).get("t", [""])[0]
            self._send(self._page("Log in · Discordia", LOGIN_BODY, TOKEN=token), "text/html; charset=utf-8")
        elif path == "/client.js":
            self._send(CLIENT_JS.read_bytes(), "text/javascript; charset=utf-8")
        elif path.startswith("/sprites/"):
            body = _read_sprite(path[len("/sprites/"):])
            if body is None:
                self.send_error(404)
            else:
                self._send(body, "image/png", etag=etag)
        elif path == "/map":
            self._send(INDEX_HTML.read_bytes(), "text/html; charset=utf-8")
        elif path == "/":
            self._send(self._home(), "text/html; charset=utf-8")
        else:
            self.send_error(404)

    def do_POST(self):
        if urlsplit(self.path).path != "/login":
            self.send_error(404)
            return
        length = self.headers.get("Content-Length", "")
        if not length.isdigit() or int(length) > 1024:  # a token is 43 characters
            self.send_error(400)
            return
        form = parse_qs(self.rfile.read(int(length)).decode(errors="replace"))
        session = self.renderer.world_adapter.web_logins.redeem(form.get("t", [""])[0])
        if session is None:
            self._send(self._page("Link expired · Discordia", SPENT_BODY), "text/html; charset=utf-8", status=403)
            return
        self.send_response(303)
        self.send_header("Location", "/map")
        # Secure: browsers still let localhost set it over plain HTTP, so a local run logs in too.
        self.send_header(
            "Set-Cookie", f"session={session}; Path=/; Max-Age={SESSION_SECONDS}; HttpOnly; Secure; SameSite=Lax"
        )
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _redirect(self, location: str):
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _home(self) -> bytes:
        member_id = self._member_id()
        try:
            name, join = self.renderer.world_adapter.get_player(member_id).name, JOIN_IN
        except NotRegisteredException:  # logged out, or logged in with no character
            name, join = "", JOIN_OUT if member_id is None else JOIN_NO_CHARACTER
        if member_id is None:
            cta = '<a class="btn" href="#join">Join in</a>'
        else:
            cta = '<a class="btn" href="/map">Open the map</a>'
        return self._page(
            f"{self.renderer.world_adapter.world.name} · Discordia",
            HOME_HTML.read_text(encoding="utf-8"),
            CTA=Markup(cta),
            JOIN=Markup(join),
            NAME=name,
            WANDERER_HP=WandererClass().hit_points_max_base,
            SOLDIER_HP=Soldier().hit_points_max_base,
        )

    def _page(self, title: str, body: str, **values) -> bytes:
        """site.html around `body`, with its {{PLACEHOLDERS}} filled in. Markup goes in as it is, first; the rest
        is escaped and goes in after, so a name from Discord can't smuggle in a tag or a placeholder."""
        if self._member_id() is None:
            account = '<a class="btn ghost" href="/#join">Log in</a>'
        else:
            account = '<a class="btn" href="/map">Open the map</a>'
        page = SITE_HTML.read_text(encoding="utf-8").replace("{{BODY}}", body)
        values = {"TITLE": title, "ACCOUNT": Markup(account), "WORLD": self.renderer.world_adapter.world.name, **values}
        for key, value in sorted(values.items(), key=lambda kv: not isinstance(kv[1], Markup)):
            page = page.replace("{{%s}}" % key, value if isinstance(value, Markup) else html.escape(str(value)))
        return page.encode()

    def _member_id(self) -> int | None:
        try:
            morsel = SimpleCookie(self.headers.get("Cookie", "")).get("session")
        except CookieError:
            return None
        return self.renderer.world_adapter.web_logins.member_id(morsel.value) if morsel else None

    def _send(self, body: bytes, ctype: str, etag: str | None = None, status: int = 200):
        if etag and self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.end_headers()
            return
        self.send_response(status)
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
