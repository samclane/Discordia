# Roadmap

Backlog for `/dev-loop`. One line per item, roughly in priority order within a section. The loop picks the first
unchecked item it can finish in one sitting, checks it off, and appends a line under **Done**. Add new items at the
bottom of the right section, add sections when a theme emerges. Keep items small enough for one commit.

## Gameplay loop (make it a game)

- [x] Earn money: NPC kills drop currency (`NPC.on_death` -> `PlayerActionResponse`); stores are the only sink today and players start with 1000.
- [x] `/attack` only ever hits players (`World.pvp_attack`): NPCs standing on the map are unkillable, so their money is unreachable outside wilds events.
- [ ] `NPC.generate(1)` rolls ~0 hit points: `(50 // 2) * (level // 2)` is 0 for level 1, so tick-spawned raiders die to a breeze.
- [ ] Death has a cost: `World.handle_player_death` drops or taxes inventory/currency instead of a free respawn.
- [ ] XP and levels on `PlayerCharacter`; wilds `level` and `NPC.generate(level)` already exist, hook them to player level.
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
- [ ] Schema versioning: a `PRAGMA user_version` bump plus a one-off migration helper for the next column added.

## Discord UX

- [ ] `/look` should list visible NPCs and players by direction, not only render the image.
- [ ] Combat and event results are long: batch `PlayerActionResponse` text into one embed per order.
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

- 2026-09-14 `/attack` hits NPCs: `World.pvp_attack` became `World.attack` and targets players and NPCs alike,
  paying out the corpse through a shared `PlayerCharacter.loot`. Fixed `Space.__eq__` raising on a despawned
  actor's `None` location, which the new targeting walked straight into.

- 2026-09-13 Earn money: generated NPCs carry `CURRENCY_PER_LEVEL * level` on average, and `CombatEvent` pays it out
  once per kill alongside the loot. Also guarded `World.generate_map` against rolling zero towns, which an extra
  random draw exposed on small maps.
