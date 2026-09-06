"""
Serves the live world map over HTTP. Replaces the old desktop preview window: same WindowRenderer,
different output device.
"""

from __future__ import annotations

import logging
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from Discordia.Interface.Rendering.DesktopApp import WindowRenderer

LOG = logging.getLogger("Discordia.Interface.WebApp")

PAGE = b"""<!doctype html><title>Discordia</title>
<body style="margin:0;background:#111;display:grid;place-items:center;height:100vh">
<img id="w" src="/world.png" alt="World map"
     style="max-width:100vw;max-height:100vh;image-rendering:pixelated">
<script>
// Decode the next frame off-screen and only swap it in once it's loaded: no blank flash.
const img = document.getElementById("w");
(function poll() {
  const next = new Image();
  next.onload = () => { img.src = next.src; setTimeout(poll, 2000); };
  next.onerror = () => setTimeout(poll, 5000);
  next.src = "/world.png?t=" + Date.now();
})();
</script>
"""


class _Handler(BaseHTTPRequestHandler):
    def __init__(self, renderer: WindowRenderer, *args, **kwargs):
        self.renderer = renderer
        super().__init__(*args, **kwargs)  # this actually serves the request, so set attrs first

    def do_GET(self):
        if self.path.startswith("/world.png"):
            body, ctype = self.renderer.render_png(), "image/png"
        else:
            body, ctype = PAGE, "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")  # the map changes every tick
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        LOG.debug(format, *args)


def serve(renderer: WindowRenderer, port: int, host: str = "127.0.0.1"):
    """Blocks forever. Run me in a daemon thread."""
    # ponytail: client polls every 2s. Swap in SSE if that feels laggy.
    server = ThreadingHTTPServer((host, port), partial(_Handler, renderer))
    LOG.info("World map: http://%s:%d", host, port)
    server.serve_forever()
