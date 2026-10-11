"""
The map page in a real headless browser: what it fetches, when, and what it draws.

Drives Chrome or Edge over the DevTools protocol with aiohttp (already here for discord.py), so no new
dependencies. Skipped where neither browser is installed; GitHub's Ubuntu runners have Chrome.
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import aiohttp
import pytest

from Discordia.GameLogic import GameSpace
from Discordia.Interface.Rendering.WebApp import _Handler
from Discordia.Interface.WorldAdapter import WorldAdapter
from Discordia.test.test_webapp import serve

BROWSERS = [
    "google-chrome",
    "chromium",
    "chromium-browser",
    "chrome",
    "msedge",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]
BROWSER = next((p for p in (shutil.which(b) or (b if os.path.isfile(b) else None) for b in BROWSERS) if p), None)
pytestmark = pytest.mark.skipif(BROWSER is None, reason="no Chrome or Edge to drive")

# Under 700px wide the sidebar folds away, and 600x400 fits the whole 8x8-chunk world at about 1.5 screen
# pixels a square: zoomed out far enough for overviews and hidden labels.
WIDTH, HEIGHT = 600, 400


class Page:
    """Just enough of the DevTools protocol to load the map and run script in it."""

    def __init__(self, ws_url: str):
        self._loop = asyncio.new_event_loop()
        self._id = 0
        self._ws = self._run(self._connect(ws_url))

    def _run(self, coroutine):
        return self._loop.run_until_complete(coroutine)

    async def _connect(self, url):
        self._session = aiohttp.ClientSession()
        return await self._session.ws_connect(url, max_msg_size=0)

    def send(self, method: str, **params):
        self._id += 1
        call_id = self._id

        async def call():
            await self._ws.send_json({"id": call_id, "method": method, "params": params})
            async for message in self._ws:
                data = json.loads(message.data)
                if data.get("id") == call_id:  # events in between are dropped: nothing here listens
                    if "error" in data:
                        raise RuntimeError(f"{method}: {data['error']}")
                    return data["result"]

        return self._run(asyncio.wait_for(call(), 30))

    def js(self, expression: str):
        result = self.send("Runtime.evaluate", expression=expression, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in result:
            raise AssertionError(result["exceptionDetails"])
        return result["result"].get("value")

    def wait_for(self, condition: str, seconds: float = 10) -> bool:
        return self.js(
            f"(async () => {{ for (let i = 0; i < {seconds * 20}; i++) {{"
            f"  if ({condition}) return true; await new Promise((r) => setTimeout(r, 50)); }}"
            f"  return false; }})()"
        )

    def sleep(self, ms: int):
        self.js(f"new Promise((r) => setTimeout(r, {ms}))")

    def fetched(self, pattern: str) -> list:
        """What the page has requested so far whose URL matches the regex."""
        return self.js(
            f"performance.getEntriesByType('resource')"
            f".filter((e) => /{pattern}/.test(e.name))"
            f".map((e) => ({{ url: new URL(e.name).pathname, transfer: e.transferSize, body: e.encodedBodySize }}))"
        )

    def close(self):
        self._run(self._ws.close())
        self._run(self._session.close())
        self._loop.close()


@pytest.fixture(scope="module")
def base_url():
    world = GameSpace.World("Webland", 256, 256, seed=7)
    size = GameSpace.CHUNK_SIZE
    for y in range(0, world.height, size):  # explore all of it, so a fit view is wide and far out
        for x in range(0, world.width, size):
            world.space_at(x, y)
    server = serve(WorldAdapter(world))
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture(scope="module")
def browser():
    profile = tempfile.mkdtemp()
    args = [BROWSER, "--headless=new", "--remote-debugging-port=0", f"--user-data-dir={profile}",
            "--no-first-run", "--no-default-browser-check", "about:blank"]
    if sys.platform.startswith("linux"):
        args.append("--no-sandbox")  # CI runners forbid the user namespaces Chrome's sandbox wants
    process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    port_file = Path(profile) / "DevToolsActivePort"  # where port 0 tells us the port it picked
    deadline = time.time() + 20
    while not (port_file.exists() and port_file.read_text().strip()):
        assert time.time() < deadline, "browser never opened its debugging port"
        time.sleep(0.1)
    port = int(port_file.read_text().split()[0])
    targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
    page = Page(next(t for t in targets if t["type"] == "page")["webSocketDebuggerUrl"])
    # The default 250-entry buffer would fill with chunk images before the tests looked.
    page.send("Page.addScriptToEvaluateOnNewDocument", source="performance.setResourceTimingBufferSize(100000)")
    yield page
    page.send("Browser.close")
    page.close()
    process.wait(timeout=10)
    shutil.rmtree(profile, ignore_errors=True)


@pytest.fixture
def page(browser, base_url, request):
    """The map, freshly loaded and fitted, with every chunk image in view finished loading."""
    dpr = getattr(request, "param", 1)
    browser.send("Emulation.setDeviceMetricsOverride", width=WIDTH, height=HEIGHT, deviceScaleFactor=dpr, mobile=False)
    browser.send("Network.clearBrowserCache")  # each test sees a first visit
    browser.send("Page.navigate", url=base_url + "/")
    assert browser.wait_for(
        "typeof chunkEls !== 'undefined' && chunkEls.size > 0 && [...chunkEls.values()].every((i) => i.complete)"
    )
    return browser


def chunk_kinds(page) -> set:
    return set(page.js("[...chunkEls.values()].map((el) => el.getAttribute('src').split('.').slice(1).join('.'))"))


def test_zoomed_out_load_fetches_overviews_and_no_chunk_descriptions(page):
    """Full chunks at a fit view were 34 KB each, and their JSON came along whether anyone hovered or not."""
    assert page.js("view.scale * tile") < 4
    assert len(page.fetched(r"\/chunk\/\d+\/\d+\.mini\.png")) == 64
    assert page.fetched(r"\/chunk\/\d+\/\d+\.png$") == []  # not even before the fit landed
    assert page.fetched(r"\/chunk\/.*\.json") == []


def test_zooming_in_swaps_overviews_for_full_chunks(page):
    assert chunk_kinds(page) == {"mini.png"}
    page.js("view.scale = 0.5; applyView(); 0")
    assert page.wait_for("![...chunkEls.values()].some((el) => el.src.includes('.mini.'))")
    assert chunk_kinds(page) == {"png"}
    page.js("fitToViewport(); 0")
    page.sleep(100)
    assert chunk_kinds(page) == {"mini.png"}


def test_hovering_fetches_just_that_chunks_description(page):
    page.send("Input.dispatchMouseEvent", type="mouseMoved", x=WIDTH // 2, y=HEIGHT // 2)
    assert page.wait_for("((t) => t && !t.includes('…'))(document.getElementById('hover').textContent)")
    assert len(page.fetched(r"\/chunk\/.*\.json")) == 1
    hover = page.js("document.getElementById('hover').textContent")
    assert hover.startswith("(") and hover.split(") ")[1] not in ("", "unexplored")


def test_scrolling_out_from_a_fit_does_not_zoom_in(page):
    """A fit can land under the 0.2 zoom floor; the first wheel-out used to snap back up to it."""
    before = page.js("view.scale")
    assert before < 0.2
    page.send("Input.dispatchMouseEvent", type="mouseWheel", x=WIDTH // 2, y=HEIGHT // 2, deltaX=0, deltaY=120)
    page.sleep(100)
    assert page.js("view.scale") <= before


def test_town_labels_hide_when_too_far_out_to_read(page):
    assert page.js("view.scale * tile") < 2
    assert page.js("getComputedStyle(document.getElementById('labels')).display") == "none"
    page.js("view.scale = 0.25; applyView(); 0")
    assert page.js("getComputedStyle(document.getElementById('labels')).display") == "block"
    assert page.js("document.querySelector('.label').getBoundingClientRect().width") > 0


@pytest.mark.parametrize("page", [1, 1.25], indirect=True, ids=["dpr1", "dpr1.25"])
def test_chunk_edges_land_on_whole_pixels_and_clicks_hit_the_drawn_square(page):
    """Edges between pixels let the background through, a faint grid over the map. Snapping what's drawn
    mustn't move what a click picks."""
    bad = page.js(
        """(() => {
          const d = devicePixelRatio, bad = [];
          for (const scale of [0.0731, 0.137, 0.2402, 0.53, 1.37, 3.3]) {
            for (let k = 0; k < 6; k++) {
              view.scale = scale; view.x = 100 + k * 13.37; view.y = 50 + k * 7.71; applyView();
              showChunks();
              for (const el of chunkEls.values()) {
                const r = el.getBoundingClientRect();
                for (const v of [r.left, r.top, r.width, r.height])
                  if (Math.abs(v * d - Math.round(v * d)) > 0.01) bad.push(['edge', scale, k, v * d]);
              }
              const want = { x: origin.x + k - 3, y: origin.y + 2 - k };
              selectTile(want.x, want.y, false);
              const b = pick.getBoundingClientRect();
              const got = tileAt(b.left + b.width / 2, b.top + b.height / 2);
              if (got.x !== want.x || got.y !== want.y) bad.push(['click', scale, k, want, got]);
            }
          }
          return bad.slice(0, 5);
        })()"""
    )
    assert bad == []


def test_a_slow_pinch_still_zooms(page):
    """The drawn zoom is rounded; the view's isn't, or steps smaller than the rounding would vanish."""
    page.js("view.scale = 0.2; applyView(); for (let i = 0; i < 100; i++) zoomCenter(1.001); 0")
    assert page.js("view.scale") == pytest.approx(0.2 * 1.001**100)


def test_selecting_moves_the_highlight_without_rebuilding_the_town_list(page):
    """Rebuilding a thousand rows on every click took 40ms."""
    result = page.js(
        """(() => {
          const rows = [...document.querySelectorAll('#towns .row')];
          const [a, b] = rows;
          const [ax, ay] = a.dataset.at.split(',').map(Number);
          const [bx, by] = b.dataset.at.split(',').map(Number);
          selectTile(ax, ay, false);
          const first = rows.filter((r) => r.classList.contains('selected')).map((r) => r.dataset.at);
          selectTile(bx, by, false);
          const second = rows.filter((r) => r.classList.contains('selected')).map((r) => r.dataset.at);
          clearSelection();
          const cleared = rows.filter((r) => r.classList.contains('selected')).length;
          return { first, second, cleared, a: a.dataset.at, b: b.dataset.at, kept: rows.every((r) => r.isConnected) };
        })()"""
    )
    assert result["first"] == [result["a"]] and result["second"] == [result["b"]]
    assert result["cleared"] == 0
    assert result["kept"]  # the same elements, restyled, not replaced


def test_a_background_tab_stops_polling(page):
    page.js("performance.clearResourceTimings(); Object.defineProperty(document, 'hidden', { value: true, configurable: true }); pollActors(); pollExplored(); 0")
    page.sleep(300)
    assert page.fetched(r"(actors|explored)\.json") == []

    page.js("delete document.hidden; pollActors(); 0")  # the control: visible, it does fetch
    assert page.wait_for("performance.getEntriesByType('resource').some((e) => e.name.endsWith('/actors.json'))")


@pytest.mark.parametrize("route, poll", [("explored", "pollExplored"), ("actors", "pollActors")])
def test_polls_revalidate_instead_of_redownloading(page, monkeypatch, route, poll):
    """Nothing changes in this world, so after the page's first poll each one should be an empty 304."""
    codes = []
    send_response = _Handler.send_response

    def record(handler, code, *args):
        if handler.path == f"/{route}.json":
            codes.append(code)
        send_response(handler, code, *args)

    monkeypatch.setattr(_Handler, "send_response", record)
    page.js(f"{poll}(); 0")
    for _ in range(100):
        if codes:
            break
        page.sleep(50)
    assert codes and set(codes) == {304}
