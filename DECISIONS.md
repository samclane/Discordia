# Decisions to make

Questions for the user, one per blocked item in `ROADMAP.md`. Tick an option (or write your own under
**Notes**), then ask for a `/dev-loop` run: the answers go into the roadmap as `Decided YYYY-MM-DD: ...` notes,
the matching items get unblocked, and answered questions are removed from this file.

## Web server: aiohttp on the bot loop? (ROADMAP, Libraries)

The plan was to serve the site from `aiohttp.web` on the bot's own loop, so web requests and the game share one
thread: no `run_coroutine_threadsafe` bridge, no torn reads. Reading the handler, the catch is the chunk and hideout
PNGs: Pillow renders them, CPU-bound, and on the bot loop a render holds up the tick (and every slash command).
Handing renders to a thread pool fixes that but brings back threads reading the world, which was the point.

- [ ] aiohttp on the bot loop, Pillow renders in `run_in_executor`. Routes and SSE get simpler; renders still
  read the world off-loop (cached chunks are most of them).
- [ ] Drop it: `http.server` works. SSE, if the map ever feels laggy, is a thread per open map. The SSE item stays
  as it is.
- [ ] aiohttp in its own thread with its own loop: a route table and cheap SSE, the bridge to the bot loop stays.

**Notes:**


## Noise: how to get off the unmaintained `noise` package? (ROADMAP, Libraries)

`noise` (`pnoise3`, the terrain) is a C extension nobody maintains: a Python upgrade or a new server can fail to
install it. A world is saved as its seed and regenerated, so a different noise re-rolls every saved map. Checked
2026-11-03: `vnoise` (the numpy port) matches `pnoise3` to 0.00003 on 2,000 points, so maps would survive bar the odd
square on a threshold, but as published it doesn't import on this Python (needs the removed `pkg_resources`).
The dev loop also doesn't add dependencies on its own.

- [ ] Vendor the port: ~100 lines of vnoise's Perlin (MIT, credited) in `Procedural.py`, no new dependency, old maps
  kept. Per-square calls in numpy are slower than C; generation would be vectorised per chunk to make up for it.
- [ ] Add python-tcod (`tcod.noise`, and its pathfinding for the NPC item later). Old maps re-roll: say whether a
  wipe is fine or old saves keep `pnoise3` (and so keep the package around).
- [ ] Leave it until it actually fails to install somewhere.

**Notes:**


## Leaflet for the web map: may the loop vendor it? (ROADMAP, Libraries)

Leaflet is one JS file plus CSS, no build step, but it's a dependency and the loop doesn't add those unasked.

- [ ] Yes, vendored into `Rendering/` (served by our own server, no CDN, works offline).
- [ ] Yes, from a CDN with a pinned version and integrity hash.
- [ ] No: keep `client.js` as it is.

**Notes:**


## Anything else

New features, directions, or things you want the loop to stop doing:
