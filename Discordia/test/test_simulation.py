"""
Player simulator: a few bots play the game through WorldAdapter, one order per tick each, with World.tick() in
lockstep the way the cog runs it. Every tick of every bot is logged, and the run is checked for things that
should never happen (anomalies).

The test is a short smoke run. For a long one to dig through:

    python -m Discordia.test.test_simulation --ticks 5000 --bots 8 --out sim.jsonl

which prints a summary and writes one JSON line per bot per tick (load it with pandas.read_json(lines=True)).
"""

import argparse
import faulthandler
import json
import random
import time
from collections import Counter
from typing import Any, Callable, Dict, List, Tuple

from Discordia.GameLogic import Actors, Events, GameSpace, Items, Weapons
from Discordia.GameLogic.GameSpace import DIRECTION_VECTORS, Town
from Discordia.Interface.WorldAdapter import WorldAdapter, error_text

DIRECTIONS = [d for k, d in DIRECTION_VECTORS.items() if k]
SLOW_ORDER = 1.0  # seconds; an order this slow is worth a look (CombatEvent can spin)
HANG = 300  # seconds for a whole run before faulthandler dumps every stack and exits
# Anomalies already on ROADMAP.md, so the test stays green until they're fixed. Delete one when its fix lands.
KNOWN: Tuple[str, ...] = ()


def _toward(here, there):
    return (
        (there.x > here.x) - (there.x < here.x),
        (there.y > here.y) - (there.y < here.y),
    )


class Bot:
    """One player's habits. `reach` is how many steps out it raids before heading home: its appetite for risk."""

    def __init__(self, adapter: WorldAdapter, member_id: int, reach: int):
        adapter.register_player(member_id, f"bot{member_id}")
        self.adapter = adapter
        self.character = adapter.get_player(member_id)
        self.reach = reach
        self.heading = random.choice(DIRECTIONS)
        self.steps_out = 0

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
            self.heading = random.choice(DIRECTIONS)
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
            if c.currency > 100:
                money = c.currency - 100  # bank all but walking-around money
                return f"stash ${money}", lambda: c.stash_put(money=money)
        hurt = c.hit_points < c.hit_points_max * 0.4
        if hurt or self.steps_out >= self.reach:
            return "go home", lambda: self._step(
                _toward(c.location, a.world.starting_town)
            )
        self.steps_out += 1
        step = self.heading if random.random() < 0.7 else random.choice(DIRECTIONS)
        return "raid", lambda: self._step(step)

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
            try:
                return self.adapter.move_player(self.character, d)
            except Exception as e:
                if error_text(e) is None:
                    raise
        return []


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
    ticks: int = 300, bots: int = 4, seed: int = 0, size: int = 256
) -> List[dict]:
    """Play `ticks` ticks and return one row per bot per tick (plus the world's own events on each)."""
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
            by_character: Dict[Actors.Actor, dict] = {
                bot.character: results[bot] for bot in players
            }
            for event in world.tick():  # what the cog would DM
                if event.target in by_character:
                    by_character[event.target].setdefault("world", []).append(
                        event.text
                    )
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
    return rows


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
    deaths = Counter()
    for prev, r in zip(rows, rows[len(last) :]):
        if r["deaths"] > prev["deaths"]:
            deaths[prev["danger"]] += 1
    lines.append(
        f"  deaths by danger level stood in the tick before: {dict(sorted(deaths.items()))}"
    )
    found = Counter(a.split(":")[0] for r in rows for a in r["anomalies"])
    lines.append(f"  anomalies: {dict(found) or 'none'}")
    slowest = max(rows, key=lambda r: r["order_seconds"])
    lines.append(
        f"  slowest order: {slowest['order']} {slowest['order_seconds']}s at tick {slowest['tick']}"
    )
    return "\n".join(lines)


def test_simulated_players_break_no_rules():
    rows = simulate(ticks=300, bots=4)
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
    args = parser.parse_args()
    rows = simulate(args.ticks, args.bots, args.seed, args.size)
    if args.out:
        with open(args.out, "w") as f:
            f.writelines(json.dumps(r, default=str) + "\n" for r in rows)
    print(summary(rows))
