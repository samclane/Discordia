# Roadmap

Backlog for `/dev-loop`. One line per item, roughly in priority order within a section. The loop picks the first
unchecked item it can finish in one sitting, checks it off, and appends a line under **Done**. Add new items at the
bottom of the right section, add sections when a theme emerges. Keep items small enough for one commit.

## Vibe: extraction idle

Cookie Clicker meets Escape From Tarkov. Towns are safe; everything past them is a raid. You go out, grab what
you can, and either make it back to a town (extract) or die and lose what you carried. What you bank builds a
hideout that earns while you're away, and the hideout pays for better kit for riskier raids further out. Numbers
always go up at home; the wilds are where you gamble them.

When choosing between items, prefer the one that tightens that loop: risk out there, safety and growth at home,
and a reason to check in on Discord a few times a day rather than grind for hours.

## Extraction idle loop (the core)

- [x] Stash: a per-player store of items and money kept in town (`/stash put|take|list`, only while standing in a
  town). Saved in `Database` with a round-trip test. Carried and stashed are now two different things.
- [x] Raid loss: dying out past the towns drops everything carried, not `DEATH_TAX` of the money. The stash is
  untouched. Say exactly what was lost in the death message.
- [x] Extract: stepping into any town from the wilds ends the raid and reports the haul (items picked up, money,
  XP since leaving). Track `raid_start` loot on the character; nothing to save, a restart mid-raid just ends it.
- [x] Secure pouch: one item slot that survives death, so a raid is never a total wipe (Tarkov's secure container).
- [x] Corpse run: what a raid death drops (`PlayerCharacter.lose_carried`) just vanishes. Leave it on the square
  for a while, for the owner to walk back and recover or for anyone else to loot. Needs an item container on `Space`.
- [x] Hideout income: `Base`/`BaseLevel` already exist. `/hideout build` in town for money; each level pays
  money per tick into the stash, whether the player is online or not.
- [x] Offline catch-up: save `last_tick` on the hideout and pay the missed ticks on load, so a restart doesn't eat
  idle income.
- [x] Hideout upgrades priced Cookie Clicker style (`base * 1.15 ** level`), and some levels cost a loot item
  instead of money so raids feed the idle side.
- [x] Show the idle numbers: income per hour and stash value on `/equipment` and `/me`.
- [x] Caches are the raid targets: their loot scales with `level` (distance), and `Cache.looted` resets on a timer
  instead of never/restart (see ponytail note in `GameSpace.Cache`).
- [x] Auto-raid: `/raid <minutes>` sends the character out unattended. Each tick it walks toward the nearest unlooted
  cache and fights what it meets; when time is up it walks home. DM the result: extracted with X, or died at Y.
- [x] Raid risk knob: auto-raids pick a depth (`/raid <minutes> <level>`); deeper pays more and kills more. Tune
  so the safe choice is boring but steady.
- [x] Save `PlayerCharacter.auto_raid` so a restart doesn't strand a character mid-raid with no message.
- [x] Extraction points out in the wilds (deterministic per chunk, like caches) so a deep raid doesn't mean walking
  all the way back to a town.
- [ ] Prestige / wipe: reset hideout and stash for a permanent income multiplier (Cookie Clicker ascension,
  Tarkov wipe). Only once hideout income visibly plateaus. (blocked: needs live numbers showing the plateau, and
  a call on the multiplier and on what a wipe resets: level, gear, the pouch?)

## Gameplay loop (make it a game)

- [x] Earn money: NPC kills drop currency (`NPC.on_death` -> `PlayerActionResponse`); stores are the only sink today and players start with 1000.
- [x] `/attack` only ever hits players (`World.pvp_attack`): NPCs standing on the map are unkillable, so their money is unreachable outside wilds events.
- [x] `NPC.generate(1)` rolls ~0 hit points: `(50 // 2) * (level // 2)` is 0 for level 1, so tick-spawned raiders die to a breeze.
- [x] Wilds difficulty outruns the player: a far wilds rolls `normal(level)` enemies of `25 * level` hit points, while a player gains only `HIT_POINTS_PER_PLAYER_LEVEL` (10) per level and no extra damage at all. Scale something the player earns, or cap wilds level by distance.
- [x] Death has a cost: `World.handle_player_death` drops or taxes inventory/currency instead of a free respawn.
- [x] XP and levels on `PlayerCharacter`; wilds `level` and `NPC.generate(level)` already exist, hook them to player level.
- [x] `EncounterEvent` is a stub (`{"<test>": "<test>"}`): make it a real choice (talk / rob / ignore) with outcomes.
- [x] `MerchantEvent` is a stub with no items: sell a random `Store.generate_store()` slice at a markup.
- [x] `CombatEvent.run` can loop forever when player damage is 0 (see WARN comment): cap rounds or make a 0-damage weapon end the fight.
- [x] `CombatEvent.run` never checks `ProjectileWeapon.is_empty`, so guns fire forever into negative ammo (found by
  `test_simulation.py`; drop its `KNOWN` entry once fixed). Decide what an empty gun does mid-fight: reload, fists, or flee.
- [x] Levels outrun the map: in a 3000-tick simulation bots reach level 4-30 without going past danger 5. Tune XP
  or danger once Extract exists. (Deaths are now mostly wilds fights at danger 3-5, which is the risk working.)
- [x] Rest / heal outside towns (camp command, slow regen per tick) so a hurt player is not forced to walk home.
- [ ] XP is slow now that a cleared wilds square can't be re-looted: over 3000 simulated ticks (seed 0) bots end
  at level 1-5, where the same run gave 4-7 before. Re-looting dead enemies had been most of the XP. Watch real
  players; if levels stall, raise kill XP (`PlayerCharacter.loot`) rather than bring the farm back.
- [ ] Faction consequences: Soldier (East/West) vs Raider should change NPC hostility and store prices somewhere.
  (blocked: no town recruits `RaiderClass`, so nobody can be one, and every military base hands out the same
  `Soldier` with no East/West side, saved by class path alone. Decide how each faction is joined first.)

## NPCs and world

- [x] NPCs fleeing should step away on the grid (`Behavior.Fleeing`, ponytail note) now that NPCs move in `World.tick`.
- [x] Non-Raider NPC types, first half: animals from `BodyType` with their own sprite.
- [x] Non-Raider NPC types, second half: merchants and guards in towns (overlaps Town population below).
- [x] NPCs chase players in sight instead of random walks (greedy steps, not A*: see `NPC.step`).
- [x] Town population: named NPCs that stay in town, give flavor text on `/town status`.
- [ ] Town residents are words only (`Town.residents`). Put them on the map as NPCs that never leave town, drawn
  from Kenney's people tiles, if towns feel empty; they'd need to be skipped by `World.attack` and the NPC tick.
- [x] Wilds respawn / cooldown so a single wilds tile is not farmable every step.

## Persistence

- [x] Save NPCs (position, hp, type) so a restart does not wipe the world's population.
- [x] Save store inventories and prices per town.
- [x] Save weapon state (ammo loaded, jam) for equipped projectile weapons, and how full each ammo box is
  (`Items.Ammo.quantity`): both come back full after a restart today.
- [ ] A store's shelf is saved by class path alone, so a part-used ammo box sold to a store comes back full
  after a restart. Save `_item_state` per shelf item too if anyone farms it (ponytail note on `Items.Ammo`).
- [ ] Schema migrations are a column-presence check in `Database._migrate`. Fine for one column; if a change ever needs to rewrite data, switch to `PRAGMA user_version` and numbered steps.

## Discord UX

- [x] `/look` should list visible NPCs and players by direction, not only render the image. `Wilds.level` now exists, so it can also say how rough the place you are standing in is.
- [x] Combat and event results are long: batch `PlayerActionResponse` text into one embed per order. (stale: a
  move is already one message, and since fights summarise per enemy the longest of 300 level-8 fights is 961
  characters, under Discord's 2000. An embed would be cosmetic.)
- [x] Nothing ever shows a player their money: `/equipment` lists gear only, and the store prints prices without a balance. Add currency to `/equipment`.
- [x] `/help` command generated from the Cog's command descriptions.
- [x] Ephemeral errors everywhere (`_send(..., ephemeral=True)` is inconsistent).
- [ ] Refusals from deferred commands (`/move`, `/attack`, `/choose`, `/look`) still show to the whole channel:
  Discord gives the first followup after a public defer the defer's visibility, whatever `ephemeral` says.
  Try `interaction.delete_original_response()` then an ephemeral followup in `cog_app_command_error`, checked
  against real Discord (the simulator's fake honours `ephemeral` on that followup, so it can't tell).
  (blocked: needs a live Discord server to check what that followup does; the loop has none)
- [x] Channel announcements for deaths and town arrivals instead of only DMs.
- [x] DM spam (found by `test_server_simulation.py`; drop its `KNOWN` entry once fixed): a raider standing on you
  DMs "X hits you for 2 damage." every tick (5s) until one of you leaves or dies, a phone notification each time.
  396 of 470 DMs in a 500-tick run. Options: DM only the first hit of a fight and the death (the rest still goes
  to `add_news` for `/me`), or batch a fight into one DM every N ticks.

## Rendering

- [x] Terrain names still say `sand`/`mountain` (`/look`, web map hover) though they're drawn as paving and rooftops.
- [x] Actor sprites are the old style; the Kenney sheet has matching characters (tiles 23-26, 185, 266, 347, 428).
  (stale: side by side, the raider, soldier and wanderer sprites already are those characters in the sheet's
  palette, recoloured with helmets and hard hats. Only the unused `null_actor.png` placeholder isn't.)
- [x] Random sprite generation per `BodySize` (TODO in `Actors.py`); NPCs all share `null_npc.png`.
- [x] Show `Space.remains` (a corpse run's pile) on the web map and in `/look`, so you can find your way back.
- [x] Extraction points are drawn (a taxi) but the web map's hover and `/look` don't name them, and nothing tells
  a player where the nearest one is. A bearing to it in `/look`, like `/choose talk`'s directions to a town.
- [ ] Web map: SSE push instead of 2s polling (ponytail note in `WebApp.py`) if it feels laggy.
- [x] Display scrolling for worlds larger than the window (TODO in `ConfigParser.py`).

- [ ] Chunks are never unloaded (~0.4 MB each, ponytail note in `World.__init__`). Evict chunks with nobody in
  them once a long-running server's memory says so; store sales in them would need saving first.
- [ ] Terrain repeats every ~2560 squares (`pnoise3` period, ponytail note in `World._terrain_at`).

## Cleanup

- [x] Armor rolls its coverage randomly and `base_value` is `10 * armor_count`, so a piece worth 0 is
  free from any store. Give every item a floor price.
- [x] An equipped item stays in the backpack too (`/inventory equip` doesn't move it), so `Database.save` writes
  it twice, as a slot row and a backpack row, and a restart hands back two.
- [ ] `GameSpace.Base`/`BaseLevel` are never placed or used: the hideout is `PlayerCharacter.hideout_level`. Delete them.
- [ ] A wilds trader only sells. `Store.buy_item` already exists, so `/trade sell` is a few lines if
  players want to offload loot without walking to a town.

- [x] `Space.closest` returns `sorted(...)[0 : size - 1]`, so the default `size=1` hands back an empty
  list. Nothing calls it; either fix the slice or delete it.

- [x] `Space.__eq__` ignores terrain but `Space.__hash__` includes it, so equal spaces can hash differently. Set
  operations on spaces (`World.get_players_in_region`) are quietly relying on identity today.

- [ ] Delete `Items.FullyImplemented` marker (FIXME): `Store.generate_store` should pick from JSON data instead of subclass scanning.
- [ ] `GameSpace.generate_map` region around the `FIXME Ugly function` note at ~L685.
- [x] `NPC.generate` passes `None` as `parent_world`; `World.add_actor` should own that assignment consistently.
- [ ] README: store buy/sell are no longer placeholders; document `-W` web map and `/attack` DMs.

## Done

- 2026-10-30 Worn from the backpack, saved once: an item equipped with `/inventory equip` stays in the
  backpack by design (`lose_carried` already counted it once), but `Database.save` wrote it as a slot row and a
  backpack row, so a restart handed back two. It's now one backpack row whose JSON state names the slot it's worn
  in; items worn but not carried (fists) keep slot rows. Saves from before the fix still hold both copies, and a
  real second helmet can't be told from a duplicate, so they're left as they are.

- 2026-10-30 Naming the way out: `/look` outside a town says the nearest way out, a town by name or an
  extraction point, with squares and bearing. The web map's hover and click now name extraction points and caches
  (a `places` list in chunk JSON) and say what they're for. `ART_VERSION` 6.

- 2026-10-30 Piles on the map: `World.piles` remembers where raid deaths left things and `live_piles()` keeps
  the ones still there (not picked up, not rotted, not empty). `/look` lists a pile in view like anyone else
  ("Vex's things ($300, Helmet), 2 squares east"), and the web map draws each as a black bag from the Kenney
  sheet (`Sprites/Structures/remains.png`), sent with the actors as `kind: "remains"`; clicking says what's in it.

- 2026-10-30 Sprites by body size: a small animal (rat, feral cat, crow, fox) draws as a new hand-drawn rat,
  `Sprites/Actors/small_animal.png`; large ones keep the dog. "NPCs all share null_npc.png" was stale: raiders
  and animals have their own, and plain NPCs only live inside wilds events, never on the map. Also closed the
  Kenney actor-sprites item as stale.

- 2026-10-30 Terrain labels: `Terrain.label` is what players read, matching the city art (paving, park, canal,
  rooftops), in `/look` and the web map's hover. `name` stays the internal key the generator, autotiler and
  `BLOCKS` go by. `ART_VERSION` 5, so browsers refetch chunk JSON with the new words.

- 2026-10-30 Channel announcements: `World.announcements` collects a player's raid deaths (where, how
  dangerous, and what lies there for anyone to loot) and extractions that brought something home; the cog
  posts them once a tick, one message per server, in the new opt-in `GuildSettings.announce_channel` (picked on
  the `/settings` page). A player's news goes to the servers they've used a command in (remembered by
  `interaction_check`, in memory). The digest shares the new `_post`.

- 2026-10-30 Ephemeral errors: the refusals that still went to the whole channel are now private: a
  purchase you can't afford (it said "Not enough money." even for a bad index), a store-less town in list, buy
  and sell, and a `/town recruit` that doesn't take. Successes and plain information stay public. Deferred
  commands are the exception, noted as a follow-up.

- 2026-10-30 `/help`: every slash command with its description, `/register` first, read from the command
  tree so a new command lists itself. One ephemeral embed: the list alone is near the 2000-character message
  limit, and an embed takes 4096. Needs no character. (Also closed the one-embed-per-order item as stale.)

- 2026-10-30 `/look` lists who's in sight, nearest first: name (raider/player tagged), squares away and
  compass bearing ("Vex (raider), 2 squares east"), and says how rough the square is: wilds by their level,
  open ground by `World.depth_at`, a town as safe. Worded once in `WorldAdapter.look_text`.

- 2026-10-30 Weapon state: each item row has a migrated JSON `state` column with what changes in play
  (`Database.ITEM_STATE`: rounds loaded, the Sten's jam, the Garand's ping, a belt's ramp) and an ammo box's
  `quantity`, which is restored by draining a fresh box through `Ammo.take` so its price drops with it. An empty
  gun stays empty and a half box stays half through a restart, worn, carried, stashed or pouched.

- 2026-10-30 Store stock is saved: a store that's been bought from or sold to (`Store.traded`) gets a row
  in the new `store` table, its shelf as a JSON list of class paths in order (players buy by #). Untouched stores
  regenerate from the seed as they were, so they cost nothing. Prices weren't saved: a town's `price_ratio` never
  changes from 1.0.

- 2026-10-30 Save NPCs: a new `npc` table holds each roaming NPC's class (Raider, Animal), body, name, hit
  points, money and square, restored through `_resolve` like items. A wounded raider comes back wounded, an animal
  still flees. Event NPCs aren't saved: wilds events restock on a square's next visit anyway.

- 2026-10-29 Wilds cooldown: after any real event a wilds square goes quiet for `WILDS_QUIET_TICKS` (an hour
  at a 5-second tick), then restocks with fresh events. It also fixes a farm: `CombatEvent` re-ran `loot` on
  enemies already dead from an earlier visit, paying their XP (and a kill) every step back onto the square.
  `quiet_until` isn't saved, but neither are the events: a restart restocks every square on its next visit.

- 2026-10-29 Town population (and the merchants-and-guards half of NPC types): every town has a shopkeeper,
  an innkeeper and a guard (`Town.residents`), each named and with a line from `TOWNSFOLK`, and `/town status`
  introduces them along with the population. Rolled on their own seed from the town's position rather than in
  `generate_town`, which would have shifted chunk generation and moved every saved map. Words only, not map NPCs.

- 2026-10-29 Animals: `Actors.Animal` (a rat, stray dog, wild boar... on a `SmallAnimal`/`LargeAnimal`
  body) starts in `Behavior.Fleeing`, so it never hits and steps away from any player in sight with no new tick
  logic. No money, but a kill is experience. A third of tick spawns (`ANIMAL_SHARE`) are animals, under the same
  cap. NPC bodies come from a per-class `BODIES`, so raiders and event strangers are always `Humanoid` (they used
  to roll any body). Hand-drawn dog sprite `Sprites/Actors/animal.png`. Factions marked blocked.

- 2026-10-29 Rest outside towns: `/camp` (not in a town; there the inn is free) sets
  `PlayerCharacter.camping`, and `World.advance` heals a camper `CAMP_HEAL_SHARE` (5%) of max every
  `CAMP_HEAL_TICKS` (a minute), so full in twenty minutes. Moving or dying breaks camp. Saved as a migrated
  `character.camping` column, and since healing is in `advance`, a load heals campers for the downtime too.

- 2026-10-29 Levels outrun the map: a kill below your level pays its share of your level in XP (a level-1
  raider gives a level-4 player a quarter), so farming the wilds by town stops paying and levels keep pace with
  how deep you raid. Over 3000 ticks on seeds 0/1/2 the top bot went from level 14/23/7 to 7/8/4, against max
  danger 5. `NPC.level` (from hit points) replaces the copy in `EncounterEvent._rob`. Prestige marked blocked.

- 2026-10-29 Extraction points: each cache cell (`CACHE_CELL` chunks a side) rolls `EXTRACT_CHANCE` for an
  `Extract` on a plain square of one of its middle chunks, seeded like caches. Stepping on one takes any remains
  there, then drives you to the nearest town, which ends the raid with the usual haul. Auto-raids head home by the
  nearest town or extraction point. Drawn with Kenney's taxi; `ART_VERSION` 4. The cell roll is shared with caches
  (`World._cell_picked`).

- 2026-10-29 Auto-raid survives a restart: `auto_raid`'s home-at tick and depth are two migrated, nullable
  `character` columns. Deaths aren't saved, so a loaded raid counts them from the load. The clock runs on by the
  downtime, so a raid due home while the server was down heads home on the first tick. Anyone loaded outside a
  town also gets a fresh `raid_start`, so the walk home still reports a haul (what's gained since the restart).

- 2026-10-29 Raid risk knob: `/raid <minutes> [depth]` (default 1) only targets caches at or under that level
  and, with none known, explores out to that depth (`World.depth_at`, distance-only `danger_level`) and wanders
  there, stepping back if it strays deeper. Measured, a level-1 musket with ammo on 30 seeds, 20-minute raids:
  depth 1 never dies and brings home ~$84; depth 3 brings ~$224 and dies 11 in 30; depth 5 dies 23 in 30. No
  tuning needed for safe-and-steady. Earlier "27 of 40 die" was mostly an empty musket fighting with fists.
  Deeper only out-earns once a raid is long enough to spend time out there, not walking.

- 2026-10-29 Auto-raid: `/raid <minutes>` (from a town) sets `PlayerCharacter.auto_raid`, and each `World.tick`
  walks it (`_auto_raid_step`): attack an NPC on the square, else step for the nearest stocked cache (the new
  `World.caches`) or outward if none is known, and for the nearest town once time is up or below
  `AUTO_RAID_RETREAT` health. One event when it ends, so one DM: the extraction haul, or the death and where
  things fell. `NPC.step` moved to `Actor` for it and now hands back the move's results.

- 2026-10-29 Caches are raid targets: money already scaled with level; now the piece of kit is the dearest of
  `level` picks from a store's stock, and the salvage is 1 + `level // CACHE_LEVELS_PER_SALVAGE` pieces. `looted`
  became `looted_at` (a `World.ticks`), and an emptied cache restocks after `CACHE_REFILL_TICKS`, four hours at a
  5-second tick. Still not saved: a restart refills them early.

- 2026-10-29 Discord server simulator (`test_server_simulation.py`): members on two fake servers use the real slash
  commands, and every message the bot sends is checked for spam, posts outside allowed channels, leaked links, mass
  pings and unanswered interactions. It found two: a character named `@everyone` pinged the whole server (the bot
  now sends with `AllowedMentions.none()`), and a raider on you DM'd every hit, every 5 seconds. Now a fight DMs its
  first hit and its death; the blow-by-blow still goes to `/me`.

- 2026-10-29 Idle numbers: `/equipment` and a new Hideout card on `/me` show income per hour, the stash's worth
  (`PlayerCharacter.stash_value`: money plus item values) and the next level's price, worded once in
  `WorldAdapter.hideout_text`. Per hour needs the tick length, which the running cog now hands the adapter
  (`tick_seconds`). Also fixed `/me`'s money note, which still said a death costs a quarter.

- 2026-10-29 Hideout pricing: level n costs `HIDEOUT_COST * 1.15 ** n`, except every 5th, which costs `n // 5`
  `Items.Salvage` and no money. No item a store sells could stand in (the dearest is $370, and buyable anyway), so
  salvage is a barter item from the new `data/barter.json`, never stocked by stores and found in every cache.

- 2026-10-29 Offline catch-up: the world table saves `World.ticks` and the save time, and `Database.load` runs the
  clock on by the downtime (`World.advance`, at `tick_seconds` a tick) so every hideout is paid each pay day it
  missed. Per world, not per hideout: they all share one pay schedule. `tick()` pays through `advance(1)` too.
  `_migrate` now takes (table, column, type), since the world table needed columns as well.

- 2026-10-29 Hideout income: `/hideout build` (in town) buys a level for a flat `HIDEOUT_COST` ($1000), carried
  money first and the stash after. Every `HIDEOUT_PAY_TICKS` world ticks each level pays `HIDEOUT_INCOME` into the
  stash, $120 an hour at a 5-second tick, online or not. The hideout is a `hideout_level` on the character, like the
  stash, not the unused `Base` map square. Saved as a migrated `character.hideout_level` column.

- 2026-10-29 Corpse run: a raid death leaves what it stripped (`lose_carried` now returns the items and money)
  on the square as `Space.remains`, for `REMAINS_TICKS` (an hour at a 5-second tick, counted by the new
  `World.ticks`). Whoever steps on it first takes the lot, owner or not; a second death there adds to the pile.
  The death message says where it fell. Dropped gear comes back unequipped. Not saved: a restart loses every pile.

- 2026-10-29 Secure pouch: `PlayerCharacter.pouch` holds one item that a raid death leaves on you, filled from
  the backpack anywhere with `/inventory pouch <index>` (the old one goes back to the pack; no index empties it).
  A pouched item is unequipped, so it can't be both worn and safe. Saved as an item row with `slot = 'pouch'`,
  shown in `/inventory list` and `/me`, and counted in the extraction haul.

- 2026-10-29 Extract: stepping from anywhere outside a town into one ends the raid and says what it brought home
  (new backpack items, money and XP since you last left a town). `PlayerCharacter.raid_start` is snapshotted on
  every step out of a town and thrown away by a death, so dying never reads as an extraction. Not saved: a restart
  mid-raid just ends it quietly.

- 2026-10-29 "Roaming raiders" weren't the problem: the simulator credited each death to the square the bot stood on
  *before* its fatal move, so wilds fights read as open-ground deaths. It now records where each death happened and
  what caused it (`died_at`). The real killer on the map was an empty gun: `/attack` refused with "empty, no rounds"
  and you couldn't punch either (unequipping leaves an empty hand, not fists), so one level-1 raider could
  grind down a level-19 character. `PlayerCharacter.ready_weapon()` reloads from the pack or falls back to fists,
  for `/attack` and wilds fights alike. Map-NPC deaths over three seeds: 26 to 6. Bots also take stash money to
  re-arm after a death now, instead of raiding on fists forever.

- 2026-10-28 Ammo: guns had magazines and `reload`, but no `Items.Ammo` was ever made, so `CombatEvent` fired
  forever into negative rounds and `/attack` went dead after one magazine. A box per caliber now lives in
  `data/ammo.json` (`Weapons.Ammo9mm` ...), stocked by stores like any `FullyImplemented` item and priced by
  rounds left. An empty gun reloads from the pack on `/attack` and mid-fight; with nothing to load, a wilds fight
  goes on with fists. Every combat round deals at least 1, so a weak weapon can't loop a fight forever.
  `/inventory equip` says no to an ammo box instead of raising. Also from the Cleanup list: `Space.__hash__` now
  matches `__eq__` (x, y only), `Space.closest` returns `size` spaces, not `size - 1`. Two items were stale:
  nothing a store stocks is priced $0 (cheapest is $10), and `World.add_actor` already sets every NPC's world;
  event NPCs never join one.

- 2026-10-22 Raid loss: dying anywhere but a town loses carried money, the backpack and worn gear
  (`PlayerCharacter.lose_carried`), leaving bare fists; `DEATH_TAX` is gone. A town death costs nothing. Every
  death message, and the `/me` sheet, says what was lost (`last_death_loss`). The stash is untouched.

- 2026-10-22 Stash: `PlayerCharacter.stash`/`stash_currency`, moved with `/stash put|take [item] [money]` and
  read with `/stash list`, all gated on standing in a town. One stash per player, shared by every town. Saved as
  item rows with `slot = 'stash'` plus a migrated `character.stash_currency` column. Death already only taxed
  carried money, so the stash is safe today; the next item makes carrying actually risky.

- 2026-10-12 Raiders hunt: one that sees a player outside a town (`NPC_SIGHT`, 6 squares) steps toward them each
  tick, and the first time it picks someone they're DM'd where it is, while there's room to run (a raider is no
  faster than you). Wounded raiders (`Behavior.Fleeing`) step away instead of standing still. Only NPCs within
  `NPC_AWAKE_RADIUS` (a chunk) of a player act, NPCs never step into unloaded chunks (a live server had gone 9 to
  366 chunks in an hour from raiders alone), and the cap is one raider per 40 wilds squares, about 2 a chunk.
  Melee reaches the square beside you: `/attack` always takes a direction, and every melee attack used to be
  refused with "You need a ranged weapon", so a raider next to you could be seen and never hit.

- 2026-10-11 Urban tiles: terrain is drawn from Kenney's RPG Urban pack, each square built from four 8px quarters
  picked by its eight neighbours (`Terrain.neighbours`, replacing the 9-way `orientation`), so parks, canals and
  rooftops get proper kerbs, inside corners, strips and islands. Ground is paving; wilds pick one of eight props by
  position; towns are a shopfront. `WebApp.ART_VERSION` is in the ETag so browsers drop cached old art.

- 2026-10-11 Minecraft-sized worlds: the map is generated a 32-square chunk at a time where something walks,
  each chunk keyed on (seed, chunk) so it regenerates identically in any order and leaves the game RNG alone.
  Spawn is the town nearest the middle; wilds danger is a level per 32 squares from it instead of a share of the
  map; wilds roll events on first visit (2 MB a chunk down to 0.4). The web map serves explored chunks only
  (`/chunk/x/y.png|json`, `/explored.json`), and the client places everything relative to the spawn so 60M
  squares stay inside what a browser can lay out. `default.ini` is now 60,000,000 a side.

- 2026-09-20 `MerchantEvent` is real: a trader on the road carries up to `MAX_STOCK` items from
  `Store.generate_store()` at `MARKUP`, browsed and bought with the new `/trade`. `pending_encounter`
  became `pending_event` so an encounter and a merchant share one slot, each command checking which
  is actually waiting.

- 2026-09-16 `EncounterEvent` is real: a stranger on the road parks a pending choice on the character and
  waits for the new `/choose` (talk for directions to the nearest town, rob for a contest of levels,
  ignore to walk on). Moving clears it. Added `GameSpace.bearing`, which the `/look` item can reuse.

- 2026-09-15 Wilds difficulty: levels were measured from a placeholder town at (0, 0) rather than the spawn,
  so most of a map was level 5+ and a starting character had nowhere survivable to fight. `World.danger_level`
  now spans 1 to `WILDS_MAX_LEVEL` by share of the distance to the furthest corner, and wilds are populated
  after the starting town is chosen. Measured: fists clear the wilds next door, a hammer at level 3 clears
  midway, a rifle at level 5 clears the far end.

- 2026-09-15 XP and levels: kills pay experience through `PlayerCharacter.loot`, a flat 100 per level, each
  level adding 10 to the hit point ceiling and handing over the difference. `/equipment` became a real
  character sheet (level, experience, money, health), which also closed the money-visibility item.
  `Database._migrate` adds the new column to save files that predate it.

- 2026-09-14 Death has a cost: dying leaves `DEATH_TAX` (a quarter) of carried money behind, and both places
  that narrate a death say what it cost. Skipped dropping inventory: items on the ground need a container on
  `Space` that does not exist yet.

- 2026-09-14 NPC hit points: `HIT_POINTS_PER_LEVEL * max(level, 1)` replaces the integer-floored formula that
  gave level 1 an average of 0.7 hit points (a third of them dead on arrival) and made levels 2 and 3 identical.

- 2026-09-14 `/attack` hits NPCs: `World.pvp_attack` became `World.attack` and targets players and NPCs alike,
  paying out the corpse through a shared `PlayerCharacter.loot`. Fixed `Space.__eq__` raising on a despawned
  actor's `None` location, which the new targeting walked straight into.

- 2026-09-13 Earn money: generated NPCs carry `CURRENCY_PER_LEVEL * level` on average, and `CombatEvent` pays it out
  once per kill alongside the loot. Also guarded `World.generate_map` against rolling zero towns, which an extra
  random draw exposed on small maps.
