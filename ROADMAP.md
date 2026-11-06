# Roadmap

Backlog for `/dev-loop`. One line per item, roughly in priority order within a section. The loop picks the first
unchecked item it can finish in one sitting, checks it off, and appends one line under **Done**. Add new items at
the bottom of the right section, add sections when a theme emerges. Keep items small enough for one commit.
Checked items get cleared out now and then (last 2026-11-05): their Done line stays, and `git log` has the rest.

## Vibe: extraction idle

Cookie Clicker meets Escape From Tarkov. Towns are safe; everything past them is a raid. You go out, grab what
you can, and either make it back to a town (extract) or die and lose what you carried. What you bank builds a
hideout that earns while you're away, and the hideout pays for better kit for riskier raids further out. Numbers
always go up at home; the wilds are where you gamble them.

When choosing between items, prefer the one that tightens that loop: risk out there, safety and growth at home,
and a reason to check in on Discord a few times a day rather than grind for hours.

## Theme: the Soviet-Afghan War

The setting is the Soviet-Afghan War (1979-1989): dry mountains, mud-walled villages, passes that change hands
by the hour, and a war nobody is winning. It is the skin over the loop above, not a history lesson. Places and
people are invented; the period, kit and landscape are real.

- Towns are what holds: walled villages (kishlaks), bazaars, and the two military bases. Eastern is a Soviet
  garrison, Western a mujahideen camp supplied from over the border. Both sides are people trying to get home.
- The wilds are mountains, dry riverbeds (wadis), poppy fields and roads where convoys get ambushed. Danger rises
  with altitude and distance from a garrison.
- Raiders are bandits and deserters from either side, not a faction anyone can join on purpose.
- Caches are weapon dumps, wrecked convoys and caravans; extraction points are helicopter landing zones and
  friendly checkpoints.
- Kit is period: AK-47/AKM/AK-74, Lee-Enfield, Makarov, RPG-7, DShK, afghanka uniforms, flak vests. Money is
  afghanis; barter goods are tea, tinned meat, cigarettes, batteries, medicine.
- Tone is Tarkov's: grim and practical, no heroes. Don't make civilians targets or jokes, and don't take a side.

When naming or flavoring something new (an item, a tile, an NPC, an event line), fit it to this setting. Rename
existing things to it when an item touches them anyway, not as a sweep.

## Extraction idle loop (the core)

- [ ] Pets, more kinds by role (a donkey that carries more?), once the goat and the dog show what players use.
  (blocked: waits on players having had the goat and the dog a while; nothing records which they adopt yet)
- [x] Make the hideout more expensive (asked 2026-11-05). Level 1 is `HIDEOUT_COST` $1000, about 8 hours of what
  it pays, and each after `HIDEOUT_GROWTH` x1.15.

## Gameplay loop (make it a game)

- [x] Simulator bots raid toward a random point `reach` squares out (`Bot._pick_goal`), never a cache: 2 caches
  opened in 10 seeds x 2000 ticks, so caches, found armor and the 6B45 barely show in `sim_history`. Have them
  head for the nearest stocked cache within reach, as `/raid` does (`World._auto_raid_step`). Expect every game
  metric to move; `mean armor worn` should leave 0.

- [x] Since 7db073c (bots raid for caches) mean level fell 2.28 -> 2.03 and mean worth 712.7 -> 668.8 (10 seeds x
  2000), deaths 7.3 -> 7.1. Likely a bot habit: once it reaches its cache the goal stays put, so it loiters there
  until its steps run out instead of going on out (less extract XP, fewer kills). Give it a new goal on arrival
  (the next stocked cache in reach, else a random point) and see if level and worth come back.

- [x] Simulator bots build hideouts (asked 2026-11-05): none ever do, so the price and income tuning never shows in
  `sim_history`. A bot in town with the next level's price to spare builds it; a metric for mean hideout level.
- [x] Simulator bots keep pets (asked 2026-11-05): adopt a goat or a dog once they can afford it, feed it when in
  town, and a metric for pets kept.
- [x] No simulator bot affords a first hideout level ($2000 since b36ce63): `mean hideout level` is 0 over 10 seeds x
  2000 ticks, and in one seed x 10000 ticks (~14 hours at a 5-second tick) the richest of 6 bots ends on $1451.
  Is that the bots (most end on a hammer or fists) or the economy? Find out before pricing the hideout further.
- [x] Is the dog too strong? With simulator bots keeping pets, 10 seeds x 2000 deaths went 7.5 -> 3.5 and mean level
  2.07 -> 2.72; with every bot on a goat instead, 6.2 and 2.10. So the dog's bite (`PET_BITE_DAMAGE` 2 a blow, 4
  once happy) on top of a $100 hammer's 10 halves deaths, for $300. Decide if that's the dog's job or too much.
  Decided 2026-11-05: halve the bite, 1 a blow and 2 once happy.
- [x] Most simulator bots end on a hammer or fists and earn like a work shift: per 2000 ticks the median bot makes
  $173, the top three (all on rifles) $1369-1878. Find why they don't re-arm with a rifle after a raid death (the
  stash running dry? `Bot._best_gun` ranking a $100 hammer's 10 damage over what it can afford with ammo?).
- [x] Stores sell guns they have no ammo for: 22% of the guns on fresh shelves (the starting town and 20 more, 10
  seeds), and a box can sell out after. A player who buys one has a club once the loaded rounds are gone, and
  simulator bots raid dry a tenth of the time for it. Stock a box of its ammo with every gun a shelf carries?

## NPCs and world

## Persistence

## Discord UX

## Rendering

- [ ] Web map: SSE push instead of 2s polling (ponytail in `WebApp.serve`), a `web.StreamResponse` on the bot loop.
  (blocked: waits on players finding the map laggy)
- [ ] Evict chunks with nobody in them (~0.4 MB each, never unloaded: ponytail in `World.__init__`); store sales
  in them would need saving first. (blocked: waits on the live server's memory, charted on `/admin`. Checked
  2026-11-03: runs peak at 47-72 MB RSS of ~1 GB, and every deploy restarts the process and drops its chunks.)
- [x] Terrain repeats every ~2560 squares (`pnoise3`'s period, ponytail in `World._terrain_at`). The noise item
  under Libraries fixes it if tcod's noise doesn't wrap. (blocked: on that item)
- [x] Don't draw townspeople on town tiles (asked 2026-11-05): drop the doorway townsperson added 2026-11-03.
- [x] Map info panel: click an actor's name to target it on the map (asked 2026-11-05).
- [x] Map info panel reads like a console (asked 2026-11-05): a scrolling log, newest at the bottom.

## Cleanup

- [ ] Flaky web tests: five have failed once each in a full run and passed after (2026-11-03: two in
  `test_webapp.py`, three in `test_webclient.py`; 2026-11-04: `test_a_slow_pinch_still_zooms` at setup, the `page`
  fixture's 10s wait for every chunk `<img>` to be `complete`). They look timing-sensitive under load; that 10s
  wait is the likeliest shared cause. (blocked: none reproduce. Next time, keep pytest's whole output and start
  from the traceback; ruled out so far: port reuse between test servers.)
- [x] Clean and compact `ROADMAP.md` (asked for 2026-11-05): it's ~760 lines, most of them Done entries and long
  blocked notes. Keep every open item and its decisions; shorten the rest.
- [x] Timestamps on every simulation HTML page (asked for 2026-11-05): `sim.html`, `server.html` and
  `history.html` should say when the run (or the chart) was made.
- [x] `mean armor worn (pieces)` went 0.02 -> 0 in the game simulator at `a166029` and has stayed 0 since (asked
  for 2026-11-05: "why?"). Find what that commit changed for bots' armor, and whether it's the bots or the game.

## Libraries

Hand-rolled parts an existing library already does. Researched 2026-11-03; in this order.

- [x] Replace `noise` (`pnoise3`: unmaintained, no wheels for recent Pythons) with `tcod.noise`. Decided
  2026-11-05: python-tcod, built around (its pathfinding for the item below); a wipe is fine, so every world moves
  to tcod (old saves re-roll) and `noise` leaves `requirements.txt`. (blocked: tcod isn't installed in the venv,
  and the loop doesn't touch `venv/`: `pip install tcod` there; the item adds it to `requirements.txt`)
- [ ] NPC chase via `tcod.path` (a Dijkstra map toward the player) instead of greedy steps (ponytail in
  `NPC.step`), so a coastline doesn't stop them cold; `astar` can go if `AStarPathfinder` moves over too. Only if
  stuck NPCs show up in play or the simulator. (blocked: tcod is in now; waits on stuck NPCs showing up)

## Done

- 2026-09-13 Earn money: NPCs carry `CURRENCY_PER_LEVEL * level`, paid out once per kill.
- 2026-09-14 Death has a cost: a death left `DEATH_TAX` of carried money behind (raid loss replaced it).
- 2026-09-14 NPC hit points: `HIT_POINTS_PER_LEVEL * max(level, 1)`; level-1 raiders no longer arrive dead.
- 2026-09-14 `/attack` hits NPCs: `World.attack` targets players and NPCs, paying out through `PlayerCharacter.loot`.
- 2026-09-15 Wilds difficulty: danger measured from the spawn, not a placeholder town at (0, 0).
- 2026-09-15 XP and levels: kills pay XP, 100 a level, each level +10 max hit points.
- 2026-09-16 `EncounterEvent` is real: a stranger on the road waits for `/choose` talk, rob or ignore.
- 2026-09-20 `MerchantEvent` is real: a road trader sells a `Store.generate_store()` slice at `MARKUP` via `/trade`.
- 2026-10-11 Minecraft-sized worlds: the map generates a 32-square chunk at a time, deterministic per (seed, chunk).
- 2026-10-11 Urban tiles: terrain autotiled from Kenney's RPG Urban pack by its neighbours (`Terrain.neighbours`).
- 2026-10-12 Raiders hunt: a raider that sees you out of town steps toward you, and you're DM'd the first time.
- 2026-10-22 Stash: `/stash put|take|list` in town; carried and stashed are separate.
- 2026-10-22 Raid loss: dying out of town loses carried money, backpack and worn gear (`lose_carried`).
- 2026-10-28 Ammo: `Items.Ammo` exists, so guns run dry and reload instead of firing into negative rounds.
- 2026-10-29 "Roaming raiders" weren't the problem: the simulator blamed deaths on the square before the fatal move.
- 2026-10-29 Extract: stepping into a town ends the raid and says what it brought home.
- 2026-10-29 Secure pouch: `/inventory pouch` keeps one item through a raid death.
- 2026-10-29 Corpse run: a raid death leaves its things on the square (`Space.remains`) for `REMAINS_TICKS`.
- 2026-10-29 Hideout income: `/hideout build` buys levels that pay into the stash every tick.
- 2026-10-29 Offline catch-up: a load runs the clock on by the downtime (`World.advance`), hideouts included.
- 2026-10-29 Hideout pricing: level n costs `HIDEOUT_COST * 1.15 ** n`, every 5th salvage instead of money.
- 2026-10-29 Idle numbers: income per hour, stash worth and the next level's price on `/equipment` and `/me`.
- 2026-10-29 Discord server simulator (`test_server_simulation.py`): real commands on fake servers, every message checked.
- 2026-10-29 Caches are raid targets: kit and salvage scale with danger, and caches refill on a timer.
- 2026-10-29 Auto-raid: `/raid <minutes>` walks to caches, fights, comes home and DMs the result.
- 2026-10-29 Raid risk knob: `/raid <minutes> [depth]` caps the danger an auto-raid goes to.
- 2026-10-29 Auto-raid survives a restart: its home-at tick and depth are saved.
- 2026-10-29 Extraction points: `Extract` squares out in the wilds, seeded per cache cell like caches.
- 2026-10-29 Levels outrun the map: a kill below your level pays only a share of its XP.
- 2026-10-29 Rest outside towns: `/camp` heals `CAMP_HEAL_SHARE` every `CAMP_HEAL_TICKS`.
- 2026-10-29 Animals: `Actors.Animal` (rat, stray dog, boar...) roam with their own sprites.
- 2026-10-29 Town population: a named shopkeeper, innkeeper and guard per town (`Town.residents`).
- 2026-10-29 Wilds cooldown: a wilds square goes quiet `WILDS_QUIET_TICKS` after an event, then restocks.
- 2026-10-30 Save NPCs: roaming NPCs live in a new `npc` table.
- 2026-10-30 Store stock is saved: a traded store's shelf goes in a `store` table.
- 2026-10-30 Weapon state: items carry a migrated JSON `state` (rounds loaded, jams, ammo left).
- 2026-10-30 `/look` lists who's in sight, nearest first with bearings, and how rough the square is.
- 2026-10-30 `/help`: every slash command, read from the command tree.
- 2026-10-30 Ephemeral errors: refusals that went to the whole channel are private.
- 2026-10-30 Channel announcements: raid deaths and hauls posted to a server's channel (`World.announcements`).
- 2026-10-30 Terrain labels: `Terrain.label` names what the art shows (paving, park, canal, rooftops).
- 2026-10-30 Sprites by body size: small animals draw as a rat, large ones as a dog.
- 2026-10-30 Piles on the map: `World.piles`/`live_piles()` show where raid deaths left things.
- 2026-10-30 Naming the way out: `/look` out of town names the nearest town or extraction point, with a bearing.
- 2026-10-30 Worn from the backpack, saved once: an equipped backpack item no longer saves (and loads) twice.
- 2026-10-30 Deleted `GameSpace.Base` and `BaseLevel`: never used; the hideout is `hideout_level`.
- 2026-10-30 `FullyImplemented` is gone: stores stock `Data.stocked()`, minus blocks saying `"store": false`.
- 2026-10-30 The `FIXME Ugly function` was `World.is_space_buildable`, only used to plant a town when a map rolls none.
- 2026-10-30 README: documents `-W`, `--database`, the tests, `/settings`, the DMs, the inn and stores.
- 2026-10-30 More classes: Scavenger, Medic, Scout and Fixer, each trained in one kind of trade town, a perk each.
- 2026-10-30 Ruins and plazas: a fourth noise layer turns paving into ruins (cover) or plazas (exposed).
- 2026-10-31 Achievements (d15fd3f): twelve, DM'd and announced, listed on `/achievements` and `/me`.
- 2026-10-31 Raider deaths after fc3f783: per tick out, Raider bots die in wilds fights no more than anyone else.
- 2026-10-31 Deaths after d15fd3f: one seed-1 bot's broke, bare-fisted spiral, not a balance change.
- 2026-10-31 Unarmed simulator bots: a bot with only fists stays on danger 1 until it can afford a gun.
- 2026-10-31 Soldier prices: soldiers pay 20% less at their own side's base store, 20% more at the other's.
- 2026-10-31 Enlisting simulator bots: a third enlist at the first military base; a `soldiers (share of bots)` metric.
- 2026-10-31 Private refusals before the tick: what's knowable before the tick is refused privately, before the defer.
- 2026-10-31 Cache-only chest armor: caches can roll the 6B45 (`CACHE_ONLY`), likelier the deeper they are.
- 2026-10-31 Bots wear found armor (`Bot._better_armor`), and a `mean armor worn (pieces)` metric: 0.02, armor is scarce.
- 2026-10-31 Prestige: `/hideout prestige` (hideout 15+) trades the hideout and stash for +10% income for good.
- 2026-10-31 XP on extract: a haul pays `EXTRACT_XP_PER_DANGER` XP per danger level of the raid's deepest square.
- 2026-10-31 Simulator bots read cover: their steps swing onto ruins and off plazas (`Bot._careful`).
- 2026-10-31 Extract XP deadlier? No: 10 seeds x 2000 ticks with and without it die about the same.
- 2026-10-31 Simulator `--seeds N`: plays N seeds and records the means.
- 2026-10-31 Simulator bots recruit: Wanderer bots take the first trade town's class; a trade-class share metric.
- 2026-10-31 Faction joining: robbing or killing a player makes you a Raider; a base's recruits record their side.
- 2026-10-31 Simulator bot stance: odd-numbered bots rob strangers, even ones never do.
- 2026-10-31 Raiders spare Raiders: raider NPCs neither hunt nor hit Raider-class players (`World.spares`).
- 2026-10-31 Friendly fire: `/attack` with no direction no longer hits whoever happens to share your square.
- 2026-11-02 A rendered hideout: `/hideout view` and `/me` draw a room a square wider per level, the stash on show.
- 2026-11-02 Trophies on the hideout wall: a frame per achievement and one for the best haul.
- 2026-11-02 Odd jobs: `/town work` pays an hour-long shift, $48 at a 5-second tick.
- 2026-11-02 Gathering: `/gather` on danger-1 ground pays the same shift in firewood, $60 once sold.
- 2026-11-02 Simulator bots work: broke and bare-fisted, a bot works shifts until it can buy a gun.
- 2026-11-02 Stores restock: every `STORE_RESTOCK_TICKS` a traded store gets back a kind it sold out of.
- 2026-11-02 Checked the work wage: bare-fisted, working pays $47 an hour and fist-raiding $0. Left as is.
- 2026-11-02 Checked the restock death rise (10 seeds x 5000): deaths held; levels fell from bots buying the cheapest gun.
- 2026-11-03 Bots shop like players: a broke bot buys the most damaging gun it can afford, with ammo (`Bot._best_gun`).
- 2026-11-03 Town residents on the map: a townsperson drawn in every town's doorway.
- 2026-11-03 Store shelves keep item state through a restart: a part-used ammo box stays part-used.
- 2026-11-03 Numbered schema migrations: `Database.MIGRATIONS`, stepped by `PRAGMA user_version`.
- 2026-11-03 Refusals after a public defer go private (the "thinking..." reply is deleted). Unchecked on real Discord.
- 2026-11-03 Dashboard memory: `/admin` charts the process's resident memory beside loaded chunks.
- 2026-11-03 `/trade sell`: a wilds trader buys at two thirds of a town's price.
- 2026-11-03 Empty hands are fists: unequipping or selling your gun leaves you a fist.
- 2026-11-03 Pets, first slice: a goat (`/pet adopt|feed|status`) puts milk in the stash every hour while fed.
- 2026-11-03 Pets, neglect and care: fed on time it gives twice the milk; hungry three days, it wanders off.
- 2026-11-03 Hungry goat DM: one DM when its last meal runs out.
- 2026-11-03 Dog fetches: `/pet adopt kind:dog`; a fed dog finds salvage on quiet steps. One pet each.
- 2026-11-03 Dog bites: a fed dog adds `PET_BITE_DAMAGE` to the blows you land.
- 2026-11-04 Web server on aiohttp: the site runs on the bot loop, renders in a thread; a timed-out web order is cancelled.
- 2026-11-05 Web map on Leaflet: vendored 1.9.4, one chunk per tile at every zoom; a pinch lands on a whole level.
- 2026-11-05 Compacted `ROADMAP.md` 764 -> ~190 lines: checked items cleared, each Done entry one line, the blocked
  notes cut to their reason (the five flaky web tests are one item now). Nothing open or decided was dropped.
- 2026-11-05 Timestamps on the simulation pages: `sim.html` and `server.html` say when the run was (the server's
  from its log's meta line, so a `--from` redraw keeps it), `history.html` when it was drawn.
- 2026-11-05 Why `mean armor worn` fell to 0 at a166029: the bots, not the game. Before it, one bot put on armor
  once in 10 seeds x 2000 ticks (the 0.02); working shifts reshuffled the draws and that find went. Bots never
  head for caches, where found armor comes from (2 opened in the whole run), nor buy armor. New item for that.
- 2026-11-05 Simulator bots raid for caches: `Bot._pick_goal` heads for the nearest stocked cache within `reach`
  of town (`World.stocked_caches`, shared with `/raid`), else a random point. 10 seeds x 2000: caches opened 2 -> 12.
- 2026-11-05 Level and worth after 7db073c: noise. Behaviour unchanged but one extra random draw per goal gives level
  1.88, worth 677, deaths 6.7 against 2.28, 713, 7.3, so 7db073c's 2.03, 669, 7.1 is inside it. Not loitering
  either: a new goal on arrival gave 1.93 and halved caches opened (a loiterer re-loots the refill). Reverted.
- 2026-11-05 Terrain on tcod: `noise` is gone; four seeded `tcod.noise` Simplex fields (Perlin drew axis-aligned
  blobs and repeats at 256 units), sampled a chunk at a time (`World._terrain_block`), thresholds refitted to the
  old shares (water 18%, grass 29%, mountains 3%). No repeat within 65,536 units, so the 2560-square repeat is gone
  too. Migration step 5 re-rolls an old save: new thresholds, its NPCs and store shelves dropped, everyone back in
  the starting town. The next deploy does that to the live world.
- 2026-11-05 Dearer hideout: `HIDEOUT_COST` $1000 -> $2000, x1.15 a level as before, so a level takes twice as long
  to pay for itself (the first ~16 hours, level 15 ~6 days). Bots never build one, so the simulators won't show it.
- 2026-11-05 No townspeople on the map: town squares draw just the town, the resident sprite is gone. Residents are
  still named in the map's info panel and on `/town status`.
- 2026-11-05 Names in the map's info panel are buttons: a click selects that actor and follows it, so one of a crowd
  on a square can be picked out (clicking the selected one's name re-centres after a drag).
- 2026-11-05 The map's info panel is a console: monospace, scrolling, each pick's description kept above the next
  (dimmed, the last 50), the live one at the bottom and scrolled to unless you've scrolled up to read.
- 2026-11-05 Simulator bots build hideouts: armed and in town, a bot buys the next level when it can keep $300 back
  to re-arm (`HIDEOUT_RESERVE`), salvage levels from salvage it holds; a `mean hideout level` metric. It's 0: none can pay.
- 2026-11-05 Simulator bots keep pets: armed and in town, a bot adopts one when it can keep `HIDEOUT_RESERVE` back (far
  raiders a dog, the rest a goat) and feeds it in the last quarter of its meal; a `pets kept` metric (1.0: all do).
  Deaths 7.5 -> 3.5 from the dogs (new item); worth 702 -> 674, the $300 spent and the milk never sold.
- 2026-11-05 Why no bot built a hideout: the bots, not the economy. Players start on $1000; bots earn $382 each per
  2000 ticks on average (kills, caches, encounters) and spend $329 on guns and ammo, $300 on a pet, $57 to deaths.
  The median bot earns $173 (hammer or fists), the rifle bots $1369-1878 ($500-650 an hour), so $2000 is a few
  hours of good raiding: at 10 seeds x 6000 ticks mean hideout level is 0.14. Price left as is; new item on re-arming.
- 2026-11-05 Why bots don't re-arm: they mostly don't end on hammers (3 of 60 do); they raid dry. A gun shot empty
  with no rounds left is a club (`ready_weapon`), and bots kept raiding on it. Now one goes home for a box when the
  home store has one it can pay for, from the stash if short: worth 674 -> 709, deaths 3.5 -> 3.0. Most dry time
  is a gun whose ammo the store doesn't stock (new item). Shopping only for guns it can feed was worse (worth 589):
  bots worked shifts instead, and a loaded gun, then fists and a dog, out-earns a shift.
- 2026-11-05 Dog bite halved: `PET_BITE_DAMAGE` 2 -> 1 (2 once happy). 10 seeds x 2000: deaths 3.0 -> 4.4, mean level
  2.73 -> 2.13, worth 709 -> 525: the dog's kills were much of the bots' income.
- 2026-11-06 Ammo with every gun: `Store.generate_store` adds a box of each shelf gun's caliber the roll left off
  (the hourly restock already put one of everything back, so this only covers a fresh shelf and a road trader).
  Server simulator DMs 165 -> 335 and death posts 25 -> 43 there are the random stream, not spam: traders shuffle
  and caches sample a `generate_store()` shelf, now longer, so its one seed played a different game (same message
  kinds, more NPC fights).
