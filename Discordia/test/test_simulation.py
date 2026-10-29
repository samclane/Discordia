"""
Player simulator: a few bots play the game through WorldAdapter, one order per tick each, with World.tick() in
lockstep the way the cog runs it. Every tick of every bot is logged, and the run is checked for things that
should never happen (anomalies).

The test is a short smoke run. For a long one to dig through:

    python -m Discordia.test.test_simulation --ticks 5000 --bots 8 --out sim.jsonl --html sim.html

which prints a summary, writes one JSON line per bot per tick (load it with pandas.read_json(lines=True)), and
draws the run as a standalone page: trails and deaths on the explored map, and level, money, range and deaths
over time (sim_template.html is the template).
"""

import argparse
import base64
import faulthandler
import io
import json
import math
import random
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from PIL import Image

from Discordia.GameLogic import Actors, Events, GameSpace, Items, Weapons
from Discordia.GameLogic.GameSpace import DIRECTION_VECTORS, Town
from Discordia.Interface.Rendering.DesktopApp import WindowRenderer
from Discordia.Interface.WorldAdapter import WorldAdapter, error_text

DIRECTIONS = [d for k, d in DIRECTION_VECTORS.items() if k]
SLOW_ORDER = 1.0  # seconds; an order this slow is worth a look (CombatEvent can spin)
HANG = 300  # seconds for a whole run before faulthandler dumps every stack and exits
# Anomalies already on ROADMAP.md, so the test stays green until they're fixed. Delete one when its fix lands.
KNOWN: Tuple[str, ...] = ()
REPORT_TEMPLATE = Path(__file__).with_name("sim_template.html")
MAP_PX = 4  # pixels a square on the report's map: ~10 chunks across fit a laptop screen


def _toward(here, there) -> Tuple[int, int]:
    """A step from `here` toward `there` (anything with x and y) that keeps to the true bearing on average:
    always along the long axis, along the short one as often as the ratio says. Stepping by sign alone walks
    every route as a diagonal and then a straight, so all paths collapse onto eight compass lines."""
    dx, dy = there.x - here.x, there.y - here.y
    longest = max(abs(dx), abs(dy)) or 1
    return (
        int(math.copysign(1, dx)) if random.random() < abs(dx) / longest else 0,
        int(math.copysign(1, dy)) if random.random() < abs(dy) / longest else 0,
    )


class Bot:
    """One player's habits. `reach` is how many steps out it raids before heading home: its appetite for risk."""

    def __init__(self, adapter: WorldAdapter, member_id: int, reach: int):
        adapter.register_player(member_id, f"bot{member_id}")
        self.adapter = adapter
        self.character = adapter.get_player(member_id)
        self.reach = reach
        self.goal = self._pick_goal()
        self.steps_out = 0
        self.entered: Optional[GameSpace.Space] = None  # the square this tick's move stepped into, if any

    def order(self) -> Tuple[str, Callable[[], Any]]:
        """Pick this tick's order: (label, thunk), like a slash command handing the cog an action."""
        c, a = self.character, self.adapter
        if isinstance(c.pending_event, Events.EncounterEvent):
            choice = random.choice(Events.EncounterEvent.CHOICES)
            return f"choose {choice}", lambda: a.resolve_encounter(c, choice)
        if any(n.location == c.location for n in a.get_nearby_npcs(c)):
            return "attack", lambda: [a.attack(c, (0, 0))]
        if isinstance(town := c.location, Town):
            self.steps_out = 0
            self.goal = self._pick_goal()
            if c.hit_points < c.hit_points_max:
                return "inn", lambda: [town.inn_event(c)]
            if isinstance(c.weapon, Weapons.Fist):
                wanted = Weapons.Weapon
            elif isinstance(gun := c.weapon, Weapons.ProjectileWeapon) and not any(
                isinstance(i, Items.Ammo) and i.caliber == gun.caliber for i in c.inventory
            ):
                wanted = lambda item: isinstance(item, Items.Ammo) and item.caliber == gun.caliber
            else:
                wanted = None
            if wanted and (buy := self._cheapest(town, wanted)) is not None:
                return f"buy {buy.name}", lambda: self._buy(town, buy)
            if wanted is Weapons.Weapon and (short := self._short_for_a_weapon(town)):
                return f"take ${short}", lambda: c.stash_take(money=short)  # re-arm after a death
            if c.currency > 100:
                money = c.currency - 100  # bank all but walking-around money
                return f"stash ${money}", lambda: c.stash_put(money=money)
        hurt = c.hit_points < c.hit_points_max * 0.4
        if hurt or self.steps_out >= self.reach:
            return "go home", lambda: self._step(
                _toward(c.location, a.world.starting_town)
            )
        self.steps_out += 1
        step = _toward(c.location, self.goal) if random.random() < 0.7 else random.choice(DIRECTIONS)
        return "raid", lambda: self._step(step)

    def _pick_goal(self) -> GameSpace.Space:
        """Somewhere `reach` squares out from the starting town, at any bearing: where this raid heads."""
        world, angle = self.adapter.world, random.uniform(0, 2 * math.pi)
        town = world.starting_town
        x = round(town.x + self.reach * math.cos(angle))
        y = round(town.y + self.reach * math.sin(angle))
        return GameSpace.Space(min(max(x, 0), world.width - 1), min(max(y, 0), world.height - 1))

    def _cheapest(self, town: Town, wanted):
        """The cheapest affordable store item that is `wanted` (a class, or a predicate), or None."""
        store = town.store
        test = (lambda item: isinstance(item, wanted)) if isinstance(wanted, type) else wanted
        fits = [
            item
            for item in store.inventory
            if test(item) and store.get_price(item) <= self.character.currency
        ]
        return min(fits, key=store.get_price, default=None)

    def _short_for_a_weapon(self, town: Town) -> int:
        """What to take out of the stash to afford the cheapest weapon here, or 0 if it can't or needn't."""
        c = self.character
        prices = [town.store.get_price(i) for i in town.store.inventory if isinstance(i, Weapons.Weapon)]
        price = min(prices, default=0)
        return price - c.currency if c.currency < price <= c.currency + c.stash_currency else 0

    def _buy(self, town: Town, item):
        """Buy `item` if it's still there: another bot in the same town may have bought it first this tick."""
        c = self.character
        index = next((i for i, x in enumerate(town.store.inventory) if x is item), None)
        if index is not None and town.store.sell_item(index, c) and not isinstance(item, Items.Ammo):
            c.equip(item)
        return []

    def _step(self, direction):
        """A move, sidestepping water and map edges the way a player would retry another direction."""
        for d in [direction] + random.sample(DIRECTIONS, len(DIRECTIONS)):
            if d == (0, 0):
                continue
            here = self.character.location
            try:
                responses = self.adapter.move_player(self.character, d)
            except Exception as e:
                if error_text(e) is None:
                    raise
                continue
            self.entered = self.adapter.world.space_at(here.x + d[0], here.y + d[1])
            return responses
        return []


def _death(space: GameSpace.Space, cause: str) -> dict:
    """Where a bot fell and what it was doing: the row itself is taken after the respawn in town."""
    return {"x": space.x, "y": space.y, "space": type(space).__name__, "danger": getattr(space, "level", 0), "cause": cause}


def snapshot(world: GameSpace.World, c) -> dict:
    here = c.location
    weapon = c.weapon
    return {
        "name": c.name,
        "x": here.x if here else None,
        "y": here.y if here else None,
        "space": type(here).__name__,
        "danger": getattr(here, "level", 0),
        "town_distance": round(here.distance(world.starting_town), 1) if here else None,
        "hp": c.hit_points,
        "hp_max": c.hit_points_max,
        "dead": c.is_dead,
        "currency": c.currency,
        "stash_currency": c.stash_currency,
        "items": len(c.inventory),
        "xp": c.experience,
        "level": c.level,
        "deaths": c.deaths,
        "weapon": str(weapon) if weapon else None,
        "ammo": getattr(weapon, "current_capacity", None),
    }


def anomalies(row: dict) -> List[str]:
    """What should never be true of a character between ticks."""
    found = []
    if row["x"] is None:
        found.append("character has no location")
    if not 0 < row["hp"] <= row["hp_max"]:
        found.append(f"hp {row['hp']} outside (0, {row['hp_max']}]")
    if row["dead"]:
        found.append("character still dead after the tick")
    if row["currency"] < 0 or row["stash_currency"] < 0:
        found.append(f"negative money {row['currency']} / {row['stash_currency']}")
    if row["ammo"] is not None and row["ammo"] < 0:
        found.append(f"weapon fired past empty: ammo {row['ammo']}")
    if row["weapon"] is None:
        found.append("no weapon, not even fists")
    return found


def simulate(
    ticks: int = 300,
    bots: int = 4,
    seed: int = 0,
    size: int = 256,
    html: Optional[Path] = None,
) -> List[dict]:
    """Play `ticks` ticks and return one row per bot per tick (plus the world's own events on each). With
    `html`, also draw the run there."""
    world = GameSpace.World(
        "Sim", size, size, seed=seed
    )  # seeds `random` too, so a run replays
    adapter = WorldAdapter(world)
    players = [
        Bot(adapter, i, reach=random.choice([5, 15, 40, 80])) for i in range(bots)
    ]
    rows = []
    faulthandler.dump_traceback_later(HANG, exit=True)
    try:
        for tick in range(ticks):
            orders = [(bot, *bot.order()) for bot in players]
            results: Dict[Bot, dict] = {}
            for bot, label, action in random.sample(
                orders, len(orders)
            ):  # same-tick orders, random order
                start = time.perf_counter()
                where, deaths = bot.character.location, bot.character.deaths
                bot.entered = None
                try:
                    out = action()  # responses, or a stash receipt string
                    text = (
                        [r.text for r in out if r.text]
                        if isinstance(out, list)
                        else [out]
                    )
                    error = None
                except Exception as e:
                    if error_text(e) is None:
                        raise  # a bug, not a rule: let the test show it
                    text, error = [], error_text(e)
                results[bot] = {
                    "order": label,
                    "text": text,
                    "error": error,
                    "order_seconds": round(time.perf_counter() - start, 4),
                }
                if bot.character.deaths != deaths:
                    results[bot]["died_at"] = _death(bot.entered or where, label.split()[0])
            by_character: Dict[Actors.Actor, dict] = {
                bot.character: results[bot] for bot in players
            }
            before = {bot: (bot.character.location, bot.character.deaths) for bot in players}
            for event in world.tick():  # what the cog would DM
                if event.target in by_character:
                    by_character[event.target].setdefault("world", []).append(
                        event.text
                    )
            for bot, (where, deaths) in before.items():
                if bot.character.deaths != deaths:
                    results[bot]["died_at"] = _death(where, "npc on the map")
            for bot in players:
                row = {
                    "tick": tick,
                    **snapshot(world, bot.character),
                    **results[bot],
                    "npcs": len(world.npcs),
                    "chunks": len(world.loaded_chunks()),
                }
                row["anomalies"] = anomalies(row)
                if row["order_seconds"] > SLOW_ORDER:
                    row["anomalies"].append(f"slow order: {row['order_seconds']}s")
                rows.append(row)
    finally:
        faulthandler.cancel_dump_traceback_later()
    if html:
        report(rows, world, players, seed, Path(html))
    return rows


def report(rows: List[dict], world: GameSpace.World, players: List[Bot], seed: int, path: Path):
    """Fill in sim_template.html with this run: the explored map as a picture, and each bot's numbers by tick."""
    renderer = WindowRenderer(WorldAdapter(world))
    chunks = world.loaded_chunks()
    cx0, cy0 = min(c[0] for c in chunks), min(c[1] for c in chunks)
    cx1, cy1 = max(c[0] for c in chunks), max(c[1] for c in chunks)
    side = GameSpace.CHUNK_SIZE * MAP_PX
    image = Image.new("RGB", ((cx1 - cx0 + 1) * side, (cy1 - cy0 + 1) * side), (24, 24, 24))
    for cx, cy in chunks:
        png = renderer.chunk_png(cx, cy)
        assert png is not None  # it's loaded: that's where the list came from
        tile = Image.open(io.BytesIO(png)).resize((side, side), Image.Resampling.BOX)
        image.paste(tile, ((cx - cx0) * side, (cy - cy0) * side))
    buffer = io.BytesIO()
    image.save(buffer, "PNG", optimize=True)

    by_name: Dict[str, List[dict]] = {}
    for r in rows:
        by_name.setdefault(r["name"], []).append(r)
    bots = []
    for bot in players:
        mine = by_name[bot.character.name]
        bots.append(
            {
                "name": bot.character.name,
                "reach": bot.reach,
                "weapon": (mine[-1]["weapon"] or "").split("	")[0],
                "x": [r["x"] for r in mine],
                "y": [r["y"] for r in mine],
                "level": [r["level"] for r in mine],
                "worth": [r["currency"] + r["stash_currency"] for r in mine],
                "distance": [r["town_distance"] for r in mine],
                "deaths": [r["deaths"] for r in mine],
                "died": [[r["died_at"]["x"], r["died_at"]["y"], r["tick"]] for r in mine if "died_at" in r],
            }
        )
    data = {
        "seed": seed,
        "size": world.width,
        "chunks": len(chunks),
        "kills": world.stats.kills,
        "origin": [cx0 * GameSpace.CHUNK_SIZE, cy0 * GameSpace.CHUNK_SIZE],
        "squares": [(cx1 - cx0 + 1) * GameSpace.CHUNK_SIZE, (cy1 - cy0 + 1) * GameSpace.CHUNK_SIZE],
        "town": [world.starting_town.x, world.starting_town.y],
        "map": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode(),
        "bots": bots,
        "anomalies": [[r["tick"], r["name"], a] for r in rows for a in r["anomalies"]],
    }
    blob = json.dumps(data, separators=(",", ":")).replace("</", r"<\/")  # no early </script>
    page = REPORT_TEMPLATE.read_text(encoding="utf-8").replace("/*DATA*/null", blob)
    path.write_text(page, encoding="utf-8")


def summary(rows: List[dict]) -> str:
    last = {r["name"]: r for r in rows}
    lines = [
        f"{len(rows)} rows, {rows[-1]['tick'] + 1} ticks, {rows[-1]['chunks']} chunks, {rows[-1]['npcs']} npcs"
    ]
    for name, r in last.items():
        mine = [x for x in rows if x["name"] == name]
        lines.append(
            f"  {name}: level {r['level']}, deaths {r['deaths']}, ${r['currency']} + ${r['stash_currency']} stashed, "
            f"furthest {max(x['town_distance'] for x in mine)}, max danger {max(x['danger'] for x in mine)}, "
            f"weapon {r['weapon']}"
        )
    orders = Counter(r["order"].split()[0] for r in rows)
    lines.append(f"  orders: {dict(orders)}")
    lines.append(f"  errors: {dict(Counter(r['error'] for r in rows if r['error']))}")
    deaths = Counter(
        f"{d['cause']} in {d['space']} danger {d['danger']}" for r in rows if (d := r.get("died_at"))
    )
    lines.append(f"  deaths, by what the bot was doing and where it fell: {dict(deaths.most_common())}")
    found = Counter(a.split(":")[0] for r in rows for a in r["anomalies"])
    lines.append(f"  anomalies: {dict(found) or 'none'}")
    slowest = max(rows, key=lambda r: r["order_seconds"])
    lines.append(
        f"  slowest order: {slowest['order']} {slowest['order_seconds']}s at tick {slowest['tick']}"
    )
    return "\n".join(lines)


def test_simulated_players_break_no_rules(tmp_path):
    rows = simulate(ticks=300, bots=4, html=tmp_path / "sim.html")
    assert '"name":"bot0"' in (tmp_path / "sim.html").read_text(encoding="utf-8")
    bad = [
        (r["tick"], r["name"], a)
        for r in rows
        for a in r["anomalies"]
        if not a.startswith(KNOWN)
    ]
    assert not bad, f"{len(bad)} anomalies, first: {bad[:5]}\n{summary(rows)}"
    assert any(r["space"] == "Wilds" for r in rows), "nobody ever left town"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--ticks", type=int, default=2000)
    parser.add_argument("--bots", type=int, default=6)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--size", type=int, default=256)
    parser.add_argument("--out", help="write every row here as JSON lines")
    parser.add_argument("--html", help="draw the run as a standalone page here")
    args = parser.parse_args()
    rows = simulate(args.ticks, args.bots, args.seed, args.size, args.html)
    if args.out:
        with open(args.out, "w") as f:
            f.writelines(json.dumps(r, default=str) + "\n" for r in rows)
    print(summary(rows))
