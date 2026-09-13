---
description: One iteration of Discordia development. Pick the next ROADMAP.md item, build it, test, commit.
model: opus
allowed-tools: Bash, Read, Edit, Write, Grep, Glob
---

You are doing one iteration of a long-running development loop on Discordia, a Discord MUD. Read `CLAUDE.md` first.
Each iteration is independent: assume no memory of previous runs beyond what is in git and `ROADMAP.md`.

Requested focus (may be empty): $ARGUMENTS

## Procedure

1. **Orient.** Run `git status --short` and `git log --oneline -5`. If the tree is dirty from a previous run,
   commit it only if tests pass; otherwise `git stash` it and say so in your summary.
2. **Pick.** Open `ROADMAP.md`. If a focus was requested, take the matching item or theme. Otherwise take the first
   unchecked item, top to bottom, that you can finish in one sitting. If an item turns out too large, split it into
   two lines in the roadmap and do the first half.
3. **Understand before editing.** Read every file the item touches and trace the flow end to end
   (GameLogic -> WorldAdapter -> DiscordInterface -> Database). Grep for callers of anything you change.
   Respect `# ponytail:` comments: they name a shortcut and when to upgrade it.
4. **Build the smallest version that works.** Game rules in GameLogic, formatting in the Cog. Reuse existing
   helpers. No new dependencies. No abstractions for one use. If a character field changes, update `Database`
   save/load in the same commit.
5. **Test.** Add or extend one test per behavior in `Discordia/test/` (plain pytest, no Discord token), then run:
   ```
   python -m pytest Discordia/test -q
   ```
   Everything must pass. Fix what you broke; do not skip or delete tests to get green.
6. **Record.** Check the item off in `ROADMAP.md` and add one line under **Done** (`- YYYY-MM-DD item: what shipped`).
   If you noticed follow-up work, add it as new unchecked lines in the right section. Update `README.md` if a
   player-facing command changed.
7. **Commit.** One commit for the item, imperative subject line, body says what changed and why. Do not push.

## Rules

- Never start a second item in the same iteration. Small, finished, green.
- If the item cannot be done (blocked, needs a design decision), do not guess: leave it unchecked, add a
  `(blocked: reason)` note after it in the roadmap, and move to the next item.
- Do not touch `discordia.db`, `config.ini`, or `venv/`.
- Final message: three lines. What shipped, test count, what the next iteration should pick up.
