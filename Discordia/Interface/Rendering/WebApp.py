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
import time
import zlib
from dataclasses import replace
from functools import partial
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from Discordia import SPRITE_FOLDER, VERSION
from Discordia.GameLogic import Events, GameSpace
from Discordia.GameLogic.Actors import EXPERIENCE_PER_LEVEL, Fixer, Medic, PlayerCharacter, Scavenger, Scout, Soldier, WandererClass
from Discordia.GameLogic.Items import ArmorAbstract, EquipmentSet
from Discordia.GameLogic.Weapons import Weapon
from Discordia.Interface.Rendering.DesktopApp import WindowRenderer
from Discordia.Interface.WebLogins import SESSION_SECONDS
from Discordia.Interface.WorldAdapter import (
    DIRECTION_NAMES,
    SUPERSEDED,
    GuildSettings,
    NotRegisteredException,
    NotSpawnedException,
    attack_text,
    choose_text,
    error_text,
    move_text,
)

LOG = logging.getLogger("Discordia.Interface.WebApp")

CLIENT_JS = Path(__file__).with_name("client.js")
INDEX_HTML = Path(__file__).with_name("index.html")
SITE_HTML = Path(__file__).with_name("site.html")  # header and footer around every page but the map
HOME_HTML = Path(__file__).with_name("home.html")
ME_HTML = Path(__file__).with_name("me.html")
SPRITES_ROOT = SPRITE_FOLDER.resolve()
# Bump when the sprites change, or browsers keep revalidating the old art against an unchanged ETag.
ART_VERSION = 7
ADMIN_ROUTE = re.compile(r"/admin/(\d+)")  # a Discord server's settings, for its admins
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
    <p class="sub">You're one step from {{{{GOAL}}}}.</p>
    <form method="post" action="/login">
      <input type="hidden" name="t" value="{{{{TOKEN}}}}">
      <input type="hidden" name="next" value="{{{{NEXT}}}}">
      <button class="btn" autofocus>{{{{BUTTON}}}}</button>
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
    <div class="cta"><a class="btn" href="/map">Open the map</a><a class="btn ghost" href="/me">Your character</a></div>"""
ADMIN_BODY = """<section class="sheet settings"><div class="wrap">
    <p class="eyebrow">Server settings</p>
    <h1>{{SERVER}}</h1>
    {{SAVED}}
    <form method="post" action="{{ACTION}}">
      <div class="card">
        <h3>Channels</h3>
        <p class="note">Discordia's commands only work in the channels ticked here, and in their threads.
          Tick none and they work everywhere. <code>/settings</code> works anywhere.</p>
        <ul class="items">{{CHANNELS}}</ul>
      </div>
      <div class="card">
        <h3>Daily digest</h3>
        <p class="note">At midnight UTC: how many played, kills, deaths, and the top five. Only on days something
          happened. The bot needs permission to post in that channel.</p>
        <label>Post it in <select name="digest">{{DIGEST}}</select></label>
      </div>
      <div class="card">
        <h3>Deaths and hauls</h3>
        <p class="note">As they happen: a player from this server dies out past the towns (and where their things
          lie, for anyone to loot), or makes it back with something. At most one message a tick.</p>
        <label>Post them in <select name="announce">{{ANNOUNCE}}</select></label>
      </div>
      <button class="btn">Save</button>
    </form>
  </div></section>"""
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
    """What the client needs to say what's under the cursor: terrain names, and which squares are wilds,
    extraction points or caches."""
    return json.dumps(
        {
            "terrain": [[space.terrain.label for space in row] for row in rows],  # read on hover
            "wilds": [
                {"x": space.x, "y": space.y, "name": space.name}
                for row in rows
                for space in row
                if isinstance(space, GameSpace.Wilds)
            ],
            "places": [
                {"x": space.x, "y": space.y, "name": space.name, "kind": type(space).__name__}
                for row in rows
                for space in row
                if isinstance(space, (GameSpace.Extract, GameSpace.Cache))
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
    for space in adapter.world.live_piles():  # a corpse run's pile: drawn like an actor that never moves
        pile = space.remains
        if pile is None:  # picked up since live_piles looked
            continue
        actors.append(
            {
                "id": f"remains:{space.x},{space.y}",
                "kind": "remains",
                "name": f"{pile.owner.name}'s things",
                "x": space.x,
                "y": space.y,
                "sprite": _sprite_url(str(SPRITES_ROOT / "Structures" / "remains.png")),
                "hp": 0,
                "hp_max": 0,
                "contents": str(pile),
            }
        )
    return json.dumps({"actors": actors}).encode()


# The trades' classes, for the home page: (class, the kind of town that trains it).
TOWN_CLASSES = [(Scavenger, "mining"), (Medic, "farming"), (Scout, "woodworking"), (Fixer, "smithing")]


def _class_card(player_class, town: str) -> str:
    return (
        f'<div class="card class"><img class="px" src="{_sprite_url(player_class.sprite_path)}" alt="">'
        f'<div><h3>{player_class.name} <span class="tag">{player_class.hit_points_max_base} HP</span></h3>'
        f"<p>Trained in {town} towns. {html.escape(player_class.perk)}</p></div></div>"
    )


SLOT_LABELS = {"head": "Head", "chest": "Chest", "legs": "Legs", "feet": "Feet", "main_hand": "Main hand",
               "off_hand": "Off hand"}


def _item_row(label: str, item) -> str:
    if isinstance(item, Weapon):
        stat = f"{item.damage:g} dmg"
    elif isinstance(item, ArmorAbstract):
        stat = f"{item._armor_count:g} armor"  # the rating: armor_count rolls coverage, a hit's worth
    else:
        stat = ""
    return (
        f'<li><span class="slot">{html.escape(label)}</span><span class="name">{html.escape(item.name)}</span>'
        f'<span class="stat-tag">{stat}</span></li>'
    )


def _ago(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} min ago"
    return f"{minutes // 60} h ago" if minutes < 24 * 60 else f"{minutes // (24 * 60)} d ago"


def _news_rows(news: list) -> str:
    now = time.time()
    rows = "".join(
        f'<li><span class="slot">{_ago(now - t)}</span><span class="name">{html.escape(text)}</span></li>'
        for t, text in reversed(news)
    )
    return rows or '<li class="empty-slot"><span class="name">Quiet so far. Nothing has found you yet.</span></li>'


def _sheet(character: PlayerCharacter, adapter) -> dict:
    """me.html's placeholders, for one character. Read off the HTTP thread, like _me_json."""
    loc = character.location
    if loc is None:
        where = "not on the map right now"
    elif isinstance(loc, GameSpace.Town):
        where = f"in {loc.name} ({loc.x}, {loc.y})"
    elif isinstance(loc, GameSpace.Wilds):
        where = f"in the wilds of {loc.name} ({loc.x}, {loc.y})"
    else:
        where = f"on the road at ({loc.x}, {loc.y})"
    equipment = "".join(
        _item_row(SLOT_LABELS[slot], item)
        if type(item) not in EquipmentSet.SLOTS.values()  # the bare base classes are empty slots
        else f'<li class="empty-slot"><span class="slot">{SLOT_LABELS[slot]}</span><span class="name">nothing</span></li>'
        for slot in EquipmentSet.SLOTS
        for item in [getattr(character.equipment_set, slot)]
    )
    inventory = "".join(_item_row(f"#{i}", item) for i, item in enumerate(list(character.inventory)))
    if character.pouch is not None:
        inventory += _item_row("pouch", character.pouch)
    pending = character.pending_event
    alert = (
        f'<p class="alert"><b>Someone is waiting on you.</b> {html.escape(pending.flavor_text)}</p>' if pending else ""
    )
    if not character.deaths:
        death_note = "None yet. Keep it that way."
    elif character.last_death_loss:
        death_note = f"The last one cost you {character.last_death_loss}."
    else:
        death_note = "You had nothing on you to lose last time."
    news = adapter.news(character)
    hp_pct = round(100 * character.hit_points / character.hit_points_max) if character.hit_points_max else 0
    return {
        "SPRITE": _sprite_url(character.sprite_path_string),
        "NAME": character.name,
        "CLASS": character.player_class.name,
        "LEVEL": character.level,
        "NEXT_LEVEL": character.level + 1,
        "WHERE": where,
        "ALERT": Markup(alert),
        "HP": f"{character.hit_points:g}",
        "HP_MAX": character.hit_points_max,
        "HP_PCT": hp_pct,
        "HP_LOW": " low" if hp_pct <= 30 else "",
        "XP_PCT": 100 * (character.experience % EXPERIENCE_PER_LEVEL) // EXPERIENCE_PER_LEVEL,
        "XP_TO_NEXT": character.experience_to_next_level,
        "CURRENCY": f"{character.currency:,}",
        "DEATHS": character.deaths,
        "INCOME": f"{adapter.income_per_hour(character):,}",
        "HIDEOUT_NOTE": adapter.hideout_text(character),
        "DEATH_NOTE": death_note,
        "EQUIPMENT": Markup(equipment),
        "NEWS": Markup(_news_rows(news)),
        "INVENTORY": Markup(
            inventory
            or '<li class="empty-slot"><span class="name">Nothing yet. Stores sell, and raiders drop.</span></li>'
        ),
    }


def _me_json(character: PlayerCharacter, news: list) -> bytes:
    """The logged-in player's own character: what /equipment says, for the web."""
    loc = character.location
    encounter = character.pending_event
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
            "encounter": encounter.flavor_text if isinstance(encounter, Events.EncounterEvent) else None,
            "news": [{"t": t, "text": text} for t, text in reversed(news[-10:])],  # newest first
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
        if path not in ("/", "/login", "/invite") and not path.startswith("/sprites/") and self._member_id() is None:
            if path in ("/map", "/me") or ADMIN_ROUTE.fullmatch(path):  # pages send you to how to get in; data just refuses
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
                character = self.renderer.world_adapter.get_player(self._member_id())
                body = _me_json(character, self.renderer.world_adapter.news(character))
            except NotRegisteredException:  # logged in, but no character (yet, or anymore)
                self._send(b'{"error": "no character"}', "application/json", status=404)
            else:
                self._send(body, "application/json")
        elif path == "/login":
            query = parse_qs(urlsplit(self.path).query)
            token, after = query.get("t", [""])[0], query.get("next", [""])[0]
            if not ADMIN_ROUTE.fullmatch(after):
                goal, button = f"the map of {self.renderer.world_adapter.world.name}", "Enter the map"
            elif self._member_id() is None:
                goal, button = "this server's settings", "Open server settings"
            else:  # already logged in: no need to spend the link, the settings page asks Discord itself
                self._redirect(after)
                return
            page = self._page("Log in · Discordia", LOGIN_BODY, TOKEN=token, NEXT=after, GOAL=goal, BUTTON=button)
            self._send(page, "text/html; charset=utf-8")
        elif path == "/invite":  # Discord's own page takes it from here: pick a server, approve
            invite_url = self.renderer.world_adapter.invite_url
            if invite_url is None:
                self.send_error(503, "The bot isn't running right now.")
            else:
                self._redirect(invite_url)
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
        elif path == "/me":
            character = self._character()
            if character is None:  # logged in, but nothing to show: the home page says how to make one
                self._redirect("/#join")
            else:
                page = self._page(f"{character.name} · Discordia", ME_HTML.read_text(encoding="utf-8"), **_sheet(character, self.renderer.world_adapter))
                self._send(page, "text/html; charset=utf-8")
        elif ADMIN_ROUTE.fullmatch(path):
            guild_id = int(path.rsplit("/", 1)[1])
            guild = self._admin_guild(guild_id)
            if guild is not None:
                saved = "saved" in parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                self._send(self._admin_page(guild_id, guild, saved), "text/html; charset=utf-8")
        elif path == "/":
            self._send(self._home(), "text/html; charset=utf-8")
        else:
            self.send_error(404)

    def do_POST(self):
        path = urlsplit(self.path).path
        if path == "/logout":
            session = self._session()
            if session:
                self.renderer.world_adapter.web_logins.end(session)
            self.send_response(303)
            self.send_header("Location", "/")
            self.send_header("Set-Cookie", "session=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/act":
            self._act()
            return
        if ADMIN_ROUTE.fullmatch(path):
            self._save_admin(int(path.rsplit("/", 1)[1]))
            return
        if path != "/login":
            self.send_error(404)
            return
        body = self._body()
        if body is None:
            return
        form = parse_qs(body)
        session = self.renderer.world_adapter.web_logins.redeem(form.get("t", [""])[0])
        if session is None:
            self._send(self._page("Link expired · Discordia", SPENT_BODY), "text/html; charset=utf-8", status=403)
            return
        after = form.get("next", [""])[0]
        self.send_response(303)
        # Only to a page of ours that's known: anything else would make the login link an open redirect.
        self.send_header("Location", after if ADMIN_ROUTE.fullmatch(after) else "/map")
        # Secure: browsers still let localhost set it over plain HTTP, so a local run logs in too.
        self.send_header(
            "Set-Cookie", f"session={session}; Path=/; Max-Age={SESSION_SECONDS}; HttpOnly; Secure; SameSite=Lax"
        )
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _body(self, max_bytes: int = 1024) -> str | None:
        """The request body, or None (with a 400 sent) if it's missing or bigger than `max_bytes`."""
        length = self.headers.get("Content-Length", "")
        if not length.isdigit() or int(length) > max_bytes:  # a token is 43 characters, an order less
            self.send_error(400)
            return None
        return self.rfile.read(int(length)).decode(errors="replace")

    def _act(self):
        """Play from the browser: one order, queued like a slash command's, answered after its tick."""

        def reply(status: int, text: str):
            self._send(json.dumps({"text": text}).encode(), "application/json", status=status)

        character = self._character()
        # JSON only: a form on another site can post here, but it can't send JSON without asking first.
        if "application/json" not in self.headers.get("Content-Type", ""):
            self.send_error(415)
            return
        body = self._body()
        if body is None:
            return
        if character is None:
            return reply(401, "Log in first: /weblogin in Discord.")
        try:
            order = json.loads(body)
            what = order["action"]
        except (ValueError, TypeError, KeyError):
            return reply(400, "That isn't an order.")
        adapter = self.renderer.world_adapter
        direction, choice = order.get("direction"), order.get("choice")
        if what in ("move", "attack") and direction in DIRECTION_NAMES:
            vector = GameSpace.DIRECTION_VECTORS[direction]
            if what == "move":
                action, say = (lambda: adapter.move_player(character, vector)), (
                    lambda r: move_text(r, DIRECTION_NAMES[direction])
                )
            else:
                action, say = (lambda: adapter.attack(character, vector)), (lambda r: attack_text(character, r))
        elif what == "choose" and choice in Events.EncounterEvent.CHOICES:
            action, say = (lambda: adapter.resolve_encounter(character, choice)), choose_text
        else:
            return reply(400, "That isn't an order.")
        if character.location is None:
            text = error_text(NotSpawnedException())
            if text is None:
                return reply(500, "Something went wrong on the server.")
            return reply(409, text)
        if adapter.place_order is None:
            return reply(503, "The game isn't running right now.")
        try:
            result = adapter.place_order(character, action)  # blocks this thread until the tick
            # Inside the try: an answer that fails to format must still be an answer. A dropped
            # connection makes the browser send the order again.
            text = "You change your mind: a newer order took this one's place." if result is SUPERSEDED else say(result)
        except TimeoutError:
            return reply(504, "No tick came. Try again in a moment.")
        except Exception as exc:
            text = error_text(exc)
            if text is None:
                LOG.exception("Web order %r failed", order)
                return reply(500, "Something went wrong on the server.")
            return reply(409, text)
        reply(200, text)

    def _admin_guild(self, guild_id: int):
        """(server name, channels) if the logged-in member may manage that server. Otherwise answers the
        request itself and returns None."""
        member_id = self._member_id()
        if member_id is None:
            self.send_error(401, "Log in first.")
            return None
        lookup = self.renderer.world_adapter.guild_for_admin
        if lookup is None:
            self.send_error(503, "The bot isn't running right now.")
            return None
        try:
            guild = lookup(member_id, guild_id)
        except TimeoutError:
            self.send_error(504, "Discord didn't answer. Try again in a moment.")
            return None
        if guild is None:
            self.send_error(403, "You need Manage Server in that Discord server, and the bot has to be in it.")
        return guild

    def _admin_page(self, guild_id: int, guild, saved: bool) -> bytes:
        name, channels = guild
        settings = self.renderer.world_adapter.guild_settings.get(guild_id, GuildSettings())
        picked = set(settings.channels)

        def options(chosen):
            return '<option value="">Nowhere</option>' + "".join(
                f'<option value="{channel_id}"{" selected" if channel_id == chosen else ""}>'
                f"#{html.escape(channel_name)}</option>"
                for channel_id, channel_name in channels
            )

        rows = "".join(
            f'<li><label><input type="checkbox" name="c" value="{channel_id}"{" checked" if channel_id in picked else ""}>'
            f" #{html.escape(channel_name)}</label></li>"
            for channel_id, channel_name in channels
        )
        return self._page(
            f"{name} settings · Discordia",
            ADMIN_BODY,
            SERVER=name,
            ACTION=f"/admin/{guild_id}",
            CHANNELS=Markup(rows),
            DIGEST=Markup(options(settings.digest_channel)),
            ANNOUNCE=Markup(options(settings.announce_channel)),
            SAVED=Markup('<p class="alert"><b>Saved.</b></p>' if saved else ""),
        )

    def _save_admin(self, guild_id: int):
        # Changing a server's settings is the one thing here worth forging: refuse a form posted from another
        # site whatever the cookie does. Browsers that don't send the header still don't send a Lax cookie.
        if self.headers.get("Sec-Fetch-Site", "same-origin") != "same-origin":
            self.send_error(403)
            return
        body = self._body(max_bytes=64 * 1024)  # a server's worth of channel ids
        if body is None:
            return
        if self._member_id() is None:
            self.send_error(401)
            return
        guild = self._admin_guild(guild_id)
        if guild is None:
            return
        real = {channel_id for channel_id, _ in guild[1]}
        form = parse_qs(body)
        picked = [int(c) for c in form.get("c", []) if c.isdigit() and int(c) in real]
        def channel(name):  # one of this server's channels, or None
            value = form.get(name, [""])[0]
            return int(value) if value.isdigit() and int(value) in real else None

        settings = self.renderer.world_adapter.guild_settings
        # One assignment, so the bot loop reading it from its thread sees the old settings or the new ones.
        settings[guild_id] = replace(
            settings.get(guild_id, GuildSettings()),
            channels=picked,
            digest_channel=channel("digest"),
            announce_channel=channel("announce"),
        )
        self._redirect(f"/admin/{guild_id}?saved")

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
        elif name:
            cta = '<a class="btn" href="/map">Open the map</a><a class="btn ghost" href="/me">Your character</a>'
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
            TOWN_CLASSES=Markup("".join(_class_card(c(), town) for c, town in TOWN_CLASSES)),
        )

    def _page(self, title: str, body: str, **values) -> bytes:
        """site.html around `body`, with its {{PLACEHOLDERS}} filled in. Markup goes in as it is, first; the rest
        is escaped and goes in after, so a name from Discord can't smuggle in a tag or a placeholder."""
        character = self._character()
        if self._member_id() is None:
            account = '<a class="btn ghost" href="/#join">Log in</a>'
        elif character is None:
            account = '<a class="btn" href="/map">Open the map</a>'
        else:
            account = (
                f'<div class="account"><a class="me-link" href="/me" title="Your character">'
                f'<img class="px" src="{_sprite_url(character.sprite_path_string)}" alt="">'
                f"<span>{html.escape(character.name)}</span></a>"
                '<a class="btn" href="/map">Open the map</a></div>'
            )
        page = SITE_HTML.read_text(encoding="utf-8").replace("{{BODY}}", body)
        values = {"TITLE": title, "ACCOUNT": Markup(account), "WORLD": self.renderer.world_adapter.world.name, "VERSION": VERSION, **values}
        for key, value in sorted(values.items(), key=lambda kv: not isinstance(kv[1], Markup)):
            page = page.replace("{{%s}}" % key, value if isinstance(value, Markup) else html.escape(str(value)))
        return page.encode()

    def _session(self) -> str | None:
        try:
            morsel = SimpleCookie(self.headers.get("Cookie", "")).get("session")
        except CookieError:
            return None
        return morsel.value if morsel else None

    def _member_id(self) -> int | None:
        session = self._session()
        return self.renderer.world_adapter.web_logins.member_id(session) if session else None

    def _character(self) -> PlayerCharacter | None:
        """The logged-in player's character, or None if logged out or without one."""
        try:
            return self.renderer.world_adapter.get_player(self._member_id())
        except NotRegisteredException:
            return None

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
