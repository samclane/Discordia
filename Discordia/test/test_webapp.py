"""
End-to-end checks for the web map server: every route answers, the static responses revalidate,
and /sprites/ can't be walked out of.
"""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from functools import partial

import pytest

from Discordia.GameLogic import Actors, GameSpace
from Discordia.Interface.Rendering.DesktopApp import WindowRenderer
from Discordia.Interface.Rendering.WebApp import _Handler
from Discordia.Interface.WorldAdapter import WorldAdapter


@pytest.fixture(scope="module")
def base_url():
    adapter = WorldAdapter(GameSpace.World("Testland", 12, 12, seed=7))
    renderer = WindowRenderer(adapter)
    adapter.world.npcs.append(
        Actors.NPC(parent_world=adapter.world, name="Bandit", hp=10)
    )
    adapter.world.npcs[0].location = adapter.world.map[3][4]

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(_Handler, renderer))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def get(url):
    with urllib.request.urlopen(url) as response:
        return response.status, response.headers, response.read()


def test_page_and_client_are_served(base_url):
    assert b"<div id=\"viewport\">" in get(base_url + "/")[2]
    assert b"pollActors" in get(base_url + "/client.js")[2]


def test_background_is_a_png(base_url):
    status, headers, body = get(base_url + "/background.png")
    assert status == 200 and body.startswith(b"\x89PNG")
    assert headers["ETag"] == '"7"'  # the world seed


def test_static_responses_revalidate_to_304(base_url):
    request = urllib.request.Request(base_url + "/world.json", headers={"If-None-Match": '"7"'})
    with pytest.raises(urllib.error.HTTPError) as excinfo:  # urllib treats any 3xx it can't follow as an error
        urllib.request.urlopen(request)
    assert excinfo.value.code == 304


def test_world_json_describes_the_generated_map(base_url):
    world = json.loads(get(base_url + "/world.json")[2])
    assert world["width"] == world["height"] == 12
    assert len(world["terrain"]) == 12 and len(world["terrain"][0]) == 12
    assert all("x" in town and "name" in town for town in world["towns"])


def test_actors_json_carries_the_spawned_npc(base_url):
    actors = json.loads(get(base_url + "/actors.json")[2])["actors"]
    bandit = next(a for a in actors if a["name"] == "Bandit")
    assert (bandit["x"], bandit["y"], bandit["kind"]) == (4, 3, "npc")
    assert bandit["sprite"].startswith("/sprites/") and bandit["sprite"].endswith(".png")
    assert get(base_url + bandit["sprite"])[2].startswith(b"\x89PNG")


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
