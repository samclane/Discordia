"""
Player simulator: a few bots play the game through WorldAdapter, one order per tick each, with World.tick() in
lockstep the way the cog runs it. Every tick of every bot is logged, and the run is checked for things that
should never happen (anomalies).

The test is a short smoke run. For a long one to dig through:

    python -m Discordia.test.test_simulation --ticks 5000 --bots 8 --out sim.jsonl --html sim.html

which prints a summary, writes one JSON line per bot per tick (load it with pandas.read_json(lines=True)), and
draws the run as a standalone page: trails and deaths on the explored map, and level, money, range and deaths
over time (sim_template.html is the template). It also appends the run's headline numbers to sim_history.jsonl
(skip with --no-record); `python -m Discordia.test.sim_history` draws those across runs, to spot drift.
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
from datetime import datetime, timezone
from statistics import mean
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from PIL import Image

from Discordia.GameLogic import Actors, Events, GameSpace, Items, Weapons
from Discordia.GameLogic.GameSpace import DIRECTION_VECTORS, Town
from Discordia.Interface.Rendering.DesktopApp import WindowRenderer
from Discordia.Interface.WorldAdapter import WorldAdapter, error_text
from Discordia.test import sim_history

DIRECTIONS = [d for k, d in DIRECTION_VECTORS.items() if k]
TRADES = {c().name for c in (Actors.Scavenger, Actors.Medic, Actors.Scout, Actors.Fixer)}  # what trade towns train
COMPASS = [(0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1)]  # clockwise from north
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
        # Half the bots never rob a stranger, so trade classes survive a run as well as Raiders turn up.
        self.robs = member_id % 2 == 1
        # A third enlist instead, at the first military base they rest in, so the side rules show in the runs too.
        self.enlists = member_id % 3 == 0
        self.goal = self._pick_goal()
        self.steps_out = 0
        self.entered: Optional[GameSpace.Space] = None  # the square this tick's move stepped into, if any

    def order(self) -> Tuple[str, Callable[[], Any]]:
        """Pick this tick's order: (label, thunk), like a slash command handing the cog an action."""
        c, a = self.character, self.adapter
        if isinstance(c.pending_event, Events.EncounterEvent):
            choice = random.choice([c for c in Events.EncounterEvent.CHOICES if self.robs or c != "rob"])
            return f"choose {choice}", lambda: a.resolve_encounter(c, choice)
        if any(n.location == c.location for n in a.get_nearby_npcs(c)):
            return "attack", lambda: [a.attack(c, (0, 0))]
        if (armor := self._better_armor()) is not None:  # /inventory equip, for what a cache or a corpse gave it
            return f"equip {armor.name}", lambda: c.equip(armor) or []
        if isinstance(town := c.location, Town):
            self.steps_out = 0
            self.goal = self._pick_goal()
            base = isinstance(town.industry, GameSpace.MilitaryBase)
            if isinstance(c.player_class, Actors.WandererClass) and (
                base if self.enlists else not base and not isinstance(town.industry, GameSpace.NullIndustry)
            ):  # the first trade town it's in trains it, or the first base for one that enlists
                return "recruit", lambda: [town.recruit(c)]
            if c.hit_points < c.hit_points_max:
                return "inn", lambda: [town.inn_event(c)]
            if isinstance(gun := c.weapon, Weapons.Fist):
                if (best := self._best_gun(town)) is not None:
                    gun, cost = best
                    if cost > c.currency:  # re-arm after a death
                        return f"take ${cost - c.currency}", lambda: c.stash_take(money=cost - c.currency)
                    return f"buy {gun.name}", lambda: self._buy(town, gun)
                # Broke and bare-fisted: odd jobs until a gun is in reach, if this store has one left to save for.
                if any(isinstance(i, Weapons.Weapon) for i in town.store.inventory):
                    return "work", (lambda: []) if c.work_until is not None else lambda: a.work(c)
            elif isinstance(gun, Weapons.ProjectileWeapon) and not any(map(self._ammo_for(gun), c.inventory)):
                if (buy := self._cheapest(town, self._ammo_for(gun))) is not None:
                    return f"buy {buy.name}", lambda: self._buy(town, buy)
            if c.currency > 100:
                money = c.currency - 100  # bank all but walking-around money
                return f"stash ${money}", lambda: c.stash_put(money=money)
        hurt = c.hit_points < c.hit_points_max * 0.4
        # Bare-fisted out there (a death in town, or a gun sold), it keeps to danger 1 on the way home.
        unarmed = isinstance(c.weapon, Weapons.Fist) and a.world.danger_at(c.location) > 1
        if hurt or unarmed or self.steps_out >= self.reach:
            return "go home", lambda: self._step(
                _toward(c.location, a.world.starting_town)
            )
        self.steps_out += 1
        step = _toward(c.location, self.goal) if random.random() < 0.7 else random.choice(DIRECTIONS)
        return "raid", lambda: self._step(step)

    def _better_armor(self) -> Optional[Items.ArmorAbstract]:
        """Armor in the pack worth more than what's worn in its slot, or None. Worth, not armor_count: that's a
        roll against the piece's coverage, a fresh one every hit."""
        worn = self.character.equipment_set
        for item in self.character.inventory:
            if isinstance(item, Items.ArmorAbstract) and not item.is_equipped:
                slot = next(name for name, kind in Items.EquipmentSet.SLOTS.items() if isinstance(item, kind))
                if item.base_value > getattr(worn, slot).base_value:
                    return item
        return None

    def _pick_goal(self) -> GameSpace.Space:
        """Where this raid heads: the nearest stocked cache within `reach` of the starting town, as /raid goes for
        one, or else somewhere `reach` squares out at any bearing."""
        world, town = self.adapter.world, self.adapter.world.starting_town
        caches = [cache for cache in world.stocked_caches() if town.distance(cache) <= self.reach]
        if caches:
            return min(caches, key=town.distance)
        angle = random.uniform(0, 2 * math.pi)
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
            if test(item) and store.get_price(item, self.character) <= self.character.currency
        ]
        return min(fits, key=lambda item: store.get_price(item, self.character), default=None)

    @staticmethod
    def _ammo_for(gun: Weapons.ProjectileWeapon):
        return lambda item: isinstance(item, Items.Ammo) and item.caliber == gun.caliber

    def _best_gun(self, town: Town):
        """(gun, cost) for the most damaging weapon here it can pay for with a box of its ammo, cash and stash
        together, as a player would shop; or None. Guns come loaded, so one with no ammo on the shelf still counts."""
        c, store = self.character, town.store
        options = []
        for gun in store.inventory:
            if isinstance(gun, Weapons.Weapon):
                cost = store.get_price(gun, c)
                if isinstance(gun, Weapons.ProjectileWeapon):
                    ammo = [store.get_price(i, c) for i in store.inventory if self._ammo_for(gun)(i)]
                    cost += min(ammo, default=0)
                if cost <= c.currency + c.stash_currency:
                    options.append((gun, cost))
        return max(options, key=lambda option: (option[0].damage, -option[1]), default=None)

    def _buy(self, town: Town, item):
        """Buy `item` if it's still there: another bot in the same town may have bought it first this tick."""
        c = self.character
        index = next((i for i, x in enumerate(town.store.inventory) if x is item), None)
        if index is not None and town.store.sell_item(index, c) and not isinstance(item, Items.Ammo):
            c.equip(item)
        return []

    def _careful(self, direction):
        """`direction`, or the step either side of it if that one keeps better cover: ruins over open ground over
        a plaza (World.prey_in_sight), the way a player reading the map would go."""
        if direction not in COMPASS:
            return direction
        here, world, i = self.character.location, self.adapter.world, COMPASS.index(direction)

        def exposure(d):
            x, y, size = here.x + d[0], here.y + d[1], GameSpace.CHUNK_SIZE
            # Only squares already loaded: looking must not generate the map ahead of the walk.
            rows = world.loaded_chunk(x // size, y // size) if 0 <= x < world.width and 0 <= y < world.height else None
            terrain = rows[y % size][x % size].terrain if rows else None
            if isinstance(terrain, GameSpace.RuinsTerrain):
                return 0
            return 2 if isinstance(terrain, GameSpace.PlazaTerrain) else 1

        return min([direction, COMPASS[i - 1], COMPASS[(i + 1) % 8]], key=exposure)  # ties keep the bearing

    def _step(self, direction):
        """A move, sidestepping water and map edges the way a player would retry another direction."""
        for d in [self._careful(direction)] + random.sample(DIRECTIONS, len(DIRECTIONS)):
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
        "class": c.player_class.name,
        "deaths": c.deaths,
        "achievements": len(c.achievements),
        "armor": sum(isinstance(i, Items.ArmorAbstract) and i.base_value > 0 for i in c.equipment_set),
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
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),  # when the run was
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


def problems(rows: List[dict]) -> List[str]:
    """Every error and anomaly, one line each, with the tick and bot to look them up by."""
    return [
        f"tick {r['tick']}, {r['name']} ({r['order']}): {problem}"
        for r in rows
        for problem in ([r["error"]] if r["error"] else []) + r["anomalies"]
    ]


def metrics(rows: List[dict]) -> Dict[str, float]:
    """The run's headline numbers, for sim_history: where the bots ended up, and what went wrong on the way."""
    last = list({r["name"]: r for r in rows}.values())
    furthest = [max(x["town_distance"] for x in rows if x["name"] == r["name"]) for r in last]
    return {
        "mean level": round(mean(r["level"] for r in last), 2),
        "top level": max(r["level"] for r in last),
        "deaths": sum(r["deaths"] for r in last),
        "mean achievements": round(mean(r["achievements"] for r in last), 2),
        "trade classes (share of bots)": round(mean(r["class"] in TRADES for r in last), 2),
        "raiders (share of bots)": round(mean(r["class"] == Actors.RaiderClass().name for r in last), 2),
        "soldiers (share of bots)": round(mean(r["class"] == Actors.Soldier().name for r in last), 2),
        "mean armor worn (pieces)": round(mean(r["armor"] for r in last), 2),
        "mean worth ($, carried + stashed)": round(mean(r["currency"] + r["stash_currency"] for r in last)),
        "mean furthest from town (squares)": round(mean(furthest), 1),
        "max danger reached": max(r["danger"] for r in rows),
        "errors": sum(1 for r in rows if r["error"]),
        "anomalies": sum(len(r["anomalies"]) for r in rows),
        "npcs at the end": rows[-1]["npcs"],
        "chunks explored": rows[-1]["chunks"],
        "slowest order (s)": round(max(r["order_seconds"] for r in rows), 3),
    }


def test_a_run_is_recorded_and_drawn(tmp_path):
    history = tmp_path / "history.jsonl"
    rows = simulate(ticks=20, bots=2)
    sim_history.record("game", {"ticks": 20}, metrics(rows), history)
    sim_history.record("server", {"ticks": 20}, {"messages sent": 3}, history)
    runs = sim_history.load(history)
    assert [r["kind"] for r in runs] == ["game", "server"] and "mean level" in runs[0]["metrics"]
    assert runs[0]["at"] and runs[0]["commit"]
    sim_history.report(runs, tmp_path / "history.html")
    page = (tmp_path / "history.html").read_text(encoding="utf-8")
    assert '"messages sent":3' in page and 'const DRAWN = "20' in page, "says when it was drawn"
    sim_history.record("server", {"ticks": 20}, {"messages sent": 5, "run time (s)": 9}, history)
    assert sim_history.drift(sim_history.load(history)).endswith(": messages sent 3 -> 5")  # timings left out


def test_simulated_players_break_no_rules(tmp_path):
    rows = simulate(ticks=300, bots=4, html=tmp_path / "sim.html")
    page = (tmp_path / "sim.html").read_text(encoding="utf-8")
    assert '"name":"bot0"' in page and '"at":"20' in page, "says when it was run"
    bad = [
        (r["tick"], r["name"], a)
        for r in rows
        for a in r["anomalies"]
        if not a.startswith(KNOWN)
    ]
    assert not bad, f"{len(bad)} anomalies, first: {bad[:5]}\n{summary(rows)}"
    assert any(r["space"] == "Wilds" for r in rows), "nobody ever left town"



def test_bots_skirt_plazas_and_cut_through_ruins():
    world = GameSpace.World("Cover", 64, 64, seed=0)
    bot = Bot(WorldAdapter(world), 1, reach=5)
    here = bot.character.location = world.space_at(30, 30)
    for d, terrain in [((1, 0), GameSpace.PlazaTerrain()), ((1, 1), GameSpace.RuinsTerrain())]:
        world.space_at(here.x + d[0], here.y + d[1]).terrain = terrain
    world.space_at(here.x + 1, here.y - 1).terrain = GameSpace.SandTerrain()
    assert bot._careful((1, 0)) == (1, 1)  # east is a plaza; the ruins to the south-east hide you
    world.space_at(here.x + 1, here.y + 1).terrain = GameSpace.SandTerrain()
    assert bot._careful((1, 0)) in [(1, -1), (1, 1)]  # off the plaza either way
    for d in [(0, 1), (-1, 1)]:
        world.space_at(here.x + d[0], here.y + d[1]).terrain = GameSpace.SandTerrain()
    assert bot._careful((0, 1)) == (0, 1)  # nothing better beside it: keep the bearing


def test_bots_take_the_class_of_the_first_trade_town_they_are_in():
    world = GameSpace.World("Recruits", 64, 64, seed=0)
    bot = Bot(WorldAdapter(world), 1, reach=5)
    town = bot.character.location = world.starting_town
    town.industry = GameSpace.EasternMilitaryBase()
    assert bot.order()[0] != "recruit"  # a base trains soldiers, not a trade
    town.industry = GameSpace.MiningIndustry()
    label, act = bot.order()
    assert label == "recruit"
    act()
    assert isinstance(bot.character.player_class, Actors.Scavenger)


def test_some_bots_enlist_at_the_first_military_base_instead():
    world = GameSpace.World("Recruits", 64, 64, seed=0)
    bot = Bot(WorldAdapter(world), 3, reach=5)
    assert bot.enlists and not Bot(WorldAdapter(world), 1, reach=5).enlists
    town = bot.character.location = world.starting_town
    town.industry = GameSpace.MiningIndustry()
    assert bot.order()[0] != "recruit"  # holds out for a base
    town.industry = GameSpace.WesternMilitaryBase()
    label, act = bot.order()
    assert label == "recruit"
    act()
    assert isinstance(bot.character.player_class, Actors.Soldier) and bot.character.side == "West"
    assert bot.order()[0] != "recruit"  # once is enough


def test_an_unarmed_bot_keeps_to_danger_one():
    world = GameSpace.World("Broke", 256, 256, seed=0)
    bot = Bot(WorldAdapter(world), 1, reach=80)
    town = world.starting_town
    bot.character.location = deep = next(
        world.space_at(x, town.y) for x in range(town.x + 1, world.width) if world.danger_at(world.space_at(x, town.y)) == 2
    )
    assert isinstance(bot.character.weapon, Weapons.Fist)
    assert bot.order()[0] == "go home"
    bot.character.location = world.space_at(deep.x - 1, deep.y)  # the first danger-2 square out: this is danger 1
    assert bot.order()[0] == "raid"  # still raids the shallow end, for a cache or a kill
    bot.character.location = deep
    bot.character.equip(Weapons.Hammer())
    assert bot.order()[0] == "raid"


def test_a_broke_bare_fisted_bot_works_shifts_until_it_can_buy_a_gun():
    world = GameSpace.World("Broke", 128, 128, seed=0)
    bot = Bot(WorldAdapter(world), 2, reach=5)  # neither enlists nor recruits first: a Wanderer in a plain town
    c = bot.character
    c.location, c.currency, c.player_class = world.starting_town, 0, Actors.Scavenger()
    assert bot.order()[0] == "work"
    for _ in range(100):  # a few shifts at most
        label, act = bot.order()
        if label != "work":
            break
        act()
        world.advance(Actors.WORK_PAY_TICKS)
    assert label.startswith("buy") and c.location is world.starting_town, label


def test_a_bare_fisted_bot_buys_the_most_damaging_gun_it_can_pay_for_with_its_ammo():
    world = GameSpace.World("Shop", 64, 64, seed=0)
    bot = Bot(WorldAdapter(world), 2, reach=5)
    c = bot.character
    town = c.location = world.starting_town
    c.player_class = Actors.Scavenger()
    town.store = GameSpace.Store([Weapons.StechkinAPS(), Weapons.L1A1(), Weapons.Ammo9mm(), Weapons.Ammo762()])
    rifle = town.store.get_price(Weapons.L1A1()) + town.store.get_price(Weapons.Ammo762())
    c.currency, c.stash_currency = rifle - 1, 0  # the rifle alone, but not its ammo too
    assert bot.order()[0] == "buy Stechkin Automatic Pistol"
    c.stash_currency = 1  # with the stash, rifle and ammo
    label, act = bot.order()
    assert label == "take $1"
    act()
    label, act = bot.order()
    assert label == "buy L1A1 (FN FAL)"
    act()
    assert isinstance(c.weapon, Weapons.L1A1) and bot.order()[0] == "buy 7.62mm rounds", bot.order()[0]


def test_bots_raid_for_the_nearest_stocked_cache_in_reach():
    world = GameSpace.World("Caches", 128, 128, seed=0)
    bot = Bot(WorldAdapter(world), 2, reach=10)
    town = world.starting_town
    near, far = GameSpace.Cache(town.x + 6, town.y), GameSpace.Cache(town.x + 30, town.y)
    world.caches = [far, near]
    assert bot._pick_goal() is near, "as /raid goes for one"
    near.looted_at = world.ticks
    goal = bot._pick_goal()
    assert goal is not near and goal is not far, "emptied, or out of reach: anywhere at its reach instead"
    assert round(town.distance(goal)) <= 10


def test_bots_wear_found_armor_that_beats_what_they_have_on():
    from Discordia.GameLogic import Armor

    world = GameSpace.World("Loot", 64, 64, seed=0)
    bot = Bot(WorldAdapter(world), 1, reach=5)
    c = bot.character
    c.location = world.space_at(30, 30)
    c.inventory += [Armor.SSh68(), Armor.Chest6B45()]
    for _ in range(2):
        label, act = bot.order()
        assert label.startswith("equip ")
        act()
    assert isinstance(c.equipment_set.head, Armor.SSh68) and isinstance(c.equipment_set.chest, Armor.Chest6B45)
    c.inventory.append(Armor.SSh68())  # no better than the helmet on
    assert not bot.order()[0].startswith("equip")


def test_only_some_bots_rob_strangers(monkeypatch):
    adapter = WorldAdapter(GameSpace.World("Strangers", 64, 64, seed=0))
    honest, robber = Bot(adapter, 0, reach=5), Bot(adapter, 1, reach=5)
    for bot in (honest, robber):
        bot.character.pending_event = Events.EncounterEvent(1.0, "<test>", Actors.NPC(adapter.world, 25, "Stranger"))
    monkeypatch.setattr(random, "choice", lambda options: options[1])  # talk, rob, ignore: the middle one
    assert honest.order()[0] == "choose ignore"  # "rob" was never on its list
    assert robber.order()[0] == "choose rob"


def test_problems_say_which_tick_and_bot():
    rows = [
        {"tick": 3, "name": "bot1", "order": "attack", "error": "Attack failed", "anomalies": ["hp below 0"]},
        {"tick": 4, "name": "bot2", "order": "raid", "error": None, "anomalies": []},
    ]
    assert problems(rows) == ["tick 3, bot1 (attack): Attack failed", "tick 3, bot1 (attack): hp below 0"]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--ticks", type=int, default=2000)
    parser.add_argument("--bots", type=int, default=6)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--seeds", type=int, default=1, help="run this many seeds from --seed and record their means")
    parser.add_argument("--size", type=int, default=256)
    parser.add_argument("--out", help="write every row here as JSON lines")
    parser.add_argument("--html", help="draw the run as a standalone page here")
    parser.add_argument("--no-record", action="store_true", help="leave sim_history.jsonl alone")
    args = parser.parse_args()
    began = time.perf_counter()
    rows = simulate(args.ticks, args.bots, args.seed, args.size, args.html)  # the first seed is the one drawn
    # One seed's deaths swing 1-29 with the map it rolls, so a change only shows in the mean over many.
    runs, found = [metrics(rows)], problems(rows)
    for seed in range(args.seed + 1, args.seed + args.seeds):
        more = simulate(args.ticks, args.bots, seed, args.size)
        runs.append(metrics(more))
        found += [f"seed {seed}, {line}" for line in problems(more)]
    means = {k: round(mean(m[k] for m in runs), 2) for k in runs[0]}
    if not args.no_record:
        params = {"ticks": args.ticks, "bots": args.bots, "seed": args.seed, "size": args.size}
        if args.seeds > 1:  # left out of single runs, so their history still lines up
            params["seeds"] = args.seeds
        sim_history.record("game", params, {**means, "run time (s)": round(time.perf_counter() - began, 1)})
    if args.out:
        with open(args.out, "w") as f:
            f.writelines(json.dumps(r, default=str) + "\n" for r in rows)
    print(summary(rows))
    if args.seeds > 1:
        print(f"means over seeds {args.seed}-{args.seed + args.seeds - 1}: {means}")
        # The summary above is the first seed's: say where the others' errors are, or a mean of 0.1 can't be found.
        print("\n".join(found) or "no errors or anomalies in any seed")
