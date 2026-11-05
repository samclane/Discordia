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

import asyncio
import gzip
import html
import json
import logging
import re
import time
import zlib
from dataclasses import replace
from http.cookies import CookieError, SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, unquote

from aiohttp import web

from Discordia import SPRITE_FOLDER, VERSION
from Discordia.GameLogic import Events, GameSpace
from Discordia.GameLogic.Actors import ACHIEVEMENTS, EXPERIENCE_PER_LEVEL, Fixer, Medic, PlayerCharacter, Scavenger, Scout, Soldier, WandererClass
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
# Leaflet 1.9.4, vendored (BSD-2, leaflet.LICENSE): the map's pan, zoom and tiles. Bump the tag with the files.
LEAFLET = {name: Path(__file__).with_name(name) for name in ("leaflet.js", "leaflet.css")}
LEAFLET_ETAG = '"leaflet-1.9.4"'
INDEX_HTML = Path(__file__).with_name("index.html")
SITE_HTML = Path(__file__).with_name("site.html")  # header and footer around every page but the map
HOME_HTML = Path(__file__).with_name("home.html")
ME_HTML = Path(__file__).with_name("me.html")
ADMIN_HTML = Path(__file__).with_name("admin.html")  # the bot owner's dashboard
SPRITES_ROOT = SPRITE_FOLDER.resolve()
# Bump when the sprites change, or browsers keep revalidating the old art against an unchanged ETag.
ART_VERSION = 8
ADMIN_ROUTE = re.compile(r"/admin/(\d+)")  # a Discord server's settings, for its admins
ORDER_SECONDS = 30  # how long /act waits for a tick
DISCORD_SECONDS = 10  # how long the admin pages wait on Discord
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
      <li><span>Run <code>{{{{COMMAND}}}}</code> in Discord again.</span></li>
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
    """What the client needs to say what's under the cursor: terrain names, which squares are wilds,
    extraction points or caches, and who lives in its towns."""
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
            "towns": [  # who's in the doorway, for the info panel
                {"x": space.x, "y": space.y, "residents": space.residents}
                for row in rows
                for space in row
                if isinstance(space, GameSpace.Town)
            ],
        }
    ).encode()


def _actors_json(renderer: WindowRenderer) -> bytes:
    adapter = renderer.world_adapter
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
    """me.html's placeholders, for one character."""
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
    # Earned only: the rest stay a surprise here, /achievements lists them.
    achievements = "".join(
        f'<li><span class="slot">{icon}</span><span class="name">{html.escape(title)}: {html.escape(how)}</span></li>'
        for key, (icon, title, how, _) in ACHIEVEMENTS.items()
        if key in character.achievements
    )
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
        "HIDEOUT_IMG": Markup(
            '<img class="px hideout" src="/hideout.png" alt="Your hideout" style="max-width: 100%">'
            if character.hideout_level
            else ""
        ),
        "DEATH_NOTE": death_note,
        "EQUIPMENT": Markup(equipment),
        "NEWS": Markup(_news_rows(news)),
        "ACHIEVEMENTS": Markup(
            achievements
            or '<li class="empty-slot"><span class="name">None yet. They show here once earned.</span></li>'
        ),
        "EARNED": sum(key in character.achievements for key in ACHIEVEMENTS),
        "ACHIEVEMENTS_TOTAL": len(ACHIEVEMENTS),
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


def _dashboard_json(adapter, since: int) -> bytes:
    """The owner's dashboard: the ticks after `since`, today's stats, and every player."""
    world, stats = adapter.world, adapter.world.stats

    def where(loc) -> str:
        if loc is None:
            return "off the map"
        if isinstance(loc, GameSpace.Town):
            return loc.name
        if isinstance(loc, GameSpace.Wilds):
            return f"wilds L{loc.level} ({loc.x}, {loc.y})"
        return f"road ({loc.x}, {loc.y})"

    players = [
        {
            "name": p.name,
            "class": p.player_class.name,
            "level": p.level,
            "where": where(p.location),
            "hp": round(p.hit_points),
            "deaths": p.deaths,
            "kills": p.kills,
            "worth": p.currency + p.stash_currency,
            "hideout": p.hideout_level,
        }
        for p in list(world.players)
    ]
    return json.dumps(
        {
            "world": world.name,
            "started": adapter.started,
            "tick_seconds": adapter.tick_seconds,
            # Since the last digest (midnight UTC, or the restart since).
            "today": {
                "since": stats.since,
                "active": len(stats.active_players),
                "kills": stats.kills,
                "deaths": sum(list(stats.deaths_by_level.values())),
            },
            "samples": adapter.samples(since),
            "players": players,
        },
        separators=(",", ":"),
    ).encode()


class _Site:
    """The site's routes. They run on the bot's event loop, between ticks, so they read the world as the game
    left it; only the Pillow renders go to a thread, where they'd otherwise hold up the tick."""

    def __init__(self, renderer: WindowRenderer):
        self.renderer = renderer
        self.adapter = renderer.world_adapter

    @web.middleware
    async def gate(self, request: web.Request, handler):
        """The site is public; the map and everything it fetches are for players. Sprites are the game's public
        art, and the site wears some. Posts check for themselves: /act answers in JSON."""
        path = request.path
        if (
            request.method != "POST"
            and path not in ("/", "/login", "/invite")
            and not path.startswith("/sprites/")
            and self._member_id(request) is None
        ):
            if path in ("/map", "/me", "/admin") or ADMIN_ROUTE.fullmatch(path):  # pages send you to how to get in; data just refuses
                return _redirect("/#join")
            raise web.HTTPUnauthorized()
        return await handler(request)

    def routes(self) -> list:
        return [
            web.get(r"/chunk/{cx:\d+}/{cy:\d+}.{ext:png|mini\.png|json}", self.chunk),  # mini: the zoomed-out overview
            web.get("/world.json", self.world_json),
            web.get("/explored.json", self.explored_json),
            web.get("/actors.json", self.actors_json),
            web.get("/me.json", self.me_json),
            web.get("/hideout.png", self.hideout),
            web.get("/login", self.login_page),
            web.post("/login", self.login),
            web.post("/logout", self.logout),
            web.get("/invite", self.invite),
            web.get("/client.js", self.client_js),
            web.get("/leaflet.js", self.leaflet),
            web.get("/leaflet.css", self.leaflet),
            web.get("/sprites/{rel:.*}", self.sprite),
            web.get("/map", self.map),
            web.get("/me", self.me),
            web.get("/admin", self.dashboard),
            web.get("/admin.json", self.dashboard_json),
            web.get(r"/admin/{guild:\d+}", self.admin),
            web.post(r"/admin/{guild:\d+}", self.save_admin),
            web.post("/act", self.act),
            web.get("/", self.home),
        ]

    def _etag(self) -> str:
        # A regenerated world or new art reuses these URLs, so tag the static responses with both.
        return f'"{self.adapter.world.seed}-{ART_VERSION}"'

    async def chunk(self, request: web.Request) -> web.Response:
        cx, cy, ext = int(request.match_info["cx"]), int(request.match_info["cy"]), request.match_info["ext"]
        rows = self.adapter.world.loaded_chunk(cx, cy)
        if rows is None:
            raise web.HTTPNotFound()  # unexplored
        if ext.endswith("png"):
            png = await asyncio.to_thread(self.renderer.chunk_png, cx, cy, mini=ext == "mini.png")
            return _send(request, png or b"", "image/png", etag=self._etag())
        return _send(request, _chunk_json(rows), "application/json", etag=self._etag())

    async def world_json(self, request: web.Request) -> web.Response:
        return _send(request, _world_json(self.renderer), "application/json", etag=self._etag())

    async def explored_json(self, request: web.Request) -> web.Response:
        # Towns live in chunks, so the chunk count says whether anything changed since the last poll.
        world = self.adapter.world
        explored_etag = f'"{world.seed}-{len(world.loaded_chunks())}"'
        return _send(request, _explored_json(self.renderer), "application/json", etag=explored_etag)

    async def actors_json(self, request: web.Request) -> web.Response:
        # Actors only move on a tick, and the client polls faster than that: most polls can be a 304.
        body = _actors_json(self.renderer)
        return _send(request, body, "application/json", etag=f'"{zlib.crc32(body):x}"')

    async def me_json(self, request: web.Request) -> web.Response:
        try:
            character = self.adapter.get_player(self._member_id(request))
        except NotRegisteredException:  # logged in, but no character (yet, or anymore)
            return _send(request, b'{"error": "no character"}', "application/json", status=404)
        return _send(request, _me_json(character, self.adapter.news(character)), "application/json")

    async def hideout(self, request: web.Request) -> web.Response:
        character = self._character(request)
        png = await asyncio.to_thread(self.renderer.hideout_png, character) if character else None
        if png is None:
            raise web.HTTPNotFound()  # no character, or no hideout yet
        return _send(request, png, "image/png")

    async def login_page(self, request: web.Request) -> web.Response:
        token, after = request.query.get("t", ""), request.query.get("next", "")
        if not ADMIN_ROUTE.fullmatch(after):
            goal, button = f"the map of {self.adapter.world.name}", "Enter the map"
        elif self._member_id(request) is None:
            goal, button = "this server's settings", "Open server settings"
        else:  # already logged in: no need to spend the link, the settings page asks Discord itself
            return _redirect(after)
        page = self._page(request, "Log in · Discordia", LOGIN_BODY, TOKEN=token, NEXT=after, GOAL=goal, BUTTON=button)
        return _send(request, page, "text/html; charset=utf-8")

    async def login(self, request: web.Request) -> web.Response:
        form = parse_qs(await _body(request))
        session = self.adapter.web_logins.redeem(form.get("t", [""])[0])
        after = form.get("next", [""])[0]
        if session is None:
            command = "/settings" if ADMIN_ROUTE.fullmatch(after) else "/weblogin"
            page = self._page(request, "Link expired · Discordia", SPENT_BODY, COMMAND=command)
            return _send(request, page, "text/html; charset=utf-8", status=403)
        # Only to a page of ours that's known: anything else would make the login link an open redirect.
        # Secure: browsers still let localhost set it over plain HTTP, so a local run logs in too.
        return _redirect(
            after if ADMIN_ROUTE.fullmatch(after) else "/map",
            **{"Set-Cookie": f"session={session}; Path=/; Max-Age={SESSION_SECONDS}; HttpOnly; Secure; SameSite=Lax"},
        )

    async def logout(self, request: web.Request) -> web.Response:
        session = _session(request)
        if session:
            self.adapter.web_logins.end(session)
        return _redirect("/", **{"Set-Cookie": "session=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax"})

    async def invite(self, request: web.Request) -> web.Response:
        if self.adapter.invite_url is None:
            raise web.HTTPServiceUnavailable(text="The bot isn't running right now.")
        return _redirect(self.adapter.invite_url)  # Discord's own page takes it from here: pick a server, approve

    async def client_js(self, request: web.Request) -> web.Response:
        return _send(request, CLIENT_JS.read_bytes(), "text/javascript; charset=utf-8")

    async def leaflet(self, request: web.Request) -> web.Response:
        path = LEAFLET[request.path.removeprefix("/")]
        ctype = "text/css" if path.suffix == ".css" else "text/javascript"
        return _send(request, path.read_bytes(), f"{ctype}; charset=utf-8", etag=LEAFLET_ETAG)

    async def sprite(self, request: web.Request) -> web.Response:
        body = _read_sprite(request.match_info["rel"])
        if body is None:
            raise web.HTTPNotFound()
        return _send(request, body, "image/png", etag=self._etag())

    async def map(self, request: web.Request) -> web.Response:
        return _send(request, INDEX_HTML.read_bytes(), "text/html; charset=utf-8")

    async def me(self, request: web.Request) -> web.Response:
        character = self._character(request)
        if character is None:  # logged in, but nothing to show: the home page says how to make one
            return _redirect("/#join")
        page = self._page(request, f"{character.name} · Discordia", ME_HTML.read_text(encoding="utf-8"), **_sheet(character, self.adapter))
        return _send(request, page, "text/html; charset=utf-8")

    async def dashboard(self, request: web.Request) -> web.Response:
        await self._owner(request)
        page = self._page(request, "Dashboard · Discordia", ADMIN_HTML.read_text(encoding="utf-8"))
        return _send(request, page, "text/html; charset=utf-8")

    async def dashboard_json(self, request: web.Request) -> web.Response:
        await self._owner(request)
        since = request.query.get("since", "")
        body = _dashboard_json(self.adapter, int(since) if since.lstrip("-").isdigit() else -1)
        return _send(request, body, "application/json")

    async def admin(self, request: web.Request) -> web.Response:
        guild_id = int(request.match_info["guild"])
        guild = await self._admin_guild(request, guild_id)
        page = self._admin_page(request, guild_id, guild, "saved" in request.query)
        return _send(request, page, "text/html; charset=utf-8")

    async def act(self, request: web.Request) -> web.Response:
        """Play from the browser: one order, queued like a slash command's, answered after its tick."""

        def reply(status: int, text: str) -> web.Response:
            return _send(request, json.dumps({"text": text}).encode(), "application/json", status=status)

        character = self._character(request)
        # JSON only: a form on another site can post here, but it can't send JSON without asking first.
        if "application/json" not in request.headers.get("Content-Type", ""):
            raise web.HTTPUnsupportedMediaType()
        body = await _body(request)
        if character is None:
            return reply(401, "Log in first: /weblogin in Discord.")
        try:
            order = json.loads(body)
            what = order["action"]
        except (ValueError, TypeError, KeyError):
            return reply(400, "That isn't an order.")
        adapter = self.adapter
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
            # Waits for the tick. A timeout cancels the order too, so it can't still happen after the 504.
            result = await asyncio.wait_for(adapter.place_order(character, action), ORDER_SECONDS)
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
        return reply(200, text)

    async def _admin_guild(self, request: web.Request, guild_id: int):
        """(server name, channels) if the logged-in member may manage that server. Otherwise raises the answer."""
        member_id = self._member_id(request)
        if member_id is None:
            raise web.HTTPUnauthorized(text="Log in first.")
        lookup = self.adapter.guild_for_admin
        if lookup is None:
            raise web.HTTPServiceUnavailable(text="The bot isn't running right now.")
        try:
            guild = await asyncio.wait_for(lookup(member_id, guild_id), DISCORD_SECONDS)
        except TimeoutError:
            raise web.HTTPGatewayTimeout(text="Discord didn't answer. Try again in a moment.")
        if guild is None:
            raise web.HTTPForbidden(text="You need Manage Server in that Discord server, and the bot has to be in it.")
        return guild

    async def _owner(self, request: web.Request):
        """Raises the answer unless the logged-in member owns the bot."""
        member_id = self._member_id(request)
        if member_id is None:
            raise web.HTTPUnauthorized(text="Log in first.")
        lookup = self.adapter.is_owner
        if lookup is None:
            raise web.HTTPServiceUnavailable(text="The bot isn't running right now.")
        try:
            owner = await asyncio.wait_for(lookup(member_id), DISCORD_SECONDS)
        except TimeoutError:
            raise web.HTTPGatewayTimeout(text="Discord didn't answer. Try again in a moment.")
        if not owner:
            raise web.HTTPForbidden(text="This page is for the bot's owner.")

    def _admin_page(self, request: web.Request, guild_id: int, guild, saved: bool) -> bytes:
        name, channels = guild
        settings = self.adapter.guild_settings.get(guild_id, GuildSettings())
        picked = set(settings.channels)

        def options(chosen):
            return '<option value="">Nowhere</option>' + "".join(
                f'<option value="{channel_id}"{" selected" if channel_id == chosen else ""}>'
                f"#{html.escape(channel_name)}{'' if can_post else ' (the bot may not post here)'}</option>"
                for channel_id, channel_name, can_post in channels
            )

        rows = "".join(
            f'<li><label><input type="checkbox" name="c" value="{channel_id}"{" checked" if channel_id in picked else ""}>'
            f" #{html.escape(channel_name)}</label></li>"
            for channel_id, channel_name, _ in channels
        )
        return self._page(
            request,
            f"{name} settings · Discordia",
            ADMIN_BODY,
            SERVER=name,
            ACTION=f"/admin/{guild_id}",
            CHANNELS=Markup(rows),
            DIGEST=Markup(options(settings.digest_channel)),
            ANNOUNCE=Markup(options(settings.announce_channel)),
            SAVED=Markup('<p class="alert"><b>Saved.</b></p>' if saved else ""),
        )

    async def save_admin(self, request: web.Request) -> web.Response:
        guild_id = int(request.match_info["guild"])
        # Changing a server's settings is the one thing here worth forging: refuse a form posted from another
        # site whatever the cookie does. Browsers that don't send the header still don't send a Lax cookie.
        if request.headers.get("Sec-Fetch-Site", "same-origin") != "same-origin":
            raise web.HTTPForbidden()
        body = await _body(request, max_bytes=64 * 1024)  # a server's worth of channel ids
        if self._member_id(request) is None:
            raise web.HTTPUnauthorized()
        guild = await self._admin_guild(request, guild_id)
        real = {channel[0] for channel in guild[1]}
        form = parse_qs(body)
        picked = [int(c) for c in form.get("c", []) if c.isdigit() and int(c) in real]

        def channel(name):  # one of this server's channels, or None
            value = form.get(name, [""])[0]
            return int(value) if value.isdigit() and int(value) in real else None

        settings = self.adapter.guild_settings
        settings[guild_id] = replace(
            settings.get(guild_id, GuildSettings()),
            channels=picked,
            digest_channel=channel("digest"),
            announce_channel=channel("announce"),
        )
        return _redirect(f"/admin/{guild_id}?saved")

    async def home(self, request: web.Request) -> web.Response:
        member_id = self._member_id(request)
        try:
            name, join = self.adapter.get_player(member_id).name, JOIN_IN
        except NotRegisteredException:  # logged out, or logged in with no character
            name, join = "", JOIN_OUT if member_id is None else JOIN_NO_CHARACTER
        if member_id is None:
            cta = '<a class="btn" href="#join">Join in</a>'
        elif name:
            cta = '<a class="btn" href="/map">Open the map</a><a class="btn ghost" href="/me">Your character</a>'
        else:
            cta = '<a class="btn" href="/map">Open the map</a>'
        page = self._page(
            request,
            f"{self.adapter.world.name} · Discordia",
            HOME_HTML.read_text(encoding="utf-8"),
            CTA=Markup(cta),
            JOIN=Markup(join),
            NAME=name,
            WANDERER_HP=WandererClass().hit_points_max_base,
            SOLDIER_HP=Soldier().hit_points_max_base,
            TOWN_CLASSES=Markup("".join(_class_card(c(), town) for c, town in TOWN_CLASSES)),
        )
        return _send(request, page, "text/html; charset=utf-8")

    def _page(self, request: web.Request, title: str, body: str, **values) -> bytes:
        """site.html around `body`, with its {{PLACEHOLDERS}} filled in. Markup goes in as it is, first; the rest
        is escaped and goes in after, so a name from Discord can't smuggle in a tag or a placeholder."""
        character = self._character(request)
        if self._member_id(request) is None:
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
        values = {"TITLE": title, "ACCOUNT": Markup(account), "WORLD": self.adapter.world.name, "VERSION": VERSION, **values}
        for key, value in sorted(values.items(), key=lambda kv: not isinstance(kv[1], Markup)):
            page = page.replace("{{%s}}" % key, value if isinstance(value, Markup) else html.escape(str(value)))
        return page.encode()

    def _member_id(self, request: web.Request) -> int | None:
        session = _session(request)
        return self.adapter.web_logins.member_id(session) if session else None

    def _character(self, request: web.Request) -> PlayerCharacter | None:
        """The logged-in player's character, or None if logged out or without one."""
        try:
            return self.adapter.get_player(self._member_id(request))
        except NotRegisteredException:
            return None


def _session(request: web.Request) -> str | None:
    try:
        morsel = SimpleCookie(request.headers.get("Cookie", "")).get("session")
    except CookieError:
        return None
    return morsel.value if morsel else None


async def _body(request: web.Request, max_bytes: int = 1024) -> str:
    """The request body. Raises a 400 if it's missing or bigger than `max_bytes`."""
    length = request.headers.get("Content-Length", "")
    if not length.isdigit() or int(length) > max_bytes:  # a token is 43 characters, an order less
        raise web.HTTPBadRequest()
    return (await request.read()).decode(errors="replace")


def _redirect(location: str, **headers) -> web.Response:
    return web.Response(status=303, headers={"Location": location, **headers})


def _send(request: web.Request, body: bytes, ctype: str, etag: str | None = None, status: int = 200) -> web.Response:
    if etag and request.headers.get("If-None-Match") == etag:
        return web.Response(status=304, headers={"ETag": etag})
    headers = {"Content-Type": ctype}
    if not ctype.startswith("image/"):
        headers["Vary"] = "Accept-Encoding"
        if len(body) >= GZIP_MIN_BYTES and "gzip" in request.headers.get("Accept-Encoding", ""):
            body = gzip.compress(body, compresslevel=5)
            headers["Content-Encoding"] = "gzip"
    if etag:
        headers["ETag"] = etag
        headers["Cache-Control"] = "no-cache"  # cache it, but revalidate every time
    else:
        headers["Cache-Control"] = "no-store"
    return web.Response(status=status, body=body, headers=headers)


async def serve(renderer: WindowRenderer, port: int, host: str = "127.0.0.1") -> web.AppRunner:
    """Start serving on the running loop (the bot's) and return; the runner's cleanup() stops it."""
    # ponytail: client polls actors every 2s. Swap in SSE (a web.StreamResponse) if that feels laggy.
    site = _Site(renderer)
    app = web.Application(middlewares=[site.gate])
    app.add_routes(site.routes())
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    LOG.info("World map: http://%s:%d", host, runner.addresses[0][1])
    return runner
