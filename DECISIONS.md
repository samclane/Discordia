# Decisions to make

Questions for the user, one per blocked item in `ROADMAP.md`. Tick an option (or write your own under
**Notes**), then ask for a `/dev-loop` run: the answers go into the roadmap as `Decided YYYY-MM-DD: ...` notes,
the matching items get unblocked, and answered questions are removed from this file.

## Noise: may old maps re-roll? (ROADMAP, Libraries)

The terrain moves to `tcod.noise` (decided 2026-11-05). A world is saved as its seed and regenerated, so tcod's
noise draws a different map for an old save: towns, wilds and every character's position move. The plan for now is
that old saves keep `pnoise3`, which keeps the unmaintained `noise` package installed for them.

- [ ] Keep old saves on `pnoise3` (imported only when an old save loads), new worlds on tcod.
- [ ] Wipe is fine: every world moves to tcod, and `noise` leaves `requirements.txt`.

**Notes:**


## Leaflet: still worth it? (ROADMAP, Libraries)

You said vendor it (2026-11-05). Reading the client before starting, the main reason given doesn't hold: Leaflet's
`keepBuffer` only unloads tiles off screen, but a zoomed-out fit has every explored chunk on screen, so the ~4000
`<img>` ceiling stays (`client.js` already drops off-screen chunks). That ceiling's fix is overview tiles of 8x8
chunks drawn by the server, with or without Leaflet. What Leaflet still buys is less code of our own (~250 lines of
pan, zoom, pinch and fly-to), against rewriting the browser tests and re-solving what they pin down: chunk edges on
whole pixels (no grid seams), a slow pinch still zooming, scroll-out below the zoom floor, Firefox's image drag.

- [ ] Do it anyway: less of our own map code is worth the rewrite.
- [ ] Drop it: keep `client.js`. The ceiling gets the 8x8 overview tiles when explored chunks near ~4000.

**Notes:**


## Anything else

New features, directions, or things you want the loop to stop doing:
