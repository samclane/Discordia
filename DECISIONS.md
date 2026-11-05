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


## Anything else

New features, directions, or things you want the loop to stop doing:
