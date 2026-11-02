# Decisions to make

Every blocked item in `ROADMAP.md`, as a question. Tick an option (or write your own under **Notes**), then ask
for a `/dev-loop` run: the answers go into the roadmap as `Decided YYYY-MM-DD: ...` notes, the matching items get
unblocked, and this file is emptied.

## 1. Design decisions

### 1.1 No way back from broke

A raid death strips carried money and gear. With an empty stash and no hideout you're left with fists (2 dmg),
which lose the fights that would pay for a gun. One simulator bot spent a whole 5000-tick run in this spiral.
For scale: you start with $1000, and the cheapest store weapons are a Stechkin pistol ($75, 4 dmg), a Carl
Gustaf ($90, 5 dmg) and a Hammer ($100, 10 dmg, melee, needs no ammo).

- [ ] **Starter weapon:** a town store hands you a free weapon when you have none (carried, worn, pouch or stash)
      and can't afford the cheapest one.
      Which weapon? ________ (default: Hammer, since it needs no ammo)
- [ ] **Loan:** a town lends you $____ when you're broke, paid back automatically out of hauls or hideout income.
      Interest? ____ %
- [ ] **Fist-safe income:** something that pays without fighting (caches already do). Which? ________
- [ ] **Leave it:** going broke is the risk. Starting over is the way out.

Notes:

## 2. Waiting on a condition: do it now, or keep waiting?

Each of these is parked until something happens that the loop can't see. Tick **Do it now** to unblock it.

### 2.1 Town residents on the map
Residents (`Town.residents`) are just names in `/town status`. They could be NPCs standing in town, drawn from
Kenney's people tiles. Waiting on players saying towns feel empty.
- [ ] Do it now   - [ ] Keep waiting   - [ ] Drop it

### 2.2 `/trade sell` to wilds traders
Wilds traders only sell. Letting them buy is a few lines. Waiting on players asking for it.
- [ ] Do it now   - [ ] Keep waiting   - [ ] Drop it

### 2.3 Deferred refusals show to the whole channel
A refusal from `/move`, `/attack`, `/choose` or `/look` that depends on the tick is posted publicly. The fix
needs checking against real Discord. Can you test it on a live server?
- [ ] Yes: build it, and I'll check it on __________
- [ ] Build it without checking
- [ ] Leave it

### 2.4 Web map: SSE push instead of polling every 2s
Waiting on the map feeling laggy.
- [ ] Do it now   - [ ] Keep waiting   - [ ] It's fine, drop it

### 2.5 Unload chunks nobody is in
Each loaded chunk is ~0.4 MB and is never freed. Waiting on the live server's memory.
Current memory use on the Linode box: ________
- [ ] Do it now   - [ ] Keep waiting

### 2.6 Terrain repeats every ~2560 squares
About 3.5 hours of `/move` from spawn before you'd see a repeat.
- [ ] Fix it now   - [ ] Keep waiting   - [ ] Never matters, drop it

### 2.7 Store shelves forget part-used ammo boxes
Sell a half-empty ammo box to a store and after a restart it's back on the shelf full. Waiting on someone
farming it.
- [ ] Fix it now   - [ ] Keep waiting

### 2.8 Schema migrations
`Database._migrate` checks which columns exist. Switch to `PRAGMA user_version` and numbered steps once a
change has to rewrite data, not just add a column.
- [ ] Switch now   - [ ] Keep waiting

## 3. Anything else

New features, directions, or things you want the loop to stop doing:

