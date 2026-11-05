# Decisions to make

Questions for the user, one per blocked item in `ROADMAP.md`. Tick an option (or write your own under
**Notes**), then ask for a `/dev-loop` run: the answers go into the roadmap as `Decided YYYY-MM-DD: ...` notes,
the matching items get unblocked, and answered questions are removed from this file.

## Is the dog too strong?

Simulator bots that keep a dog die half as often: 10 seeds x 2000 ticks, deaths 7.5 -> 3.5 with pets (half the
bots on dogs), 6.2 with every bot on a goat. The dog's bite is `PET_BITE_DAMAGE` 2 on each of your blows, 4 once
it's happy (fed on time three times running), on top of e.g. a $100 hammer's 10. It costs $300 and $20 a feed.

- [ ] Fine as is: a dog is the safety pick, a goat the money pick.
- [ ] Halve the bite (1 a blow, 2 happy).
- [ ] Bite only once happy (0 until fed on time three times, then 2).
- [ ] Dearer dog: $600, the goat stays $300.

**Notes:**

## Anything else

New features, directions, or things you want the loop to stop doing:
