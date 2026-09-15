# Roadmap

Backlog for `/dev-loop`. One line per item, roughly in priority order within a section. The loop picks the first
unchecked item it can finish in one sitting, checks it off, and appends a line under **Done**. Add new items at the
bottom of the right section, add sections when a theme emerges. Keep items small enough for one commit.

## Gameplay loop (make it a game)

- [x] Earn money: NPC kills drop currency (`NPC.on_death` -> `PlayerActionResponse`); stores are the only sink today and players start with 1000.
- [x] `/attack` only ever hits players (`World.pvp_attack`): NPCs standing on the map are unkillable, so their money is unreachable outside wilds events.
- [x] `NPC.generate(1)` rolls ~0 hit points: `(50 // 2) * (level // 2)` is 0 for level 1, so tick-spawned raiders die to a breeze.
- [ ] Wilds difficulty outruns the player: a far wilds rolls `normal(level)` enemies of `25 * level` hit points, while a player gains only `HIT_POINTS_PER_PLAYER_LEVEL` (10) per level and no extra damage at all. Scale something the player earns, or cap wilds level by distance.
- [x] Death has a cost: `World.handle_player_death` drops or taxes inventory/currency instead of a free respawn.
- [x] XP and levels on `PlayerCharacter`; wilds `level` and `NPC.generate(level)` already exist, hook them to player level.
- [ ] `EncounterEvent` is a stub (`{"<test>": "<test>"}`): make it a real choice (talk / rob / ignore) with outcomes.
- [ ] `MerchantEvent` is a stub with no items: sell a random `Store.generate_store()` slice at a markup.
- [ ] `CombatEvent.run` can loop forever when player damage is 0 (see WARN comment): cap rounds or make a 0-damage weapon end the fight.
- [ ] Rest / heal outside towns (camp command, slow regen per tick) so a hurt player is not forced to walk home.
- [ ] Player bases: `Base`/`BaseLevel` exist in GameSpace with no command. Add `/base build|upgrade|status` gated on `is_space_buildable`.
- [ ] Faction consequences: Soldier (East/West) vs Raider should change NPC hostility and store prices somewhere.

## NPCs and world

- [ ] NPCs fleeing should step away on the grid (`Behavior.Fleeing`, ponytail note) now that NPCs move in `World.tick`.
- [ ] Non-Raider NPC types (animals from `BodyType`, merchants, guards in towns) with their own sprites.
- [ ] NPCs use A* (`AStarPathfinder`) to chase players in FOV instead of random walks.
- [ ] Town population: named NPCs that stay in town, give flavor text on `/town status`.
- [ ] Wilds respawn / cooldown so a single wilds tile is not farmable every step.

## Persistence

- [ ] Save NPCs (position, hp, type) so a restart does not wipe the world's population.
- [ ] Save store inventories and prices per town.
- [ ] Save weapon state (ammo loaded, jam) for equipped projectile weapons.
- [ ] Schema migrations are a column-presence check in `Database._migrate`. Fine for one column; if a change ever needs to rewrite data, switch to `PRAGMA user_version` and numbered steps.

## Discord UX

- [ ] `/look` should list visible NPCs and players by direction, not only render the image.
- [ ] Combat and event results are long: batch `PlayerActionResponse` text into one embed per order.
- [x] Nothing ever shows a player their money: `/equipment` lists gear only, and the store prints prices without a balance. Add currency to `/equipment`.
- [ ] `/help` command generated from the Cog's command descriptions.
- [ ] Ephemeral errors everywhere (`_send(..., ephemeral=True)` is inconsistent).
- [ ] Channel announcements for deaths and town arrivals instead of only DMs.

## Rendering

- [ ] Random sprite generation per `BodySize` (TODO in `Actors.py`); NPCs all share `null_npc.png`.
- [ ] Web map: SSE push instead of 2s polling (ponytail note in `WebApp.py`) if it feels laggy.
- [ ] Display scrolling for worlds larger than the window (TODO in `ConfigParser.py`).

## Cleanup

- [ ] `Space.__eq__` ignores terrain but `Space.__hash__` includes it, so equal spaces can hash differently. Set
  operations on spaces (`World.get_players_in_region`) are quietly relying on identity today.

- [ ] Delete `Items.FullyImplemented` marker (FIXME): `Store.generate_store` should pick from JSON data instead of subclass scanning.
- [ ] `GameSpace.generate_map` region around the `FIXME Ugly function` note at ~L685.
- [ ] `NPC.generate` passes `None` as `parent_world`; `World.add_actor` should own that assignment consistently.
- [ ] README: store buy/sell are no longer placeholders; document `-W` web map and `/attack` DMs.

## Done

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
