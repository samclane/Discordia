# Decisions to make

Questions for the user, one per blocked item in `ROADMAP.md`. Tick an option (or write your own under
**Notes**), then ask for a `/dev-loop` run: the answers go into the roadmap as `Decided YYYY-MM-DD: ...` notes,
the matching items get unblocked, and answered questions are removed from this file.

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
