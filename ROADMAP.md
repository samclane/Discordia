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
- [x] Prestige / wipe: `/hideout prestige` (in town, hideout level 15+) resets the hideout to 0 and empties the
  stash (money and items) for a permanent +10% hideout income per prestige. Character level, worn gear, the
  backpack and the pouch are kept. Saved as a migrated `character.prestige` count. (Decided 2026-10-30: by level
  15 a new level takes ~3 days of income to pay for itself, where the curve flattens.)
- [x] Hideout as a place (asked for 2026-11-02: "player hideouts with stashes, trophies, with their own rendered
  display"). Split into these, in order:
  - [x] A rendered hideout: `/hideout` (and `/me`) shows a picture of it, Pillow like `DesktopApp`, rooms that grow
    with the level and the stash on its shelves.
  - [x] Trophies on its wall: the achievements earned (they have icons since f53ef0d) and the best haul so far.
- [ ] Pets (asked for 2026-11-03: "a tamagotchi-like pet for the player that can provide resources in some way:
  fetching, milking, combat"). A reason to check in a few times a day, kept at home like the hideout. Split:
  - [x] A goat: `/pet adopt` in town buys one, `/pet feed` in town keeps it fed for half a day, and while fed it
    puts goat's milk (a barter item, sold in town) into the stash every hour, downtime included. `/pet status`
    says how it is. Saved, as a migration step.
  - [x] Neglect and care: a goat left hungry for days wanders off; one fed on time gives more. The tamagotchi part.
  - [x] A hungry goat says nothing until you ask `/pet status`. A DM when it goes hungry (once, like a fight's
    first hit) would be the tamagotchi's beep, and the reason to check in.
  - [x] A dog that comes on raids, first half: fetches (a chance of salvage on a quiet step). One pet each, goat or
    dog (`/pet adopt kind:`), fed and cared for the same way.
  - [ ] The dog's second half: bites what you fight (a little damage on your turn in a fight while it's fed).
  - [ ] More kinds by role (a donkey that carries more?), once the goat and the dog show what players use.

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
- [x] XP is slow now that a cleared wilds square can't be re-looted: over 3000 simulated ticks (seed 0) bots end
  at level 1-5, where the same run gave 4-7 before. Re-looting dead enemies had been most of the XP. Decided
  2026-10-30: extracting with a haul pays 10 XP per danger level of the deepest square reached on that raid
  (track the depth on the raid, like `raid_start`), so bringing loot home is what levels you. Kill XP unchanged.
- [x] More classes: each trade town trains one, with one perk (`PlayerClass.perk`).
- [x] More tile types: ruins (cover) and plazas (exposed), carved out of paving.
- [x] Ruins and plazas made raids deadlier in simulation (374c68f): deaths 16 -> 17 (seed 0) and 18 -> 25 (seed 1),
  mean worth 592 -> 468 and 864 -> 768. Simulator bots don't know to cut through ruins or skirt plazas, so they only
  meet the downside; real players can. Teach the bots that first, then see if plazas need to be 1.5x, not 2x.
- [x] Extract XP (4f2b1ba) lifted levels as meant (mean 1 -> 2.17 seed 0, 1.83 -> 3 seed 1), but seed 1 got
  deadlier: deaths 25 -> 29, mean worth 768 -> 643 (seed 0 went the other way, 17 -> 14 and 468 -> 578). Likely
  levelled bots raiding deeper; check the deaths-by-danger split on a longer run before tuning anything.
- [x] Two seeds can't tell a death change from noise: over 10 seeds x 2000 ticks one build's deaths ranged 1-29
  a seed, and 462a11b moved seed 0 14 -> 18 and seed 1 29 -> 28 with no real effect. Let the simulator take
  `--seeds N` and record the means, so `sim_history` drift on deaths and worth means something.
- [x] Simulator bots never `/town recruit`, so class perks don't show in `sim_history` (05429a6 moved nothing).
  Have each bot take the class of the first trade town it rests in, so the drift numbers cover them.
- [x] Simulator bots pick `/choose rob` a third of the time at random, so since 6aed7f2 64% of them end a run as
  Raiders and trade classes fell 0.62 -> 0.18 (1323bb6 split the metric). Give bots a stance (some never rob)
  so both the trade perks and the coming Raider-faction rules show in `sim_history`.
- [x] Since fc3f783 (raiders spare Raiders) deaths rose 10.8 -> 12 a seed. Deaths to raiders on the map fell
  6 -> 4 over 10 seeds as meant, but wilds-fight deaths rose 101 -> 115, mostly Raider-class bots (19 -> 26):
  likely they stay out longer now nothing on the map wears them down. Check a longer run; if it holds, wilds
  fights may want to spare Raiders too (`CombatEvent` spawns raiders). Checked 2026-10-31 over 10 seeds x 5000 ticks
  (d15fd3f): it doesn't hold. Per 1000 bot-ticks out of town Raiders die in wilds fights at 0.92, everyone else
  at 1.01 (9.9 vs 12.1 per 1000 ticks on a wilds square), and none of their 70 deaths were to map NPCs. The rise
  was counts, not rates. Left as is; wilds fights spawn plain `NPC`s anyway, which `World.spares` never covers.
- [x] Since d15fd3f deaths rose 10.5 -> 12 a seed (11.8; 10 seeds x 2000 ticks) and max danger fell 5.1 -> 4.8.
  Achievements change no rules, but the same commit made stores stock armor, which re-rolls every chunk's towns and
  wilds (and gives bots armor to buy). Likely the new maps, not a balance change: compare deaths by danger on a
  longer run before tuning anything. Checked 2026-10-31 against b559d70, 10 seeds x
  2000 and 5000 ticks: starting stores are identical (bots never buy armor), and without seed 1 the 5000-tick
  means are 24.4 vs 24.1 deaths. Seed 1's new map put one bot in a death spiral: broke ($0 + $8 stashed from tick
  ~500), bare-fisted, level 1, still raiding at full reach, 34 deaths (28 with fists) where the old map's run had 11.
- [x] No way back from broke: a death strips all carried money and gear, and with an empty stash and no hideout
  a player is left with fists (2 dmg), which lose the fights that would pay for a gun. Needs a decision on the
  floor: a free starter weapon from the starting town's store when you own none, a loan, or fist-safe ways to
  earn (caches already pay). Found as one simulator bot's 34-death spiral on seed 1 (see above). Decided 2026-11-02:
  a non-combat way to earn, like gathering or odd jobs in town. Split into these, in order:
  - [x] Odd jobs: `/town work` in any town pays a small wage for a stretch of ticks spent there, enough to buy the
    cheapest weapon ($75) in an hour or two, never enough to beat raiding.
  - [x] Gathering: something to pick up out in danger-1 wilds without a fight (firewood, scrap) to sell in town.
  - [x] Simulator bots never `/town work`, so the odd-jobs floor moves nothing in `sim_history`. Have a broke,
    bare-fisted bot work shifts until it can buy the cheapest weapon, and check seed 1's spiral bot climbs out.
- [x] Stores never restock: what's bought is gone for good. Over 5000 ticks on seed 1 the starting town sells out
  of guns, so a bare-fisted player there has nothing to work toward (9060 of 11025 simulator `work` orders, before
  the bots learned to skip it). Restock sold-out shelves on a timer, like caches (`CACHE_REFILL_TICKS`), from
  `Store.generate_store`; a saved shelf (`traded`) would need the refill time saved too.
- [x] Since a166029 (bots work shifts) mean worth fell 815.5 -> 761.9 and mean level 1.97 -> 1.9 (10 seeds x
  2000 ticks), while deaths fell 9.8 -> 9.4 as meant. A broke bot in town earns $48 an hour working, less than
  bare-fisted danger-1 raids paid it (caches, XP). Decide whether that's the floor working (safe and boring, as
  decided) or `WORK_WAGE` is too low; compare a bot's earnings per hour working vs fist-raiding before tuning.
  Checked 2026-11-02 over the same 10 seeds x 2000 ticks, per hour a bot spends bare-fisted: fist-raiding at
  e78aadb earned $0, 0 XP and 1.7 deaths; working at a166029 earns $47 and no deaths. The wage is not too low. Worth
  is cash only, and a bot that works its way to a gun spends the cash on it; working bots also skip the step
  draws, reshuffling the rest of the run. Left as is.
- [x] Since 3dc3036 (stores restock) deaths rose 9.4 -> 10.1 a seed and mean level fell 1.9 -> 1.77 (10 seeds x
  2000 ticks); class shares moved too (raiders 0.25 -> 0.3). Building restocked items draws from `random` (armor
  rolls its coverage), so every run reshuffles after tick 720; re-armed bots also raid more. Compare deaths by
  danger on 10 seeds x 5000 ticks against a166029 before tuning anything.
  Checked 2026-11-02, 10 seeds x 5000 ticks, a166029 vs 1e1b531: deaths 16.3 vs 16.5 a seed with the same split by
  danger (mostly 3-4), and deaths bare-fisted 14 -> 0. But mean level 3.25 -> 2.38 across 8 of 10 seeds: bots buy
  the cheapest gun, and a restocked shelf always has the Stechkin (4 dmg) back, so mean damage held fell 11.06 ->
  8.56. A bot habit, not a game problem: see the next line.
- [x] Simulator bots buy the cheapest gun a store has (`Bot.order`, `_cheapest(town, Weapons.Weapon)`), and since
  stores restock (3dc3036) that's always the 4-damage Stechkin, so `sim_history` levels sank. Have a bot buy the
  most damaging gun it can afford (with its ammo, keeping walking-around money), as a player would.
- [x] Simulator bots raid at their full `reach` bare-fisted and broke. Have an unarmed bot stay on danger 1 (or
  go for caches) until it can afford a weapon, so `sim_history` deaths measure the game, not one bot's spiral.
- [x] Faction consequences, decided 2026-10-30. Split into these, in order:
  - [x] Joining: winning a `/choose rob` or killing another player makes you a Raider (`RaiderClass`). A
    military base's recruit records its side (East/West) on the character, a migrated `character.side` column.
  - [x] Raider NPCs neither hunt nor hit Raider-class players (the NPC tick's targets and `prey_in_sight`).
  - [x] Soldiers pay 20% less at their own side's military base store and 20% more at the other side's.

- [x] Simulator bots never recruit at a military base (only trade towns), so soldier prices (af6fce8) and sides
  moved nothing in `sim_history`. Have a share of bots enlist at the first base they rest in, so the side rules
  show in the drift numbers.

- [x] Simulator bots never equip what they find, only what they buy, so cache-only chest armor (7710272) moved
  nothing but the random stream in `sim_history` (worth 838 -> 811, level 2.05 -> 1.97, deaths 9.8 -> 9.7). Have a
  bot wear found armor that beats what it has on, so armor shows in the drift numbers.

## NPCs and world

- [x] NPCs fleeing should step away on the grid (`Behavior.Fleeing`, ponytail note) now that NPCs move in `World.tick`.
- [x] Non-Raider NPC types, first half: animals from `BodyType` with their own sprite.
- [x] Non-Raider NPC types, second half: merchants and guards in towns (overlaps Town population below).
- [x] NPCs chase players in sight instead of random walks (greedy steps, not A*: see `NPC.step`).
- [x] Town population: named NPCs that stay in town, give flavor text on `/town status`.
- [x] Town residents are words only (`Town.residents`). Put them on the map as NPCs that never leave town, drawn
  from Kenney's people tiles, if towns feel empty; they'd need to be skipped by `World.attack` and the NPC tick.
  Decided 2026-11-02: do it now.
- [x] Wilds respawn / cooldown so a single wilds tile is not farmable every step.

## Persistence

- [x] Save NPCs (position, hp, type) so a restart does not wipe the world's population.
- [x] Save store inventories and prices per town.
- [x] Save weapon state (ammo loaded, jam) for equipped projectile weapons, and how full each ammo box is
  (`Items.Ammo.quantity`): both come back full after a restart today.
- [x] A store's shelf is saved by class path alone, so a part-used ammo box sold to a store comes back full
  after a restart. Save `_item_state` per shelf item too if anyone farms it (ponytail note on `Items.Ammo`).
  Decided 2026-11-02: fix it now.
- [x] Schema migrations are a column-presence check in `Database._migrate`. Fine for one column; if a change ever needs to rewrite data, switch to `PRAGMA user_version` and numbered steps.
  Decided 2026-11-02: switch now.

## Discord UX

- [x] `/look` should list visible NPCs and players by direction, not only render the image. `Wilds.level` now exists, so it can also say how rough the place you are standing in is.
- [x] Combat and event results are long: batch `PlayerActionResponse` text into one embed per order. (stale: a
  move is already one message, and since fights summarise per enemy the longest of 300 level-8 fights is 961
  characters, under Discord's 2000. An embed would be cosmetic.)
- [x] Nothing ever shows a player their money: `/equipment` lists gear only, and the store prints prices without a balance. Add currency to `/equipment`.
- [x] `/help` command generated from the Cog's command descriptions.
- [x] Ephemeral errors everywhere (`_send(..., ephemeral=True)` is inconsistent).
- [x] Refusals from deferred commands (`/move`, `/attack`, `/choose`, `/look`) still show to the whole channel:
  Discord gives the first followup after a public defer the defer's visibility, whatever `ephemeral` says.
  Try `interaction.delete_original_response()` then an ephemeral followup in `cog_app_command_error`, checked
  against real Discord (the simulator's fake honours `ephemeral` on that followup, so it can't tell).
  Decided 2026-11-02: build it; the user checks it on the deploy server (a dev server, `deploy/deploy.sh`).
  Note in the Done line that it is unchecked against real Discord until they do.
- [x] Decided 2026-10-30, the part that needs no live test: refuse what can be known before the tick (moving into
  water or off the map, `/choose` with no stranger waiting, `/trade` with no trader) privately, before deferring.
  Only refusals that depend on the tick itself stay public.
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
  (blocked: waits on players finding the map laggy)
- [x] Display scrolling for worlds larger than the window (TODO in `ConfigParser.py`).

- [ ] Chunks are never unloaded (~0.4 MB each, ponytail note in `World.__init__`). Evict chunks with nobody in
  them once a long-running server's memory says so; store sales in them would need saving first.
  (blocked: waits on the live server's memory; see the Linode box, ~1 GB RAM, so past ~1,500 chunks. The owner
  dashboard, `/admin`, charts both. Checked 2026-11-03: runs peak at 47-72 MB RSS with ~640 MB free, and every
  deploy restarts the process, which drops its chunks, so nothing is near the limit.)
- [x] The owner dashboard (`/admin`) can't tell when chunk eviction is due: add loaded chunks and the process's
  memory (`/proc/self/status` VmRSS, stdlib; blank off Linux) as `record_tick` metrics with `CHARTS` entries.
- [ ] Terrain repeats every ~2560 squares (`pnoise3` period, ponytail note in `World._terrain_at`).
  (blocked: waits on someone noticing; it's ~3.5 hours of /move from the spawn to see one repeat)

## Cleanup

- [x] Armor rolls its coverage randomly and `base_value` is `10 * armor_count`, so a piece worth 0 is
  free from any store. Give every item a floor price.
- [x] An equipped item stays in the backpack too (`/inventory equip` doesn't move it), so `Database.save` writes
  it twice, as a slot row and a backpack row, and a restart hands back two.
- [x] `GameSpace.Base`/`BaseLevel` are never placed or used: the hideout is `PlayerCharacter.hideout_level`. Delete them.
- [x] A wilds trader only sells. `Store.buy_item` already exists, so `/trade sell` is a few lines if
  players want to offload loot without walking to a town.
  Decided 2026-11-02: do it now.

- [x] `Space.closest` returns `sorted(...)[0 : size - 1]`, so the default `size=1` hands back an empty
  list. Nothing calls it; either fix the slice or delete it.

- [x] `Space.__eq__` ignores terrain but `Space.__hash__` includes it, so equal spaces can hash differently. Set
  operations on spaces (`World.get_players_in_region`) are quietly relying on identity today.

- [x] Delete `Items.FullyImplemented` marker (FIXME): `Store.generate_store` should pick from JSON data instead of subclass scanning.
- [x] `GameSpace.generate_map` region around the `FIXME Ugly function` note at ~L685.
- [x] The 6B45 chest armor (`Armor.Chest6B45`) has never been sold: it lacked the old marker since 2019 with no
  reason given, so it's `"store": false` in `armor.json` to keep shops as they were. Decided 2026-10-30: make it
  cache-only loot, so deep raids are where chest armor comes from. Caches pick from store stock today
  (`Cache.run_event`), so give them a small extra pool of `"store": false` gear, salvage aside.
- [x] `NPC.generate` passes `None` as `parent_world`; `World.add_actor` should own that assignment consistently.
- [x] README: store buy/sell are no longer placeholders; document `-W` web map and `/attack` DMs.
- [x] Unequipping your weapon (and now selling it) leaves `PlayerCharacter.weapon` None, so `/attack` and fights
  refuse with "no weapon equipped" until you equip something, while an empty gun falls back to fists
  (`ready_weapon`). Tests pin the None (`test_unequipping_a_weapon_leaves_the_character_bare_handed`). Decide
  whether an empty hand should be fists, as at birth and after a death.
  Decided 2026-11-03: fists. `PlayerCharacter.unequip` puts a fist back; the two tests change to expect it.
- [ ] `test_webapp.py::test_server_admins_pick_the_channels_on_the_settings_page` failed once in a full run on
  2026-11-03 and passed in the next five (alone and full). A flaky test: find what it races on if it recurs.
- [ ] `test_webclient.py::test_polls_revalidate_instead_of_redownloading[actors-pollActors]` failed once in a full
  run on 2026-11-03 and passed in the next four. Another flaky one: find what it races on if it recurs.

## Libraries

Hand-rolled parts an existing library already does. Researched 2026-11-03; in this order.

- [ ] Web server on `aiohttp.web` (installed already, discord.py depends on it) instead of `http.server` threads.
  Requests then run on the bot loop: `place_order`/`order_threadsafe`'s `run_coroutine_threadsafe` and the
  torn-read ponytail in `WebApp.py` go away, and `_Handler`'s `do_GET`/`do_POST` dispatch becomes a route table.
  Same URLs and responses, so `test_webapp.py` and `test_webclient.py` only change how they start the server.
  Split per commit if it won't fit one: static pages and JSON first, then `/act` and logins.
- [ ] Then the SSE item under Rendering is a `web.StreamResponse` on the same loop, not a thread per client.
- [ ] Replace `noise` (`pnoise3`): unmaintained, no wheels for recent Pythons, so a new server or Python upgrade
  can't install it. `tcod.noise` (python-tcod, also brings pathfinding) or `vnoise` (pure numpy, same Perlin).
  A world is regenerated from its seed, so a new noise re-rolls every saved map: keep `pnoise3` output for old
  saves (a `WorldGenerationParameters` field picking the generator, default old) or ask the user before a wipe.
  Fixes the ~2560-square repeat under Rendering too if the new one doesn't wrap at 256.
- [ ] Web map on Leaflet (`L.CRS.Simple`, a `GridLayer` whose `createTile` loads the chunk PNGs, actors as
  markers) instead of `client.js`'s own pan/zoom/tiles. One script tag, no build step. Its tile unloading
  (`keepBuffer`) clears the ~4000-chunk `<img>` ceiling in `DesktopApp.py`. `test_webclient.py`'s `page.js`
  checks need rewriting against Leaflet's DOM.
- [ ] NPC chase via `tcod.path` (Dijkstra map toward the player) instead of greedy steps (ponytail in
  `NPC.step`), so a coastline doesn't stop them cold; `astar` can go too if `AStarPathfinder` moves over. Only
  after the noise item brings tcod in, and only if stuck NPCs show up in play or the simulator.

## Done

- 2026-10-31 Bots wear found armor: out of a fight, a simulator bot spends its order putting on backpack armor worth
  more than what's in that slot (`Bot._better_armor`, by `base_value`: `armor_count` is a roll), and a new
  `mean armor worn (pieces)` metric shows it. It reads 0.02 at the end of 10 x 2000-tick runs: a cache's kit is
  its dearest pick (mostly guns), deep caches are rarely reached, and a death strips what's worn. Armor is scarce,
  not broken; worth a look if chest armor should matter more.

- 2026-10-31 Cache-only chest armor: caches roll for a piece of `GameSpace.CACHE_ONLY` (the 6B45, still
  `"store": false`) at a chance of their level / `WILDS_MAX_LEVEL`, on top of the usual kit: 1 in 8 at danger 1,
  certain at the deepest. Its own roll, since mixed into the kit pick a $100 vest loses to the store's best gun.

- 2026-10-31 Private refusals before the tick: `/move` into water or off the map and `/choose` with nobody waiting
  are refused before the defer, so the reply is ephemeral (a public defer makes the first followup public).
  `/trade` already never deferred. A step off the north or west edge used to be a "successful" move in place
  (`Space.__add__` clamps at 0); `attempt_move` now adds raw coordinates and refuses it.

- 2026-10-31 Enlisting simulator bots: a third of bots (`Bot.enlists`) skip trade towns and recruit at the first
  military base they rest in; a new `soldiers (share of bots)` metric shows them (0.15 over 10 seeds, the rest
  turn Raider or never reach a base), so soldier prices and sides move `sim_history` now.

- 2026-10-31 Soldier prices: a military base's store takes its side from the town (`Store.side`, set in
  `Town.__init__`, so a load gets it back with no new column), and `Store.get_price(item, buyer)` takes 20% off
  for a soldier of that side and adds 20% for the other (`SIDE_DISCOUNT`). Listings, autocomplete and the sale
  all use the buyer's price; the listing says which. Selling to a store is unchanged. Closes faction consequences.

- 2026-10-31 Unarmed simulator bots: a bot whose main hand is a `Fist` heads home from anywhere above danger 1,
  so it raids only the shallow end until it can afford a gun. Seed 1 at 5000 ticks: 61 -> 29 deaths, the spiralling
  bot 34 -> 12.

- 2026-10-31 Deaths after d15fd3f: one seed-1 bot's broke, bare-fisted death spiral, not a balance change (the
  other nine seeds and five bots match b559d70). Logged the missing floor for broke players and the bots' habit
  of raiding deep unarmed as follow-ups.

- 2026-10-31 Raider deaths after fc3f783: a 10-seed x 5000-tick run shows Raider-class bots die in wilds fights
  no more often than anyone else per tick out (0.92 vs 1.01 per 1000), so wilds fights keep fighting Raiders.

- 2026-10-31 Achievements (d15fd3f): twelve in `Actors.ACHIEVEMENTS`, checked each `World.tick`, DM'd and
  announced, listed by `/achievements` and on `/me`; lifetime kills and hauls saved. Stores now stock armor on
  every map (`GameSpace` imports `Armor`), so a seed rolls the same chunks whatever was imported first.

- 2026-10-30 Ruins and plazas: a fourth noise layer turns about a fifth of paving into ruins (`RuinsTerrain`,
  the sheet's grey concrete block: raiders can't spot you in them) or plazas (`PlazaTerrain`, the tan-bordered
  block: spotted from twice `NPC_SIGHT`), both in `World.prey_in_sight`. They're paving subclasses, buildable and
  walkable, and the layer has its own seed, so every saved map keeps its towns, wilds, caches and exits square for
  square (tested by switching the layer off). `ART_VERSION` 7.

- 2026-10-30 More classes: mining towns train Scavengers (60 HP, a cache gives one more salvage), farming towns
  Medics (55, camping heals twice as fast), woodworking towns Scouts (55, `fov` + 1 for `/look` and the map view),
  smithing towns Fixers (60, stores pay 25% more when you sell). All tier 1 beside Soldier, so you can switch
  between them; only a town with no trade still trains Wanderers. Each perk lives where it applies, worded once in
  `PlayerClass.perk` for `/town recruit`, `/town status` ("It trains Scavengers: ...") and the home page's class
  cards. Sprites cut from the Kenney sheet's people. Saved by class path, so nothing new in `Database`.

- 2026-10-30 README: documents `-W PORT` and `--database` (and how to run the tests), `/settings`, the DMs a
  player gets (spotted, a fight's first hit and its end, auto-raid results), the inn and store sell as they are,
  and piles in `/look`. Python 3.12 and the GitHub Actions badge replace "3.7+" and Travis. Store buy/sell were
  already described as real. The 6B45 question is marked blocked on a design call.

- 2026-10-30 The `FIXME Ugly function` was `World.is_space_buildable`, used only to plant a town when a map
  rolls none. It's now one line, `type(space) is Space and space.terrain.buildable`: no more list scans of every
  town and wilds per square, and it no longer lets that fallback town pave over a cache or extraction point.

- 2026-10-30 `FullyImplemented` is gone: stores stock `Data.stocked()`, every gear class with a stat block in
  `data/`, minus blocks saying `"store": false` (fists, salvage, and the 6B45 that was never stocked). Same
  classes in the same order as before, so every seeded store comes out as it did.

- 2026-10-30 Deleted `GameSpace.Base` and `BaseLevel`: never placed, never referenced; the hideout is
  `PlayerCharacter.hideout_level`. CLAUDE.md's layout line now lists Cache/Extract instead.

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
- 2026-10-31 Prestige: `/hideout prestige` (town, hideout 15+, `confirm` to go through) wipes the hideout and
  stash for +10% hideout income per prestige, kept in a migrated `character.prestige`; income now goes through
  `PlayerCharacter.hideout_income`.
- 2026-10-31 XP on extract: extracting with items or money pays `EXTRACT_XP_PER_DANGER` (10) XP per danger level
  of the deepest square stood on that raid (`PlayerCharacter.raid_deepest`, via the new `World.danger_at`).
- 2026-10-31 Simulator bots read cover: a step swings 45 degrees onto ruins or off a plaza (`Bot._careful`, only
  loaded squares). It changes ~8% of steps but not the outcome: over 10 seeds x 2000 ticks, 142 deaths with it
  and 133 without, worth 747 vs 708, inside seed noise. Sight isn't what kills bots (wilds fights are), so
  plazas stay at 2x.
- 2026-10-31 Extract XP deadlier? No: over 10 seeds x 2000 ticks, `EXTRACT_XP_PER_DANGER` 0 vs 10 gives deaths
  158 vs 142, mean level 1.32 vs 2.03, worth 738 vs 747, furthest 33.4 vs 32.7, and the same deaths-by-danger
  split (most at danger 3 either way). Levelled bots live longer; seed 1's 25 -> 29 was noise. No code change.
- 2026-10-31 Simulator `--seeds N`: plays N seeds from `--seed` and records each metric's mean (`seeds` joins
  the settings only when N > 1, so single-seed history still lines up). `/dev-loop` now runs `--seeds 10`
  (~20 s) instead of seeds 0 and 1.
- 2026-10-31 Simulator bots recruit: a Wanderer bot takes the class of the first trade town it stands in (not a
  military base), rows carry the class, and a new "trade classes (share of bots)" metric shows how many did.
- 2026-10-31 Faction joining: a won `/choose rob` or a player kill calls `PlayerCharacter.turn_raider()` (Raider,
  side dropped, hit points kept rather than healed); a military base's recruit sets `character.side` from
  `IndustryType.side` ("East"/"West"), saved in a migrated column.
- 2026-10-31 Simulator bot stance: odd-numbered bots rob strangers, even ones only talk or walk on (by id, so no
  extra random draws), so trade classes and Raiders both show in `sim_history`.
- 2026-10-31 Raiders spare Raiders: `World.spares(npc, player)` keeps raider NPCs from hitting (the tick's targets)
  or hunting (`prey_in_sight(space, hunter)`) Raider-class players. Animals still go for anyone; wilds fights
  (`CombatEvent`) are unchanged.
- 2026-10-31 Friendly fire: a no-direction `/attack` picked a random target among everyone on the square, so bots
  ganging up on a raider killed each other (seed 7's lone sim error: bot1 killed bot4, whose own attack then ran
  in town). An NPC on the square is now hit before any player. And an attack on a raider another order killed
  this tick says "X is already down." instead of refusing (`NPC.fell_at`). Sim deaths 12 -> 10.5 a seed, errors 0.
- 2026-11-02 A rendered hideout: `/hideout view` (anywhere) and the `/me` hideout card (`/hideout.png`) show
  a walled room from the Kenney sheet, a square wider per level up to 16, the stash money as a bag and its
  items as crates, the player standing in front. Drawn by `WindowRenderer.hideout_png`; reads only the character.
- 2026-11-02 Trophies on the hideout wall: a frame per achievement earned and a wider one for the best haul,
  which is the most one extraction brought home (money plus the new items' value). Saved as a migrated
  `character.best_haul` column, and the hideout text names it. Plain frames, not emoji (ponytail note).
- 2026-11-02 Odd jobs: `/town work` (in town) starts an hour-long shift, `PlayerCharacter.work_until`, that
  `World.advance` pays $4 carried every 60 ticks ($48 a shift at a 5-second tick, two buy a $75 Stechkin). Moving
  or dying ends it; saved as a migrated column, so a restart's catch-up pays the rest of the shift, not the downtime.
- 2026-11-02 Gathering: `/gather` on danger-1 ground out of town starts the same hour-long shift as `/town work`
  (`work_until`, no new column), but `World.advance` pays it in `Items.Firewood` ($10, `"store": false` in
  barter.json) every 120 ticks: six bundles, $60 once carried home and sold, against work's $48 in hand.
- 2026-11-02 Simulator bots work: broke and bare-fisted in a town whose store still has a gun, a bot takes
  `/town work` shifts until it can buy one. Seed 1 over 5000 ticks: no bot past 10 deaths (one had 34) and five
  of six end armed. Found stores never restock (new item): the last bare-fisted bot was in a sold-out town.
- 2026-11-02 Stores restock: every `STORE_RESTOCK_TICKS` (720, an hour at a 5-second tick) of the world clock,
  `World.advance` gives each traded store in a loaded town one of every stocked kind it lacks (`Store.restock`).
  On the global clock, so nothing new is saved and a restart's catch-up restocks too. Seed 1 x 5000 ticks: 30 -> 25
  deaths, and the bots left bare-fisted at the end are mid-shift, not stuck.
- 2026-11-02 Checked the work wage: bare-fisted, a bot earned $0 an hour fist-raiding (1.7 deaths an hour) and
  earns $47 working (none). The floor beats the old way out; the worth drop was cash turned into guns. No change.
- 2026-11-02 Checked the restock death rise on 10 seeds x 5000 ticks: deaths unchanged (16.3 vs 16.5 a seed), none
  bare-fisted any more; the level drop is bots buying the always-restocked cheapest gun (new item).
- 2026-11-03 Bots shop like players: a bare-fisted simulator bot buys the most damaging gun it can pay for with a
  box of its ammo, cash and stash together (`Bot._best_gun`, taking the shortfall from the stash first), instead
  of the cheapest, which since restocking was always the 4-damage Stechkin.
- 2026-11-03 Town residents on the map: a townsperson from the Kenney sheet (`resident.png`) stands in every town's
  doorway, baked into the map art (`WindowRenderer._draw`, so `/look` and the web map both show it; `ART_VERSION`
  8), and clicking a town on the web map lists its three residents and what they say (from the chunk's JSON,
  fetched on demand). Not NPCs, so attack, the NPC tick and saves need no skipping. `Town.residents` is now rolled
  once at construction, since the web side reads it from an HTTP thread and `_seeded` swaps the global RNG.
- 2026-11-03 Store shelves keep item state through a restart: a store row lists `[class path, _item_state]` per
  item, so a part-used ammo box sold to a store comes back part-used (and a gun keeps its loaded rounds). Bare
  class paths from older saves still load, so no migration.
- 2026-11-03 Numbered schema migrations: `Database.MIGRATIONS[n]` takes a file at `PRAGMA user_version` n to n + 1,
  each step in one transaction with its version bump; step 1 is the old column-presence check, for files from
  before. A new file starts at the last version. CLAUDE.md says where a schema change goes.
- 2026-11-03 Refusals after a public defer: `cog_app_command_error` deletes the deferred "thinking..." reply
  (`delete_original_response`) before sending the refusal as an ephemeral followup, so a tick-time refusal on
  `/move`, `/attack`, `/choose` or `/look` should stop showing to the whole channel. Unchecked against real
  Discord until the user tries it on the deploy server (the fakes honour `ephemeral` either way).
- 2026-11-03 Dashboard memory: each tick's row carries the process's resident memory (`memory_mb`, VmRSS from
  `/proc/self/status`; blank off Linux), and `/admin` charts it and shows it as a tile next to chunks explored
  (already charted), so it says when chunk eviction is due. A chart with no data (memory on Windows) is left out.
- 2026-11-03 `/trade sell`: a wilds trader buys backpack items at two thirds of a town's price (its markup is its
  discount, through `Store.buy_item`), sharing `_sell` with `/town store sell`. Selling something you hold or
  wear now takes it out of your hands: it used to stay equipped, so you kept firing a gun the store could
  sell back to you. The server simulator's members try `/trade sell` too.
- 2026-11-03 Empty hands are fists (decided 2026-11-03): `PlayerCharacter.unequip` puts a fist back when the main
  hand is left without a weapon, so unequipping or selling your gun leaves you punching, as at birth and after a
  death, instead of "You have no weapon equipped!". The no-weapon guards stay for a non-weapon in hand; their
  tests now empty the hand through the raw equipment set.
- 2026-11-03 Pets, first slice: a goat. `/pet adopt [name]` in town ($300, arrives fed), `/pet feed` in town ($20,
  fed for `PET_FEED_TICKS`, half a day; a meal doesn't keep), `/pet status` anywhere. Fed, it puts an
  `Items.GoatMilk` ($15, barter, sold in town) into the stash every `PET_MILK_TICKS` (an hour) through
  `World.advance`, downtime included. Saved as `character.pet_name`/`pet_fed_until`, migration step 2. The server
  simulator's members adopt and feed too.
- 2026-11-03 Pets, neglect and care: fed again before it goes hungry `PET_CARE_MAX` (3) times running, a goat gives
  two jugs an hour; going hungry starts that over (`pet_care`, saved, migration step 3). Hungry for
  `PET_RUNAWAY_TICKS` (three days) it wanders off for good (`pet_gone`, worked out from `pet_fed_until`, not
  stored), and you can adopt another. `/pet status` counts down either way.
- 2026-11-03 Hungry goat DM: `World.tick` returns an event on the tick a goat's last meal runs out
  (`pet_fed_until == ticks`), so the cog DMs "Bibi is hungry..." once per hunger. One that goes hungry during
  downtime stays quiet (ponytail note).
- 2026-11-03 Dog fetches: `/pet adopt kind:dog` buys a dog instead of a goat (`pet_kind`, saved, migration step 4;
  one pet each). It gives no milk; fed, a quiet step in the wilds has `PET_FETCH_CHANCE` (2%, doubled when cared
  for) of salvage into the backpack, on auto-raids too. Hungry beep and `/pet status` say which. `pet_jugs` is
  `pet_yield` now. Biting split off as its own item.
