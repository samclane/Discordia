# Discordia

Discord extraction idle game: a persistent 2D tile world (perlin-noise terrain, towns, wilds) where players raid the wilds via slash commands, extract back to towns with loot, and build a hideout that earns while they're away (see ROADMAP.md "Vibe"). Python 3.12, discord.py 2.x, Pillow, numpy, `astar`, SQLite.

## Run / test

```
python main.py [-W 8080] [--database discordia.db]   # needs DISCORD_TOKEN or config.ini [Discord] Token
python -m pytest Discordia/test -q                     # 266 tests, ~30s, no token needed
```

CI runs `pytest -q` on push (`.github/workflows`). Keep it green.

## Layout

- `Discordia/GameLogic/` pure game rules, no Discord imports.
  - `GameSpace.py` Terrain, Space/Town/Wilds/Base, `World` (map gen, `tick()`, `attack`, death), `Store`, A* pathfinder.
    The map is generated lazily in `CHUNK_SIZE` chunks, deterministic per (seed, chunk): reach squares through
    `world.space_at(x, y)`, never a grid. `world.towns`/`wilds` hold loaded chunks only. Wilds roll their events on
    first visit. NPCs only act within `NPC_AWAKE_RADIUS` (a chunk) of a player and never step into
    an unloaded chunk: only players explore.
  - `Actors.py` Actor -> NPC/Raider and PlayerCharacter; PlayerClass (Wanderer/Soldier/Raider).
  - `Events.py` Wilds events: CombatEvent (real), EncounterEvent/MerchantEvent (stubs).
  - `Behavior.py` NPC finite state machine (Aggressive -> Fleeing).
  - `Items.py` Equipment/EquipmentSet, `Weapons.py`, `Armor.py`: stat blocks load from `data/*.json` via `Data.py` (`FromData`).
  - `StringGenerator.py` names from `data/names.json`. `Procedural.py` normal() helper.
- `Discordia/Interface/`
  - `WorldAdapter.py` the only thing Discord and renderers touch: discord member id <-> PlayerCharacter, move/attack/look.
  - `DiscordInterface.py` slash commands as a Cog. Commands queue an *order*; `tick()` runs them and `World.tick()` in lockstep on the bot loop (no locks). NPC hits are DM'd.
  - `Database.py` SQLite save: world = seed + gen params (map is regenerated) + clock (`World.ticks`, run on by the downtime at load), characters + items by class path, `GuildSettings` per Discord server as JSON. NPCs and store stock are NOT saved.
  - `Rendering/DesktopApp.py` Pillow renderer (cached chunk PNGs, player views). Terrain is autotiled from quarters of
    Kenney's RPG Urban sheet (`Sprites/Terrain/`, CC0) using `Terrain.neighbours`; `BLOCKS` maps terrain to sheet blocks.
    `WebApp.py` + `index.html`/`client.js` live map at `/map`; `site.html` (header/footer) + `home.html` are the public site at `/`, `me.html` the logged-in character sheet at `/me`, all filled in by `_Handler._page` at `-W PORT` (no build step: plain JS, edit and reload). The web side only reads loaded chunks and never generates: generation stays on the bot loop.
  - Playing from the map: `POST /act` (JSON) builds the same action a slash command would and hands it to
    `adapter.place_order`, which the running cog sets to `order_threadsafe`: queued on the bot loop, answered after the
    tick. Result/error wording (`move_text`, `error_text`, ...) lives in `WorldAdapter` so both sides say the same thing.
    What the tick DMs is also kept per player (`adapter.add_news`/`news`, in memory) for `/me` and the map.
  - Adding the bot: the public `/invite` redirects to Discord's add-to-server page (`adapter.invite_url`, built by
    the cog at startup from the application id); `on_guild_join` posts a welcome in the server's system channel.
  - Server settings: `/settings` (Manage Server) hands out a login link to `/admin/<guild id>`, which asks Discord
    live (`adapter.guild_for_admin`, set by the cog) whether the member may manage that server. Settings live in
    `adapter.guild_settings` (`GuildSettings`, a new setting is a new field with a default); the cog's
    `interaction_check` enforces the channel list, `post_digest` posts the daily digest (midnight UTC) to each
    server's `digest_channel`. Checks must raise an `AppCommandError` (`_game_check` wraps game
    exceptions): the command tree lets anything else escape unanswered.
  - `WebLogins.py` web map login: `/weblogin` replies (ephemeral) with a one-time link, the link trades for a session cookie, the map and its data need it (`/`, `/login`, `/sprites/` are public), and `/me.json` serves that player's sheet. No passwords; only SHA-256 digests kept, in memory (a restart logs people out). Prod: nginx + certbot in front, `[Web] PublicUrl` in config.ini.
- `main.py` wiring, `ConfigParser.py` config.ini/default.ini, `ROADMAP.md` backlog.

## Conventions

- Game rules go in GameLogic; the Cog only parses input and formats `PlayerActionResponse.text`.
- New items/weapons/armor: add a JSON stat block in `data/`, subclass the matching `FromData` class. Restorable classes must live in a module listed in `Database._ALLOWED_MODULES`.
- Anything on a saved character (new field, new equipment slot) needs a `Database` save/load change and a round-trip test in `test_game_logic.py`.
- Tests: pytest, plain functions, no Discord token. Discord commands are tested with fake interactions in `test_discord_interface.py`; copy an existing one. The web map page is tested in headless Chrome/Edge over DevTools in `test_webclient.py` (skipped without a browser): `page.js(...)` runs script in it.
- `test_simulation.py` is a player simulator: bots play through `WorldAdapter` in lockstep with `World.tick()` and
  flag anomalies. `python -m Discordia.test.test_simulation --ticks 5000 --out sim.jsonl --html sim.html` for a long run to analyse;
  `--html` draws it (trails and deaths on the map, charts over time) from the `sim_template.html` template.
- `test_server_simulation.py` is a Discord server simulator: members on two fake servers use the real slash commands
  (discord.py's checks and error handlers, a fake Discord behind them) and every message the bot sends is checked
  for spam, posts outside allowed channels, leaked links, mass pings and unanswered interactions. New rule: add it
  in `Discord.post` or `_check_rates`. `python -m Discordia.test.test_server_simulation --ticks 500 --out s.jsonl --html s.html`
  (`--from s.jsonl --html s.html` redraws an old run; `server_template.html` is the dashboard template).
- `# ponytail:` comments mark deliberate shortcuts and their upgrade path. Read them before "fixing" one.
- Black formatting. Small diffs, no speculative abstractions.

## Development loop

`/dev-loop` (in `.claude/commands/`) does one roadmap item per run on Opus. Start a session with `claude --model opus`, then `/loop 30m /dev-loop` (or `/loop /dev-loop` to self-pace, or `/dev-loop <item>` for one specific item).
