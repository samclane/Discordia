"""
End-to-end checks for the web map server: every route answers, the static responses revalidate,
and /sprites/ can't be walked out of.
"""

import gzip
import http.client
import io
import json
import html
import re
from types import SimpleNamespace
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from functools import partial

import pytest
from PIL import Image

from Discordia.GameLogic import Actors, GameSpace
from Discordia.Interface.Rendering.DesktopApp import MINI_TILE, WindowRenderer
from Discordia.Interface.Rendering.WebApp import ART_VERSION, _Handler
from Discordia.Interface.WebLogins import LINK_SECONDS, SESSION_SECONDS, WebLogins
from Discordia.Interface.WorldAdapter import WorldAdapter


# Every test server shares these logins, so one session cookie gets a test past the gate on any of them.
LOGINS = WebLogins()
SESSION = LOGINS.redeem(LOGINS.new_link_token(0))
COOKIE = f"session={SESSION}"


def serve(adapter):
    adapter.web_logins = LOGINS
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(_Handler, WindowRenderer(adapter)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture(scope="module")
def base_url():
    # Wide enough for chunks nobody has been to: the spawn is mid-map, so the far end stays unexplored.
    adapter = WorldAdapter(GameSpace.World("Testland", 200, 12, seed=7))
    adapter.world.npcs.append(
        Actors.NPC(parent_world=adapter.world, name="Bandit", hp=10)
    )
    adapter.world.npcs[0].location = adapter.world.space_at(4, 3)

    server = serve(adapter)
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture(autouse=True)
def logged_in():
    """urlopen() sends the session cookie, as a logged-in browser would."""
    opener = urllib.request.build_opener()
    opener.addheaders = [("Cookie", COOKIE)]
    urllib.request.install_opener(opener)
    yield
    urllib.request.install_opener(None)


def get(url):
    with urllib.request.urlopen(url) as response:
        return response.status, response.headers, response.read()


def test_page_and_client_are_served(base_url):
    assert b"<div id=\"viewport\">" in get(base_url + "/map")[2]
    assert b"pollActors" in get(base_url + "/client.js")[2]


def test_explored_chunks_are_pngs(base_url):
    explored = json.loads(get(base_url + "/explored.json")[2])
    cx, cy = explored["chunks"][0]
    status, headers, body = get(base_url + f"/chunk/{cx}/{cy}.png")
    assert status == 200 and body.startswith(b"\x89PNG")
    assert headers["ETag"] == f'"7-{ART_VERSION}"'  # the world seed and the art

    terrain = json.loads(get(base_url + f"/chunk/{cx}/{cy}.json")[2])["terrain"]
    assert len(terrain) == 12 and len(terrain[0]) == GameSpace.CHUNK_SIZE  # clipped to the map


def test_zoomed_out_map_gets_a_small_overview(base_url):
    """A fit view shows every explored chunk: at full size that was 34 KB each, hundreds of them."""
    explored = json.loads(get(base_url + "/explored.json")[2])
    cx, cy = explored["chunks"][0]
    full = get(base_url + f"/chunk/{cx}/{cy}.png")[2]
    misses = WindowRenderer._chunk_mini_png.cache_info().misses
    status, headers, mini = get(base_url + f"/chunk/{cx}/{cy}.mini.png")
    assert status == 200 and headers["Content-Type"] == "image/png"
    assert Image.open(io.BytesIO(mini)).size == (GameSpace.CHUNK_SIZE * MINI_TILE,) * 2
    assert len(mini) * 5 < len(full)

    get(base_url + f"/chunk/{cx}/{cy}.mini.png")  # the next visitor's is cached, not redrawn
    assert WindowRenderer._chunk_mini_png.cache_info().misses == misses + 1


@pytest.mark.parametrize("ext", ["png", "mini.png", "json"])
def test_unexplored_chunks_404_rather_than_generate(base_url, ext):
    """Generation belongs to the game loop; a visitor panning the map mustn't build the world."""
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        get(base_url + f"/chunk/5/0.{ext}")  # the far end of the map, where the spawn search never reached
    assert excinfo.value.code == 404


def test_static_responses_revalidate_to_304(base_url):
    request = urllib.request.Request(base_url + "/world.json", headers={"If-None-Match": f'"7-{ART_VERSION}"'})
    with pytest.raises(urllib.error.HTTPError) as excinfo:  # urllib treats any 3xx it can't follow as an error
        urllib.request.urlopen(request)
    assert excinfo.value.code == 304


def test_world_json_describes_the_generated_map(base_url):
    world = json.loads(get(base_url + "/world.json")[2])
    assert (world["width"], world["height"], world["chunk"]) == (200, 12, GameSpace.CHUNK_SIZE)
    assert {"x", "y"} <= world["spawn"].keys()

    towns = json.loads(get(base_url + "/explored.json")[2])["towns"]
    assert towns and all("x" in town and "name" in town for town in towns)
    assert all(town["sprite"].startswith("/sprites/") for town in towns)


def test_actors_json_carries_the_spawned_npc(base_url):
    actors = json.loads(get(base_url + "/actors.json")[2])["actors"]
    bandit = next(a for a in actors if a["name"] == "Bandit")
    assert (bandit["x"], bandit["y"], bandit["kind"]) == (4, 3, "npc")
    assert bandit["sprite"].startswith("/sprites/") and bandit["sprite"].endswith(".png")
    assert get(base_url + bandit["sprite"])[2].startswith(b"\x89PNG")


def test_one_connection_serves_many_requests(base_url):
    """A page load is hundreds of chunk requests; a connection each queued them six at a time."""
    host, port = base_url.removeprefix("http://").split(":")
    connection = http.client.HTTPConnection(host, int(port))
    sockets = set()
    for path in ["/world.json", "/explored.json", "/actors.json", "/client.js"]:
        connection.request("GET", path, headers={"Cookie": COOKIE})
        response = connection.getresponse()
        response.read()
        assert response.status == 200 and response.version == 11
        sockets.add(id(connection.sock))
    assert len(sockets) == 1 and connection.sock is not None
    connection.close()


def test_text_is_gzipped_for_browsers_that_take_it(base_url):
    explored = json.loads(get(base_url + "/explored.json")[2])
    cx, cy = explored["chunks"][0]
    url = base_url + f"/chunk/{cx}/{cy}.json"
    plain = get(url)[2]
    request = urllib.request.Request(url, headers={"Accept-Encoding": "gzip"})
    with urllib.request.urlopen(request) as response:
        assert response.headers["Content-Encoding"] == "gzip"
        packed = response.read()
    assert gzip.decompress(packed) == plain
    assert len(packed) * 4 < len(plain)  # terrain names repeat; the polled JSON is the same story

    # Too small to bother, and never the PNGs: they're compressed already.
    for small in ["/world.json", f"/chunk/{cx}/{cy}.png"]:
        request = urllib.request.Request(base_url + small, headers={"Accept-Encoding": "gzip"})
        with urllib.request.urlopen(request) as response:
            assert "Content-Encoding" not in response.headers


def test_explored_json_revalidates_until_the_map_grows():
    """The client polls this every 10s; most polls should be an empty 304, not the whole town list."""
    world = GameSpace.World("Growland", 200, 12, seed=7)
    server = serve(WorldAdapter(world))
    url = f"http://127.0.0.1:{server.server_port}/explored.json"
    try:
        etag = get(url)[1]["ETag"]
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(urllib.request.Request(url, headers={"If-None-Match": etag}))
        assert excinfo.value.code == 304

        unexplored = next(cx for cx in range(7) if world.loaded_chunk(cx, 0) is None)
        world.space_at(unexplored * GameSpace.CHUNK_SIZE, 0)  # someone walks somewhere new
        status, headers, body = get(urllib.request.Request(url, headers={"If-None-Match": etag}))
        assert status == 200 and headers["ETag"] != etag
        assert [unexplored, 0] in json.loads(body)["chunks"]
    finally:
        server.shutdown()


def test_actors_json_revalidates_until_someone_moves():
    """The client polls every 2s and the world ticks every 5s: polls between ticks should be an empty 304."""
    world = GameSpace.World("Stillland", 64, 12, seed=7)
    world.npcs.append(Actors.NPC(parent_world=world, name="Bandit", hp=10))
    world.npcs[0].location = world.space_at(4, 3)
    server = serve(WorldAdapter(world))
    url = f"http://127.0.0.1:{server.server_port}/actors.json"
    try:
        etag = get(url)[1]["ETag"]
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(urllib.request.Request(url, headers={"If-None-Match": etag}))
        assert excinfo.value.code == 304

        world.npcs[0].location = world.space_at(5, 3)
        status, headers, body = get(urllib.request.Request(url, headers={"If-None-Match": etag}))
        assert status == 200 and headers["ETag"] != etag
        assert json.loads(body)["actors"][0]["x"] == 5
    finally:
        server.shutdown()


@pytest.mark.parametrize(
    "path",
    [
        "/sprites/../../../../main.py",
        "/sprites/..%2f..%2f..%2f..%2fmain.py",
        "/sprites/Terrain/../../../../setup.py",
        "/sprites/Terrain",  # a directory, not a sprite
        "/nope",
    ],
)
def test_sprites_route_refuses_anything_outside_the_sprite_folder(base_url, path):
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        get(base_url + path)
    assert excinfo.value.code == 404


def test_coastlines_are_drawn_from_the_neighbours():
    """A lone square of water is all kerb, the middle of a lake is all water: same terrain, different tile."""
    renderer = WindowRenderer(WorldAdapter(GameSpace.World("Tiles", 8, 8, seed=7)))
    alone = renderer._terrain_cache["water", 0]
    surrounded = renderer._terrain_cache["water", 0xFF]
    assert alone.tobytes() != surrounded.tobytes()
    assert alone.getpixel((0, 0))[3] == 0  # rounded corner, ground shows through
    assert surrounded.getpixel((0, 0))[3] == 255
    assert renderer._terrain_cache["sand", 0] is None  # bare ground


def test_a_weblogin_link_logs_in_once_and_shows_your_character():
    adapter = WorldAdapter(GameSpace.World("Loginland", 40, 40, seed=7))
    adapter.register_player(42, "Webber")
    server = serve(adapter)
    base = f"http://127.0.0.1:{server.server_port}"
    token = adapter.web_logins.new_link_token(42)
    try:
        # Opening the link only shows a button: a link preview fetching it mustn't spend it.
        assert f'value="{token}"'.encode() in get(f"{base}/login?t={token}")[2]

        conn = http.client.HTTPConnection("127.0.0.1", server.server_port)

        def post(t):
            body = f"t={t}"
            conn.request("POST", "/login", body, {"Content-Type": "application/x-www-form-urlencoded"})
            response = conn.getresponse()
            response.read()
            return response

        response = post(token)
        assert response.status == 303 and response.headers["Location"] == "/map"
        cookie = response.headers["Set-Cookie"]
        assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=Lax" in cookie
        session = cookie.split(";")[0]
        assert post(token).status == 403, "a link works once"

        conn.request("GET", "/me.json", headers={"Cookie": session})
        me = json.loads(conn.getresponse().read())
        assert me["name"] == "Webber" and me["id"].startswith("player:")
        conn.request("GET", "/me.json", headers={"Cookie": COOKIE})  # logged in as nobody's character
        response = conn.getresponse()
        response.read()
        assert response.status == 404
        for headers in ({"Cookie": "session=forged"}, {}):
            conn.request("GET", "/me.json", headers=headers)
            response = conn.getresponse()
            response.read()
            assert response.status == 401
        conn.close()
    finally:
        server.shutdown()


def test_weblogins_keep_only_digests_and_let_links_lapse():
    now = [0.0]
    logins = WebLogins(clock=lambda: now[0])
    token = logins.new_link_token(42)
    assert token not in repr(vars(logins)), "the secret itself must not be stored"
    now[0] = LINK_SECONDS + 1
    assert logins.redeem(token) is None

    session = logins.redeem(logins.new_link_token(42))
    assert logins.member_id(session) == 42
    assert session not in repr(vars(logins))
    now[0] += SESSION_SECONDS + 1
    assert logins.member_id(session) is None


@pytest.mark.parametrize("path", ["/world.json", "/actors.json", "/chunk/0/0.png", "/client.js", "/me.json"])
def test_without_a_session_the_map_is_closed(base_url, path):
    """The map is for players: no cookie, or a forged one, gets nothing of it."""
    for cookie in ({}, {"Cookie": "session=forged"}):
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.build_opener().open(urllib.request.Request(base_url + path, headers=cookie))
        assert refused.value.code == 401
        refused.value.close()


def test_without_a_session_the_map_sends_you_to_how_to_join(base_url):
    conn = http.client.HTTPConnection(*base_url.removeprefix("http://").split(":"))
    conn.request("GET", "/map")
    response = conn.getresponse()
    response.read()
    conn.close()
    assert response.status == 303 and response.headers["Location"] == "/#join"


def public_home(base_url, cookie=None) -> str:
    request = urllib.request.Request(base_url + "/", headers={"Cookie": cookie} if cookie else {})
    with urllib.request.build_opener().open(request) as response:
        assert response.status == 200
        return response.read().decode()


def test_the_home_page_is_public_and_its_art_loads(base_url):
    page = public_home(base_url)
    assert "<h1>Testland</h1>" in page and "/weblogin" in page and 'href="/#join">Log in' in page
    assert "{{" not in page, "a placeholder went unfilled"
    for sprite in set(re.findall(r'src="(/sprites/[^"]+)"', page)):
        with urllib.request.build_opener().open(base_url + sprite) as response:
            assert response.read().startswith(b"\x89PNG")


def test_the_home_page_knows_who_you_are_and_escapes_it():
    adapter = WorldAdapter(GameSpace.World("Homeland", 40, 40, seed=7))
    adapter.register_player(7, 'Bo"b {{TOKEN}} & co')
    server = serve(adapter)
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        page = public_home(base, f"session={LOGINS.redeem(LOGINS.new_link_token(7))}")
        assert "logged in as <b>Bo&quot;b {{TOKEN}} &amp; co</b>" in page
        assert 'href="/map">Open the map' in page
        assert "have no character" in public_home(base, COOKIE)  # member 0 never registered
    finally:
        server.shutdown()


def test_your_character_sheet_shows_your_kit_and_what_is_waiting():
    from Discordia.GameLogic import Armor, Weapons

    adapter = WorldAdapter(GameSpace.World("Sheetland", 40, 40, seed=7))
    adapter.register_player(3, "Ada & co")
    character = adapter.get_player(3)
    character.equip(Armor.SSh68())
    character.inventory.append(Weapons.FNMinimi())
    character.pending_event = SimpleNamespace(flavor_text="A <stranger> blocks the road.")
    server = serve(adapter)
    base = f"http://127.0.0.1:{server.server_port}"
    cookie = f"session={LOGINS.redeem(LOGINS.new_link_token(3))}"
    try:
        page = public_home(base, cookie)  # the header knows you on every page
        assert 'class="me-link"' in page and "Ada &amp; co" in page

        with urllib.request.build_opener().open(urllib.request.Request(base + "/me", headers={"Cookie": cookie})) as r:
            sheet = r.read().decode()
        assert "<h1>Ada &amp; co</h1>" in sheet and "Level 1 Wanderer" in sheet
        helmet = Armor.SSh68()
        assert html.escape(helmet.name) in sheet  # in its slot, at its rating: armor_count is a roll
        assert f"{helmet._armor_count:g} armor" in sheet
        assert '<span class="slot">#0</span>' in sheet, "inventory is numbered for /inventory equip"
        assert "A &lt;stranger&gt; blocks the road." in sheet
        assert "{{" not in sheet, "a placeholder went unfilled"
    finally:
        server.shutdown()


def test_the_sheet_is_for_logged_in_players():
    conn = http.client.HTTPConnection("127.0.0.1", serve(WorldAdapter(GameSpace.World("Shut", 40, 40, seed=7))).server_port)
    conn.request("GET", "/me")
    response = conn.getresponse()
    response.read()
    assert response.status == 303 and response.headers["Location"] == "/#join"


def test_logging_out_ends_the_session_for_good():
    adapter = WorldAdapter(GameSpace.World("Exitland", 40, 40, seed=7))
    server = serve(adapter)
    session = LOGINS.redeem(LOGINS.new_link_token(9))
    conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
    try:
        conn.request("POST", "/logout", headers={"Cookie": f"session={session}", "Content-Length": "0"})
        response = conn.getresponse()
        response.read()
        assert response.status == 303 and response.headers["Location"] == "/"
        assert "Max-Age=0" in response.headers["Set-Cookie"]
        assert LOGINS.member_id(session) is None, "a copy of the old cookie must not still work"
    finally:
        conn.close()
        server.shutdown()
