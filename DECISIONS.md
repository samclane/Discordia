# Decisions to make

Questions for the user, one per blocked item in `ROADMAP.md`. Tick an option (or write your own under
**Notes**), then ask for a `/dev-loop` run: the answers go into the roadmap as `Decided YYYY-MM-DD: ...` notes,
the matching items get unblocked, and answered questions are removed from this file.

## Empty hands: fists or nothing? (ROADMAP, Cleanup)

Unequipping your weapon, or selling the one you hold, leaves you with no weapon at all: `/attack` answers "You
have no weapon equipped!" and a wilds fight says the same, until you equip something. Yet a new character and a
dead one start with fists, and a gun that runs dry falls back to fists mid-fight. Two tests pin the "no weapon"
behaviour today, so it may have been meant: a way to refuse a fight on purpose.

- [ ] Fists: an empty hand punches, like a new character. `PlayerCharacter.unequip` puts a fist back; the two
  tests change to expect it.
- [ ] Nothing, as now: keep "no weapon equipped" as a way to stay out of a fight. Drop the roadmap item.

**Notes:**


## Anything else

New features, directions, or things you want the loop to stop doing:

