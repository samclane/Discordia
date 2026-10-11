"""
End-to-end checks for the web map server: every route answers, the static responses revalidate,
and /sprites/ can't be walked out of.
"""

import gzip
import http.client
import io
import json
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
from Discordia.Interface.WorldAdapter import WorldAdapter


def serve(adapter):
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


def get(url):
    with urllib.request.urlopen(url) as response:
        return response.status, response.headers, response.read()


def test_page_and_client_are_served(base_url):
    assert b"<div id=\"viewport\">" in get(base_url + "/")[2]
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
        connection.request("GET", path)
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
