# Discordia

Discord MUD: a persistent 2D tile world (perlin-noise terrain, towns, wilds) that players explore and fight in via slash commands. Python 3.12, discord.py 2.x, Pillow, numpy, `astar`, SQLite.

## Run / test

```
python main.py [-W 8080] [--database discordia.db]   # needs DISCORD_TOKEN or config.ini [Discord] Token
python -m pytest Discordia/test -q                     # 128 tests, ~10s, no token needed
```

CI runs `pytest -q` on push (`.github/workflows`). Keep it green.

## Layout

- `Discordia/GameLogic/` pure game rules, no Discord imports.
  - `GameSpace.py` Terrain, Space/Town/Wilds/Base, `World` (map gen, `tick()`, `pvp_attack`, death), `Store`, A* pathfinder.
  - `Actors.py` Actor -> NPC/Raider and PlayerCharacter; PlayerClass (Wanderer/Soldier/Raider).
  - `Events.py` Wilds events: CombatEvent (real), EncounterEvent/MerchantEvent (stubs).
  - `Behavior.py` NPC finite state machine (Aggressive -> Fleeing).
  - `Items.py` Equipment/EquipmentSet, `Weapons.py`, `Armor.py`: stat blocks load from `data/*.json` via `Data.py` (`FromData`).
  - `StringGenerator.py` names from `data/names.json`. `Procedural.py` normal() helper.
- `Discordia/Interface/`
  - `WorldAdapter.py` the only thing Discord and renderers touch: discord member id <-> PlayerCharacter, move/attack/look.
  - `DiscordInterface.py` slash commands as a Cog. Commands queue an *order*; `tick()` runs them and `World.tick()` in lockstep on the bot loop (no locks). NPC hits are DM'd.
  - `Database.py` SQLite save: world = seed + gen params (map is regenerated), characters + items by class path. NPCs and store stock are NOT saved.
  - `Rendering/DesktopApp.py` Pillow renderer (baked background + actor layer); `WebApp.py` + `client.js` live map at `-W PORT`.
- `main.py` wiring, `ConfigParser.py` config.ini/default.ini, `ROADMAP.md` backlog.

## Conventions

- Game rules go in GameLogic; the Cog only parses input and formats `PlayerActionResponse.text`.
- New items/weapons/armor: add a JSON stat block in `data/`, subclass the matching `FromData` class. Restorable classes must live in a module listed in `Database._ALLOWED_MODULES`.
- Anything on a saved character (new field, new equipment slot) needs a `Database` save/load change and a round-trip test in `test_game_logic.py`.
- Tests: pytest, plain functions, no Discord token. Discord commands are tested with fake interactions in `test_discord_interface.py`; copy an existing one.
- `# ponytail:` comments mark deliberate shortcuts and their upgrade path. Read them before "fixing" one.
- Black formatting. Small diffs, no speculative abstractions.

## Development loop

`/dev-loop` (in `.claude/commands/`) does one roadmap item per run on Opus. Start a session with `claude --model opus`, then `/loop 30m /dev-loop` (or `/loop /dev-loop` to self-pace, or `/dev-loop <item>` for one specific item).
