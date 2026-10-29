"""
Unit tests for the parts of the game rules that don't need a rendered world: weapon maths, geometry,
equipment, stores, events, and the adapter's error contract.

test_all.py already drives a full 100x100 world; these stay small and fast on purpose.
"""

import random

import pytest

from Discordia.GameLogic import (
    Actors,
    Armor,
    Behavior,
    Events,
    GameSpace,
    Items,
    Weapons,
)
from Discordia.GameLogic.GameSpace import (
    DIRECTION_VECTORS,
    GrassTerrain,
    MountainTerrain,
    NullTerrain,
    SandTerrain,
    Space,
    Store,
    Town,
    WaterTerrain,
    Wilds,
)
from Discordia.GameLogic.Items import (
    ChestArmorAbstract,
    EquipmentSet,
    MainHandEquipment,
)
from Discordia.Interface.WorldAdapter import (
    AlreadyRegisteredException,
    CombatException,
    InvalidSpaceException,
    NoEncounterException,
    NoMerchantException,
    NoWeaponEquippedException,
    NotRegisteredException,
    WorldAdapter,
)

WORLD_SIZE = 40
WORLD_SEED = 0


@pytest.fixture
def adapter() -> WorldAdapter:
    """A small world with one registered player. Fresh per test: the tests below move and maim him."""
    world = GameSpace.World("Test World", WORLD_SIZE, WORLD_SIZE, seed=WORLD_SEED)
    for x in range(
        0, WORLD_SIZE, GameSpace.CHUNK_SIZE
    ):  # generate all of it, not just round the spawn
        for y in range(0, WORLD_SIZE, GameSpace.CHUNK_SIZE):
            world.space_at(x, y)
    adapter = WorldAdapter(world)
    adapter.register_player(1, "Tester")
    return adapter


# --- Weapon construction: the constructors are the only validation these have -------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"base_damage": -1},
        {"base_damage": 1, "range_": 0},
        {"base_damage": 1, "range_falloff": 1.5},
        {"base_damage": 1, "range_falloff": -0.1},
        {"base_damage": 1, "capacity": 0},
    ],
)
def test_projectile_weapon_rejects_nonsense(kwargs):
    with pytest.raises(ValueError):
        Weapons.ProjectileWeapon(
            projectile_type=Weapons.ProjectileType.Bullet, **kwargs
        )


def test_shotgun_needs_at_least_two_pellets():
    with pytest.raises(ValueError):
        Weapons.Shotgun(pellet_count=1, caliber=Weapons.Caliber.MM_762, base_damage=5)


def test_burst_fire_requires_a_burst_capable_action():
    with pytest.raises(ValueError):
        Weapons.Firearm(
            caliber=Weapons.Caliber.MM_762,
            action=Weapons.FiringAction.SemiAutomatic,
            burst_size=3,
            capacity=30,
            base_damage=5,
        )


def test_single_shot_capacity_forces_single_shot_action():
    musket = Weapons.Jezail()
    assert musket.is_single_shot
    assert musket.action == Weapons.FiringAction.SingleShot


def test_melee_weapon_chances_must_be_probabilities():
    with pytest.raises(ValueError):
        Weapons.BladedWeapon(bleed_chance=2.0, bleed_factor=0.5, base_damage=1)
    with pytest.raises(ValueError):
        Weapons.BluntWeapon(cripple_chance=-1.0, base_damage=1)


# --- Firing --------------------------------------------------------------------------------------


def test_firing_drains_the_magazine_and_reload_refills_it():
    revolver = Weapons.WeblyRevolver()
    assert not revolver.is_empty
    for _ in range(revolver.capacity):
        revolver.on_damage()
    assert revolver.is_empty
    assert revolver.current_capacity == 0
    actor = Actors.PlayerCharacter(parent_world=None, name="Tester")
    actor.inventory.append(Items.Ammo(caliber=revolver.caliber, quantity=6))
    revolver.reload(actor)
    assert revolver.current_capacity == revolver.capacity
    assert actor.inventory.has_item(Items.Ammo(caliber=revolver.caliber)) is False


def test_burst_fire_costs_a_burst_worth_of_ammo_and_pays_a_burst_worth_of_damage():
    rifle = Weapons.AK47()
    rifle.burst_size = 3
    before = rifle.current_capacity
    rifle.on_damage()
    assert rifle.current_capacity == before - 3
    assert rifle.damage == 3 * rifle._base_damage


def test_damage_falls_off_with_distance():
    rifle = Weapons.AK47()  # 35% falloff per square
    assert rifle.calc_damage(0) == rifle.damage
    assert rifle.calc_damage(1) < rifle.calc_damage(0)
    assert rifle.calc_damage(5) < rifle.calc_damage(1)


def test_selective_fire_toggles_between_semi_and_full_auto():
    rifle = Weapons.AK47()
    rifle.toggle_action()
    assert rifle.action == Weapons.FiringAction.SemiAutomatic
    rifle.toggle_action()
    assert rifle.action == Weapons.FiringAction.FullyAutomatic


def test_unmountable_machine_guns_refuse_to_be_mounted():
    bipodless = Weapons.MachineGun(
        mountable=False,
        caliber=Weapons.Caliber.MM_762,
        action=Weapons.FiringAction.FullyAutomatic,
        capacity=100,
        base_damage=10,
    )
    with pytest.raises(AttributeError):
        bipodless.mounted = True

    minimi = Weapons.FNMinimi()
    minimi.mounted = True
    assert minimi.mounted


# --- Spaces and terrain ---------------------------------------------------------------------------


def test_space_rejects_negative_coordinates():
    with pytest.raises(ValueError):
        Space(-1, 0)


def test_moving_off_the_top_left_clamps_to_the_origin():
    assert Space(0, 0) + DIRECTION_VECTORS["nw"] == (0, 0)
    assert Space(3, 3) - (5, 1) == (0, 2)


def test_space_unpacks_as_a_coordinate_pair():
    space = Space(4, 7)
    assert tuple(space) == (4, 7)
    assert (space[0], space[1]) == (4, 7)
    with pytest.raises(ValueError):
        space[2]


def test_distance_is_euclidean():
    assert Space(0, 0).distance((3, 4)) == 5


def test_terrain_knows_which_neighbours_match_it(adapter):
    """The renderer kerbs a park or a canal from these bits, so they have to agree with the map."""
    world = adapter.world
    for space in [
        world.space_at(x, y) for x in range(5, 35, 7) for y in range(5, 35, 7)
    ]:
        expected = sum(
            1 << bit
            for bit, (dx, dy) in enumerate(GameSpace.NEIGHBOURS)
            if world.space_at(space.x + dx, space.y + dy).terrain.name
            == space.terrain.name
        )
        assert space.terrain.neighbours == expected


def test_wilds_pick_a_sprite_by_position():
    """Mixed sprites so the wilds aren't one tree stamped everywhere, but steady between redraws."""
    paths = {Wilds(x, 0, "Somewhere").sprite_path for x in range(50)}
    assert len(paths) == GameSpace.WILDS_SPRITES
    assert all(path.is_file() for path in paths)
    assert Wilds(3, 4, "A").sprite_path == Wilds(3, 4, "B").sprite_path


def test_terrain_cost_ranks_the_going_underfoot():
    costs = [
        GrassTerrain().cost,
        SandTerrain().cost,
        WaterTerrain().cost,
        MountainTerrain().cost,
    ]
    assert costs == sorted(costs)
    assert NullTerrain().cost > max(costs)
    assert not NullTerrain().walkable
    assert not WaterTerrain().buildable and not MountainTerrain().buildable


# --- Equipment ------------------------------------------------------------------------------------


def test_armor_count_sums_every_worn_piece():
    equipment_set = EquipmentSet()
    assert equipment_set.armor_count == 0
    equipment_set.equip(ChestArmorAbstract(armor_count=5))
    equipment_set.equip(Items.HeadArmorAbstract(armor_count=2))
    assert equipment_set.armor_count == 7


def test_armor_soaks_damage_before_hit_points():
    character = Actors.PlayerCharacter(parent_world=None, name="Tester")
    character.equip(ChestArmorAbstract(armor_count=5))
    character.take_damage(12)
    assert character.hit_points == character.hit_points_max - 7


def test_hit_points_never_exceed_the_maximum():
    character = Actors.PlayerCharacter(parent_world=None, name="Tester")
    character.hit_points = 10 * character.hit_points_max
    assert character.hit_points == character.hit_points_max


def test_changing_class_resets_the_health_pool():
    character = Actors.PlayerCharacter(parent_world=None, name="Tester")
    character.take_damage(10)
    character.player_class = Actors.Soldier()
    assert (
        character.hit_points
        == character.hit_points_max
        == Actors.Soldier().hit_points_max_base
    )


def test_unequipping_a_weapon_leaves_the_character_bare_handed():
    character = Actors.PlayerCharacter(parent_world=None, name="Tester")
    assert character.has_weapon_equipped
    assert character.weapon is not None
    character.unequip(character.weapon)
    assert character.weapon is None
    assert not character.has_weapon_equipped


def test_equipping_reports_itself_to_the_item():
    rifle = Weapons.Jezail()
    character = Actors.PlayerCharacter(parent_world=None, name="Tester")
    character.equip(rifle)
    assert rifle.is_equipped and rifle.player is character
    character.unequip(rifle)
    assert not rifle.is_equipped and rifle.player is None


def test_a_character_is_only_registered_once_it_stands_somewhere():
    character = Actors.PlayerCharacter(parent_world=None, name="Tester")
    assert not character.registered
    character.location = Space(1, 1)
    assert character.registered


# --- Towns and stores -------------------------------------------------------------------------------


def test_the_inn_heals_you_up():
    town = Town(1, 1, "Testville")
    character = Actors.PlayerCharacter(parent_world=None, name="Tester")
    character.take_damage(20)
    response = town.inn_event(character)
    assert response.is_successful
    assert character.hit_points == character.hit_points_max


def test_recruiting_promotes_you_once():
    town = Town(1, 1, "Fort Test", industry=GameSpace.EasternMilitaryBase())
    character = Actors.PlayerCharacter(parent_world=None, name="Tester")

    assert town.recruit(character).is_successful
    assert isinstance(character.player_class, Actors.Soldier)
    assert town.recruit(character).failed  # already a Solider; nothing left to offer


def test_a_wanderer_town_cannot_promote_a_wanderer():
    town = Town(1, 1, "Sleepy Hollow", industry=GameSpace.FarmingIndustry())
    character = Actors.PlayerCharacter(parent_world=None, name="Tester")
    assert town.recruit(character).failed


def test_store_price_follows_the_price_ratio():
    store = Store()
    store.price_ratio = 2.0
    rifle = Weapons.AK47()
    assert store.get_price(rifle) == 2 * rifle.base_value


def test_store_refuses_a_bad_index_or_an_empty_wallet():
    rifle = Weapons.AK47()
    store = Store([rifle])
    character = Actors.PlayerCharacter(parent_world=None, name="Tester")

    assert not store.sell_item(99, character)
    character.currency = 0
    assert not store.sell_item(0, character)
    assert rifle in store.inventory


def test_buying_moves_the_item_and_the_money():
    rifle = Weapons.AK47()
    store = Store([rifle])
    character = Actors.PlayerCharacter(parent_world=None, name="Tester")
    character.currency = 10_000
    purse = character.currency

    assert store.sell_item(0, character)
    assert rifle in character.inventory and rifle not in store.inventory
    assert character.currency == purse - store.get_price(rifle)


def test_selling_back_returns_the_item_to_the_shelf():
    rifle = Weapons.AK47()
    store = Store([])
    character = Actors.PlayerCharacter(parent_world=None, name="Tester")
    character.inventory.append(rifle)
    purse = character.currency

    price = store.buy_item(rifle, character)
    assert rifle in store.inventory and rifle not in character.inventory
    assert character.currency == purse + price


# --- Wilds and events -------------------------------------------------------------------------------


def test_adding_events_eats_into_the_do_nothing_chance():
    wilds = Wilds(1, 1, "The Nowhere")
    assert wilds.null_event.probability == 1.0

    event = Events.MerchantEvent(0.25, "<test>", Store())
    wilds.add_event(event)
    assert wilds.null_event.probability == pytest.approx(0.75)
    assert sum(e.probability for e in wilds.events) == pytest.approx(1.0)


def test_an_event_can_never_be_more_likely_than_whats_left():
    wilds = Wilds(1, 1, "The Nowhere")
    wilds.add_event(Events.MerchantEvent(5.0, "<greedy>", Store()))
    assert wilds.null_event.probability == 0
    assert wilds.events[-1].probability == 1.0


def test_a_quiet_wilds_reports_that_nothing_happened():
    """The null event runs empty: callers read 'no responses' as 'nothing to narrate'."""
    wilds = Wilds(1, 1, "The Nowhere")
    character = Actors.PlayerCharacter(parent_world=None, name="Tester")
    assert wilds.run_event(character) == []


def test_combat_ends_with_the_enemies_dead_and_their_kit_looted(adapter):
    enemy = Actors.NPC(None, 1, "Mook")
    enemy.inventory.append(Armor.Helmet())
    event = Events.CombatEvent(1.0, "<test>", [enemy])
    character = adapter.get_player(1)
    character.equip(Weapons.Hammer())

    responses = list(event.run(character))
    assert enemy.is_dead
    assert responses[-1].is_successful
    assert any(isinstance(item, Armor.Helmet) for item in character.inventory)


def test_the_wilds_get_rougher_the_further_you_go_from_the_spawn(adapter):
    """Levels were measured from a placeholder town at (0, 0), so a spawn anywhere else was ringed
    by wilds far too rough for a character who starts with fists."""
    world = adapter.world
    spawn = world.starting_town
    near = [wilds.level for wilds in world.wilds if spawn.distance(wilds) <= 8]
    far = [wilds.level for wilds in world.wilds if spawn.distance(wilds) >= 20]
    assert near and far

    assert min(near) == 1  # somewhere fightable on day one
    assert sum(near) / len(near) < sum(far) / len(far)
    assert 1 <= min(near) and max(far) <= GameSpace.WILDS_MAX_LEVEL


def test_danger_is_clamped_to_the_range_whatever_the_roll(adapter):
    world = adapter.world
    corners = [
        (0, 0),
        (world.width - 1, 0),
        (0, world.height - 1),
        (world.width - 1, world.height - 1),
    ]
    edge = Space(*max(corners, key=world.starting_town.distance))

    at_home = [world.danger_level(world.starting_town) for _ in range(50)]
    at_the_edge = [world.danger_level(edge) for _ in range(50)]
    assert min(at_home + at_the_edge) >= 1
    assert max(at_home + at_the_edge) <= GameSpace.WILDS_MAX_LEVEL
    assert sum(at_home) < sum(at_the_edge)


def test_a_world_too_small_to_roll_a_town_still_gets_one():
    """Town placement is a per-tile dice roll: a small map can roll none, and spawning needs one."""
    world = GameSpace.World("Pebble", 8, 8, seed=7)
    assert world.towns
    assert world.starting_town in world.towns


def _describe(world, cx, cy):
    rows = world.loaded_chunk(cx, cy)
    return [
        (type(s).__name__, s.name, s.terrain.name, s.terrain.neighbours)
        for row in rows
        for s in row
    ]


def test_a_chunk_comes_out_the_same_whatever_order_it_is_explored_in():
    """A save is only the seed, so a chunk must regenerate identically however players wandered into it."""
    one = GameSpace.World("Twin", 200, 200, seed=3)
    two = GameSpace.World("Twin", 200, 200, seed=3)
    one.space_at(0, 0)
    one.space_at(199, 199)
    two.space_at(199, 199)
    two.space_at(0, 0)
    for cx, cy in [(0, 0), (6, 6)]:
        assert _describe(one, cx, cy) == _describe(two, cx, cy)


def test_caches_sit_far_from_towns_and_each_other_and_pay_out_once():
    world = GameSpace.World("Stash", 640, 640, seed=5)
    for cx in range(640 // GameSpace.CHUNK_SIZE):
        for cy in range(640 // GameSpace.CHUNK_SIZE):
            world.space_at(cx * GameSpace.CHUNK_SIZE, cy * GameSpace.CHUNK_SIZE)
    caches = [
        space
        for chunk in world.loaded_chunks()
        for row in world.loaded_chunk(*chunk)
        for space in row
        if isinstance(space, GameSpace.Cache)
    ]
    assert len(caches) >= 3
    for cache in caches:
        assert cache.terrain.walkable and cache.level >= 1
        assert min(map(cache.distance, world.towns)) >= GameSpace.CACHE_TOWN_DISTANCE
        others = [c for c in caches if c is not cache]
        assert min(map(cache.distance, others)) > 2 * GameSpace.CHUNK_SIZE

    player = Actors.PlayerCharacter(parent_world=world, name="Finder")
    world.add_actor(player)
    money = player.currency
    [found] = caches[0].run_event(player)
    assert found.currency > 0 and player.currency == money + found.currency
    [again] = caches[0].run_event(player)
    assert again.currency == 0 and "emptied" in again.text


def test_a_minecraft_sized_world_only_generates_where_somebody_goes():
    world = GameSpace.World("Vast", 30_000_000, 30_000_000, seed=1)
    assert len(world.loaded_chunks()) <= (2 * GameSpace.SPAWN_SEARCH_RINGS + 1) ** 2
    # Measured from the spawn, not as a share of the map: a share would make all of this level 1.
    far = Space(
        world.starting_town.x + 10 * GameSpace.DANGER_TILES_PER_LEVEL,
        world.starting_town.y,
    )
    assert world.danger_level(far) == GameSpace.WILDS_MAX_LEVEL

    player = Actors.PlayerCharacter(parent_world=world, name="Explorer")
    world.add_actor(player)
    before = len(world.loaded_chunks())
    for _ in range(GameSpace.CHUNK_SIZE + 1):
        player.attempt_move(DIRECTION_VECTORS["e"])
    assert len(world.loaded_chunks()) > before


def test_generating_a_chunk_leaves_the_game_dice_alone():
    """Otherwise who explores first would change every fight after it."""
    world = GameSpace.World("Dice", 1000, 1000, seed=5)
    state = random.getstate()
    world.space_at(999, 999)
    assert random.getstate() == state


def test_killing_an_npc_pays_out_its_money_once(adapter):
    enemy = Actors.NPC(None, 1, "Mook")
    enemy.currency = 40
    event = Events.CombatEvent(1.0, "<test>", [enemy])
    character = adapter.get_player(1)
    character.equip(Weapons.Hammer())
    purse = character.currency

    responses = list(event.run(character))
    assert character.currency == purse + 40
    assert enemy.currency == 0  # the corpse is empty now
    assert any("$40" in response.text for response in responses)


def test_a_generated_npc_is_worth_more_at_a_higher_level():
    """Averaged: the draw is normal, so a single pair can invert."""
    low = [Actors.NPC.generate(1).currency for _ in range(50)]
    high = [Actors.NPC.generate(10).currency for _ in range(50)]
    assert all(money >= 0 for money in low + high)
    assert sum(high) > sum(low)


@pytest.mark.parametrize("level", [0, 1, 2, 10])
def test_a_generated_npc_always_spawns_able_to_fight(level):
    """Wilds levels start at 0, and an NPC with no hit points starts below Aggressive.flee_at."""
    npcs = [Actors.NPC.generate(level) for _ in range(30)]
    assert all(npc.hit_points > 0 for npc in npcs)
    assert all(npc.hit_points == npc.hit_points_max for npc in npcs)
    assert not any(npc.is_dead for npc in npcs)


def test_levelling_raises_the_ceiling_and_hands_over_the_difference():
    character = Actors.PlayerCharacter(parent_world=None, name="Tester")
    character.take_damage(10)
    hurt = character.hit_points
    ceiling = character.hit_points_max

    assert character.gain_experience(Actors.EXPERIENCE_PER_LEVEL) == 1
    assert character.level == 2
    assert character.hit_points_max == ceiling + Actors.HIT_POINTS_PER_PLAYER_LEVEL
    assert character.hit_points == hurt + Actors.HIT_POINTS_PER_PLAYER_LEVEL


def test_experience_below_the_next_level_changes_nothing_but_the_tally():
    character = Actors.PlayerCharacter(parent_world=None, name="Tester")
    ceiling = character.hit_points_max

    assert character.gain_experience(Actors.EXPERIENCE_PER_LEVEL - 1) == 0
    assert character.level == 1
    assert character.hit_points_max == ceiling
    assert character.experience_to_next_level == 1


def test_changing_class_keeps_the_levels_you_earned():
    """Recruiting in a town resets hit points from the class base, which used to be the whole story."""
    character = Actors.PlayerCharacter(parent_world=None, name="Tester")
    character.gain_experience(2 * Actors.EXPERIENCE_PER_LEVEL)
    character.player_class = Actors.Soldier()

    assert character.level == 3
    assert (
        character.hit_points_max
        == Actors.Soldier().hit_points_max_base + 2 * Actors.HIT_POINTS_PER_PLAYER_LEVEL
    )


def test_a_kill_pays_experience_and_announces_a_level(adapter):
    player = adapter.get_player(1)
    player.equip(Weapons.Hammer())
    mook = Actors.NPC(None, 2 * Actors.EXPERIENCE_PER_LEVEL, "Mook")
    adapter.world.add_actor(mook, player.location)
    mook.take_damage(mook.hit_points_max)  # the hammer would take a while

    response = GameSpace.PlayerActionResponse(source=player)
    phrase = player.loot(mook, response)
    assert player.experience == Actors.EXPERIENCE_PER_LEVEL
    assert player.level == 2
    assert "XP" in phrase and "level 2" in phrase


def test_a_generated_npc_is_tougher_at_a_higher_level():
    """Averaged, and on consecutive levels: the old curve floored 1 and 2 to the same value."""
    weak = sum(Actors.NPC.generate(1).hit_points for _ in range(50))
    strong = sum(Actors.NPC.generate(2).hit_points for _ in range(50))
    assert strong > weak


def _encounter(adapter, npc_hit_points=25, currency=60):
    """Park a stranger on the player, the way stepping into the wilds does."""
    player = adapter.get_player(1)
    npc = Actors.NPC(adapter.world, npc_hit_points, "Stranger")
    npc.currency = currency
    event = Events.EncounterEvent(1.0, "<test>", npc)
    list(event.run(player))
    return player, npc, event


def test_an_encounter_waits_for_the_player_to_decide(adapter):
    player, _, event = _encounter(adapter)
    assert player.pending_event is event


def test_walking_on_is_how_you_ignore_a_stranger(adapter):
    player, _, _ = _encounter(adapter)
    player.attempt_move(DIRECTION_VECTORS["n"])
    assert player.pending_event is None


def test_talking_to_a_stranger_gets_you_directions(adapter):
    player, _, event = _encounter(adapter)
    (response,) = event.resolve(player, "talk")

    nearest = min(
        (town for town in adapter.world.towns if town != player.location),
        key=player.location.distance,
    )
    assert nearest.name in response.text
    assert player.pending_event is None  # one encounter, one outcome


def test_ignoring_a_stranger_costs_nothing(adapter):
    player, npc, event = _encounter(adapter)
    purse, health = player.currency, player.hit_points

    (response,) = event.resolve(player, "ignore")
    assert response.is_successful
    assert (player.currency, player.hit_points) == (purse, health)
    assert npc.currency == 60  # they keep what they had


def test_robbing_a_stranger_who_loses_takes_their_money(adapter, monkeypatch):
    player, npc, event = _encounter(adapter)
    purse = player.currency
    monkeypatch.setattr(Events.random, "random", lambda: 0.0)  # always beats the odds

    (response,) = event.resolve(player, "rob")
    assert response.is_successful
    assert player.currency == purse + 60
    assert npc.currency == 0
    assert "$60" in response.text


def test_robbing_a_stranger_who_wins_hurts(adapter, monkeypatch):
    player, npc, event = _encounter(adapter, npc_hit_points=100, currency=60)
    purse, health = player.currency, player.hit_points
    monkeypatch.setattr(Events.random, "random", lambda: 1.0)  # never beats the odds

    (response,) = event.resolve(player, "rob")
    assert response.failed
    assert player.currency == purse
    assert npc.currency == 60
    assert player.hit_points == health - 20  # a fifth of what the stranger can take


def test_an_encounter_refuses_a_choice_it_does_not_offer(adapter):
    player, _, event = _encounter(adapter)
    with pytest.raises(ValueError):
        event.resolve(player, "befriend")
    assert player.pending_event is event  # still waiting


def test_choosing_with_nobody_waiting_raises(adapter):
    player = adapter.get_player(1)
    with pytest.raises(NoEncounterException):
        adapter.resolve_encounter(player, "talk")


def test_a_generated_merchant_carries_a_handful_of_goods_at_a_markup():
    merchant = Events.MerchantEvent.generate(3)
    assert 0 < len(merchant.store.inventory) <= Events.MerchantEvent.MAX_STOCK
    assert merchant.store.price_ratio == Events.MerchantEvent.MARKUP

    item = merchant.store.inventory[0]
    assert merchant.store.get_price(item) > Store([item]).get_price(item)  # town price


def test_buying_from_a_trader_on_the_road(adapter):
    player = adapter.get_player(1)
    hammer = Weapons.Hammer()
    store = Store([hammer])
    store.price_ratio = Events.MerchantEvent.MARKUP
    list(Events.MerchantEvent(1.0, "<test>", store).run(player))
    player.currency = 10_000

    assert adapter.merchant_store(player) is store
    assert store.sell_item(0, player)
    assert hammer in player.inventory
    assert player.currency == 10_000 - int(
        hammer.base_value * Events.MerchantEvent.MARKUP
    )
    assert not store.inventory  # the blanket is bare now


def test_walking_on_ends_the_trade(adapter):
    player = adapter.get_player(1)
    list(Events.MerchantEvent(1.0, "<test>", Store([Armor.Helmet()])).run(player))

    player.attempt_move(DIRECTION_VECTORS["n"])
    with pytest.raises(NoMerchantException):
        adapter.merchant_store(player)


def test_trading_with_nobody_there_raises(adapter):
    with pytest.raises(NoMerchantException):
        adapter.merchant_store(adapter.get_player(1))


def test_a_stranger_is_not_a_trader_and_a_trader_is_not_a_stranger(adapter):
    """Both park on the same slot, so each command has to check what is actually waiting."""
    player = adapter.get_player(1)
    list(Events.MerchantEvent(1.0, "<test>", Store()).run(player))
    with pytest.raises(NoEncounterException):
        adapter.resolve_encounter(player, "talk")

    list(
        Events.EncounterEvent(1.0, "<test>", Actors.NPC(None, 5, "Stranger")).run(
            player
        )
    )
    with pytest.raises(NoMerchantException):
        adapter.merchant_store(player)


def test_combat_without_a_weapon_reports_the_problem_instead_of_looping():
    enemy = Actors.NPC(None, 5, "Mook")
    event = Events.CombatEvent(1.0, "<test>", [enemy])
    character = Actors.PlayerCharacter(parent_world=None, name="Tester")
    assert character.has_weapon_equipped
    assert character.weapon is not None
    character.unequip(character.weapon)

    responses = list(event.run(character))
    assert not enemy.is_dead
    assert any(
        response.failed and "no weapon" in response.text for response in responses
    )


def _emptied(weapon):
    while not weapon.is_empty:
        weapon.on_damage()
    return weapon


def test_an_empty_gun_reloads_from_the_pack_mid_fight(adapter):
    enemy = Actors.NPC(None, 5, "Mook")
    character = adapter.get_player(1)
    revolver = _emptied(Weapons.WeblyRevolver())
    character.equip(revolver)
    box = Weapons.Ammo9mm()
    character.inventory.append(box)

    list(Events.CombatEvent(1.0, "<test>", [enemy]).run(character))
    assert enemy.is_dead
    assert box.quantity < Weapons.Ammo9mm().quantity  # the rounds came out of the box


def test_an_empty_gun_with_nothing_to_load_fights_on_with_fists(adapter):
    enemy = Actors.NPC(None, 2, "Mook")  # one punch, before it can think of running
    character = adapter.get_player(1)
    revolver = _emptied(Weapons.WeblyRevolver())
    character.equip(revolver)

    responses = list(Events.CombatEvent(1.0, "<test>", [enemy]).run(character))
    assert enemy.is_dead
    assert revolver.current_capacity == 0  # never fired past empty
    assert any("Fists it is" in response.text for response in responses)


def test_a_weapon_that_does_no_damage_still_ends_the_fight(adapter):
    enemy = Actors.NPC(None, 5, "Mook")
    character = adapter.get_player(1)
    feather = Weapons.Hammer()
    feather._base_damage = 0
    character.equip(feather)

    responses = list(Events.CombatEvent(1.0, "<test>", [enemy]).run(character))
    assert enemy.is_dead or isinstance(enemy.brain.current_state, Behavior.Fleeing)
    assert responses[-1].is_successful


def test_every_gun_has_ammo_a_store_can_stock():
    boxes = {
        cls().caliber
        for cls in Items.FullyImplemented.__subclasses__()
        if issubclass(cls, Items.Ammo)
    }
    guns = [
        cls()
        for cls in Items.FullyImplemented.__subclasses__()
        if issubclass(cls, Weapons.ProjectileWeapon)
    ]
    assert guns
    assert {gun.caliber for gun in guns} <= boxes


def test_a_part_used_ammo_box_sells_for_what_is_left_in_it():
    box = Weapons.Ammo9mm()  # 50 rounds
    full = Store().get_price(box)
    assert box.take(25) == 25
    assert Store().get_price(box) == full // 2
    assert box.take(999) == 25  # only what's left comes out
    assert box.quantity == 0


def test_spaces_that_are_equal_hash_equal():
    grass, water = Space(3, 4, GrassTerrain()), Space(3, 4, WaterTerrain())
    assert grass == water == (3, 4)
    assert hash(grass) == hash(water) == hash((3, 4))
    assert len({grass, water}) == 1


def test_closest_returns_as_many_spaces_as_asked():
    here = Space(0, 0)
    spaces = [Space(5, 5), Space(1, 1), Space(3, 3)]
    assert here.closest(spaces) == [Space(1, 1)]
    assert here.closest(spaces, size=2) == [Space(1, 1), Space(3, 3)]


def test_a_badly_hurt_npc_flees_instead_of_dying_and_keeps_its_kit():
    enemy = Actors.NPC(None, 100, "Coward")
    enemy.hit_points = 30  # one Hammer hit puts it under Aggressive.flee_at
    enemy.inventory.append(Armor.Helmet())
    event = Events.CombatEvent(1.0, "<test>", [enemy])
    character = Actors.PlayerCharacter(parent_world=None, name="Tester")
    character.equip(Weapons.Hammer())

    responses = list(event.run(character))
    assert isinstance(enemy.brain.current_state, Behavior.Fleeing)
    assert any("flees" in response.text for response in responses)
    assert not any(isinstance(item, Armor.Helmet) for item in character.inventory)


def test_a_dead_npc_despawns_and_drops_its_inventory():
    enemy = Actors.NPC(None, 3, "Mook")
    enemy.location = Space(2, 2)
    helmet = Armor.Helmet()
    enemy.inventory.append(helmet)

    enemy.take_damage(3)
    assert enemy.is_dead
    assert enemy.location is None
    assert enemy.on_death() == [helmet]


# --- WorldAdapter contract ----------------------------------------------------------------------------


def test_registration_strips_characters_that_would_break_discord_markup(adapter):
    adapter.register_player(2, "<b>Ev/il\\Name</b>")
    assert adapter.get_player(2).name == "bEvilNameb"


def test_registering_the_same_member_twice_raises(adapter):
    with pytest.raises(AlreadyRegisteredException):
        adapter.register_player(1, "Impostor")


def test_asking_for_a_stranger_raises(adapter):
    assert not adapter.is_registered(999)
    with pytest.raises(NotRegisteredException):
        adapter.get_player(999)


def test_new_players_start_in_the_starting_town(adapter):
    player = adapter.get_player(1)
    assert player.location == adapter.world.starting_town
    assert adapter.is_town(player.location)
    assert not adapter.is_wilds(player.location)


def test_walking_into_impassable_terrain_raises(adapter):
    player = adapter.get_player(1)
    north = player.location + DIRECTION_VECTORS["n"]
    adapter.world.space_at(north.x, north.y).terrain = NullTerrain()
    with pytest.raises(InvalidSpaceException):
        adapter.move_player(player, DIRECTION_VECTORS["n"])
    assert player.location == adapter.world.starting_town  # didn't budge


def test_attacking_bare_handed_raises(adapter):
    player = adapter.get_player(1)
    player.unequip(player.weapon)
    with pytest.raises(NoWeaponEquippedException):
        adapter.attack(player, None)


def _beside(world, steps=1):
    """An open square with open ground `steps` north of it, neither of them a town."""
    return next(
        here
        for here in (world.space_at(x, y) for y in range(steps, world.height) for x in range(world.width))
        if all(
            world.is_space_valid(s) and not isinstance(s, GameSpace.Town)
            for s in (here, world.space_at(here.x, here.y - steps))
        )
    )


def test_a_melee_swing_reaches_the_square_beside_you(adapter):
    """/attack always takes a direction, and with a melee weapon that used to be refused outright."""
    player = adapter.get_player(1)
    player.equip(Weapons.Hammer())
    player.location = _beside(adapter.world)
    mook = Actors.NPC(None, 100, "Mook")
    adapter.world.add_actor(mook, adapter.world.space_at(player.location.x, player.location.y - 1))

    response = adapter.attack(player, DIRECTION_VECTORS["n"])
    assert response.target is mook
    assert mook.hit_points == mook.hit_points_max - response.damage > 0  # full weight, no falloff


def test_a_melee_swing_does_not_reach_two_squares(adapter):
    player = adapter.get_player(1)
    player.equip(Weapons.Hammer())
    player.location = _beside(adapter.world, steps=2)
    mook = Actors.NPC(None, 100, "Mook")
    adapter.world.add_actor(mook, adapter.world.space_at(player.location.x, player.location.y - 2))

    with pytest.raises(CombatException, match="within reach"):
        adapter.attack(player, DIRECTION_VECTORS["n"])
    assert mook.hit_points == mook.hit_points_max


def test_a_melee_swing_hits_your_own_square_first(adapter):
    player = adapter.get_player(1)
    player.equip(Weapons.Hammer())
    player.location = _beside(adapter.world)
    here, there = Actors.NPC(None, 100, "Here"), Actors.NPC(None, 100, "There")
    adapter.world.add_actor(here, player.location)
    adapter.world.add_actor(there, adapter.world.space_at(player.location.x, player.location.y - 1))

    assert adapter.attack(player, DIRECTION_VECTORS["n"]).target is here


def test_attacking_an_empty_square_raises(adapter):
    player = adapter.get_player(1)
    with pytest.raises(CombatException):
        adapter.attack(player, None)


def test_pvp_hits_someone_standing_on_the_same_square(adapter):
    adapter.register_player(2, "Victim")
    attacker, victim = adapter.get_player(1), adapter.get_player(2)
    attacker.equip(Weapons.Hammer())

    response = adapter.attack(attacker, None)
    assert response.is_successful
    assert response.target is victim
    assert victim.hit_points < victim.hit_points_max


def test_a_space_is_not_equal_to_things_that_are_not_coordinates():
    """A despawned actor's location is None, and combat compares locations every swing."""
    space = Space(1, 2, GrassTerrain())
    assert space == (1, 2)
    assert space == Space(1, 2, SandTerrain())  # the same square, whatever is on it
    assert space != None  # noqa: E711 - the point is __eq__, not identity
    assert space != "over there"


def test_attacking_hits_an_npc_standing_on_the_same_square(adapter):
    player = adapter.get_player(1)
    player.equip(Weapons.Hammer())
    mook = Actors.NPC(None, 100, "Mook")
    adapter.world.add_actor(mook, player.location)

    response = adapter.attack(player, None)
    assert response.target is mook
    assert mook.hit_points < mook.hit_points_max


def test_killing_an_npc_with_a_swing_loots_it(adapter):
    player = adapter.get_player(1)
    player.equip(Weapons.Hammer())
    mook = Actors.NPC(None, 1, "Mook")
    mook.inventory.append(Armor.Helmet())
    mook.currency = 40
    adapter.world.add_actor(mook, player.location)
    purse = player.currency

    response = adapter.attack(player, None)
    assert mook.is_dead
    assert player.currency == purse + 40
    assert any(isinstance(item, Armor.Helmet) for item in player.inventory)
    assert "$40" in response.text
    assert mook.currency == 0 and not mook.inventory  # the body is bare now


def test_a_dead_npc_cannot_be_attacked_again(adapter):
    """on_death despawns the NPC before World.tick prunes it: it must stop being a target immediately."""
    player = adapter.get_player(1)
    player.equip(Weapons.Hammer())
    mook = Actors.NPC(None, 1, "Mook")
    adapter.world.add_actor(mook, player.location)
    adapter.attack(player, None)

    assert mook in adapter.world.npcs  # still on the roster until the next tick
    with pytest.raises(CombatException):
        adapter.attack(player, None)


def test_an_empty_gun_cannot_shoot_so_you_swing_fists(adapter):
    """Nothing to load and someone on your square: you still get to hit back, just not with the gun."""
    adapter.register_player(2, "Victim")
    attacker, victim = adapter.get_player(1), adapter.get_player(2)
    musket = Weapons.Jezail()
    attacker.equip(musket)
    musket.fire()
    assert musket.is_empty

    response = adapter.attack(attacker, None)
    assert response.target is victim
    assert response.damage == Weapons.Fist().damage
    assert "fists" in response.text
    assert musket.current_capacity == 0  # never fired past empty


def test_dying_sends_you_back_to_the_starting_town(adapter):
    player = adapter.get_player(1)
    elsewhere = adapter.world.space_at(0, 0)
    player.location = elsewhere

    player.take_damage(player.hit_points_max)
    assert player.location == adapter.world.starting_town


def test_dying_on_a_raid_loses_everything_you_carried(adapter):
    player = adapter.get_player(1)
    player.location = adapter.world.wilds[0]
    player.currency = 400
    rifle, helmet = Weapons.Jezail(), Armor.Helmet()
    player.equip(rifle)
    player.inventory.append(helmet)

    player.take_damage(player.hit_points_max)
    assert (player.currency, list(player.inventory)) == (0, [])
    assert isinstance(player.weapon, Weapons.Fist)  # back to bare hands, not unarmed
    assert GameSpace.death_toll_text(player) == (
        f" You lost $400, {helmet}, {rifle}, left where you fell at {adapter.world.wilds[0]}."
    )


def _die_beside_town(world, player):
    """Kill `player` on the quiet square beside the starting town; returns the way back to that square."""
    d = _quiet_step_out_of_town(world)
    player.attempt_move(d)
    player.take_damage(player.hit_points_max)
    return d


def test_a_raid_death_leaves_your_things_for_a_corpse_run(adapter):
    player = adapter.get_player(1)
    helmet = Armor.Helmet()
    player.inventory.append(helmet)
    player.equip(helmet)
    player.currency = 400
    d = _die_beside_town(adapter.world, player)
    assert (player.currency, list(player.inventory)) == (0, [])

    results = adapter.move_player(player, d)
    assert "your own things" in results[-1].text
    assert (player.currency, list(player.inventory)) == (400, [helmet])
    assert not helmet.is_equipped  # picked up off the ground, not worn
    assert player.location.remains is None  # picked clean, nothing to take twice


def test_anyone_can_loot_remains_but_not_once_they_rot(adapter):
    adapter.register_player(2, "Scavenger")
    victim, scavenger = adapter.get_player(1), adapter.get_player(2)
    victim.currency = 400
    d = _die_beside_town(adapter.world, victim)

    adapter.world.ticks += GameSpace.REMAINS_TICKS + 1
    adapter.move_player(scavenger, d)
    assert scavenger.currency == 1000  # what it started with: the pile had rotted

    victim.currency = 50
    _die_beside_town(adapter.world, victim)
    adapter.move_player(scavenger, (-d[0], -d[1]))
    results = adapter.move_player(scavenger, d)
    assert f"{victim.name}'s things" in results[-1].text and scavenger.currency == 1050


def test_dying_in_town_costs_nothing(adapter):
    player = adapter.get_player(1)
    player.currency = 400
    player.take_damage(player.hit_points_max)
    assert player.currency == 400
    assert GameSpace.death_toll_text(player) == ""


def _quiet_step_out_of_town(world):
    """A direction from the starting town onto open ground that isn't a town and has no event waiting."""
    town = world.starting_town
    for d in DIRECTION_VECTORS.values():
        s = world.space_at(town.x + d[0], town.y + d[1])
        if world.is_space_valid(s) and type(s) is GameSpace.Space:
            return d
    pytest.skip("starting town has no plain ground next to it")


def test_stepping_back_into_town_extracts_and_reports_the_haul(adapter):
    player = adapter.get_player(1)
    helmet, carried = Armor.Helmet(), Armor.Helmet()
    player.inventory.append(carried)
    d = _quiet_step_out_of_town(adapter.world)

    adapter.move_player(player, d)
    assert player.raid_start is not None
    player.inventory.append(helmet)
    player.currency += 250
    player.gain_experience(40)

    results = adapter.move_player(player, (-d[0], -d[1]))
    assert player.location == adapter.world.starting_town
    assert results[-1].text.endswith(f"you brought home: {helmet}, $250, 40 XP.")
    assert player.raid_start is None


def test_a_raid_death_is_not_an_extraction(adapter):
    player = adapter.get_player(1)
    adapter.move_player(player, _quiet_step_out_of_town(adapter.world))
    player.take_damage(player.hit_points_max)
    assert player.raid_start is None  # back in town, but nothing was brought home


def test_the_pouch_survives_a_raid_death(adapter):
    player = adapter.get_player(1)
    rifle, helmet = Weapons.Jezail(), Armor.Helmet()
    player.inventory += [rifle, helmet]
    player.equip(rifle)

    assert player.pouch_swap(0) == f"{rifle} into your pouch"
    assert not rifle.is_equipped and list(player.inventory) == [helmet]
    player.location = adapter.world.wilds[0]
    player.take_damage(player.hit_points_max)
    assert player.pouch is rifle and list(player.inventory) == []
    assert str(rifle) not in GameSpace.death_toll_text(player)

    player.inventory.append(helmet)
    assert player.pouch_swap(0) == f"{helmet} into your pouch, {rifle} back into your pack"
    assert player.pouch_swap() == f"{helmet} back into your pack"
    with pytest.raises(ValueError):
        player.pouch_swap(5)


def test_a_hideout_is_bought_with_carried_then_stashed_money_and_pays_into_the_stash(adapter):
    player = adapter.get_player(1)
    player.currency, player.stash_currency = 400, Actors.HIDEOUT_COST - 400
    player.build_hideout()
    assert (player.hideout_level, player.currency, player.stash_currency) == (1, 0, 0)
    with pytest.raises(ValueError):
        player.build_hideout()
    assert player.hideout_level == 1

    player.location = adapter.world.wilds[0]  # out on a raid, or not playing at all: it pays either way
    for _ in range(Actors.HIDEOUT_PAY_TICKS):
        adapter.world.tick()
    assert player.stash_currency == Actors.HIDEOUT_INCOME


def test_hideout_levels_cost_more_each_time_and_some_cost_salvage(adapter):
    player = adapter.get_player(1)
    player.currency = 10**6
    prices = []
    for _ in range(Actors.HIDEOUT_SALVAGE_EVERY - 1):
        prices.append(player.hideout_price[0])
        player.build_hideout()
    assert prices == [1000, 1150, 1322, 1520]  # HIDEOUT_COST * 1.15 ** level

    assert player.hideout_price == (0, 1)  # the fifth is bartered, and money won't do
    with pytest.raises(ValueError, match="salvage"):
        player.build_hideout()
    player.stash.append(Items.Salvage())
    money = player.currency
    player.build_hideout()
    assert (player.hideout_level, player.currency, list(player.stash)) == (5, money, [])
    assert player.hideout_price == (int(1000 * 1.15**5), 0)


def test_a_cache_always_holds_salvage(adapter):
    player = adapter.get_player(1)
    cache = GameSpace.Cache(0, 0)
    cache.run_event(player)
    assert any(isinstance(item, Items.Salvage) for item in player.inventory)


def test_the_stash_banks_items_and_money_and_death_leaves_it_alone(adapter):
    player = adapter.get_player(1)
    helmet = Armor.Helmet()
    player.inventory.append(helmet)
    player.currency = 400

    assert player.stash_put(0, 300) == f"{helmet}, $300"
    assert (list(player.inventory), player.currency) == ([], 100)
    assert (list(player.stash), player.stash_currency) == ([helmet], 300)

    player.location = adapter.world.wilds[0]
    player.take_damage(player.hit_points_max)
    assert (list(player.stash), player.stash_currency, player.currency) == ([helmet], 300, 0)

    assert player.stash_take(money=50) == "$50"
    assert player.stash_take(0) == str(helmet)
    assert (list(player.inventory), player.stash_currency) == ([helmet], 250)


@pytest.mark.parametrize("index, money", [(0, 0), (None, 401), (None, -1)])
def test_a_bad_stash_move_moves_nothing(adapter, index, money):
    player = adapter.get_player(1)
    player.currency = 400
    with pytest.raises(ValueError):
        player.stash_put(index, money)
    assert (player.currency, player.stash_currency, list(player.stash)) == (400, 0, [])


def test_dying_broke_costs_nothing_and_says_nothing(adapter):
    """Fists don't count as kit: there is no toll worth narrating."""
    player = adapter.get_player(1)
    player.location = adapter.world.wilds[0]
    player.currency = 0

    player.take_damage(player.hit_points_max)
    assert player.currency == 0
    assert GameSpace.death_toll_text(player) == ""


def test_you_come_back_from_death_alive_and_can_die_again(adapter):
    """Dying used to leave you dead at 0 HP for good: every later fight was an instant, free loss."""
    player = adapter.get_player(1)
    player.location = adapter.world.wilds[0]

    player.take_damage(player.hit_points_max)
    assert not player.is_dead
    assert player.hit_points == player.hit_points_max

    player.take_damage(player.hit_points_max)
    assert player.deaths == 2


def test_raiders_leave_players_in_town_alone(adapter):
    player = adapter.get_player(1)
    town = adapter.world.starting_town
    raider = Actors.Raider(adapter.world, 50, "Camper")
    adapter.world.add_actor(raider, town)

    adapter.world.tick()
    assert player.hit_points == player.hit_points_max


def test_the_map_holds_exactly_width_times_height_spaces(adapter):
    assert len(list(adapter.iter_spaces())) == adapter.width * adapter.height
    assert [(idx, p.name) for idx, p in adapter.iter_registered()] == [(1, "Tester")]


def test_a_player_sees_their_own_neighbourhood(adapter):
    player = adapter.get_player(1)
    nearby = adapter.get_nearby_players(player)
    assert player in nearby

    edge = adapter.world.get_adjacent_spaces(adapter.world.space_at(0, 0), sq_range=2)
    assert all(
        0 <= space.x < adapter.width and 0 <= space.y < adapter.height for space in edge
    )
    assert len(edge) == 9  # a 5x5 window clipped to the top-left corner


def test_screenshots_degrade_gracefully_without_a_renderer(adapter):
    assert adapter.get_player_screenshot(adapter.get_player(1)) == "<No Renderer>"


# --- World tick: NPCs act on real time, not on player input ------------------------------------


def test_ticking_spawns_npcs_and_moves_them_without_the_player(adapter):
    """Without the player's input, that is: they only move where a player is near enough to see it."""
    world = adapter.world
    assert not world.npcs

    world.tick()
    assert len(world.npcs) == 1
    npc = world.npcs[0]
    assert npc.parent_world is world
    assert world.is_space_valid(npc.location)

    # Somewhere with room to walk, so "it never moved" means the tick is broken, not that it's boxed in
    npc.location = next(
        space
        for space in adapter.iter_spaces()
        if all(
            world.is_space_valid(neighbor)
            for neighbor in world.get_adjacent_spaces(space)
        )
    )
    start = npc.location
    adapter.get_player(1).location = world.space_at(start.x + 1, start.y)  # watching, not playing
    seen = {start}
    for _ in range(50):
        world.tick()
        seen.add(npc.location)
        assert world.is_space_valid(npc.location)
    assert len(seen) > 1


def test_a_tick_lets_an_npc_hit_a_player_sharing_its_space(adapter):
    world = adapter.world
    player = adapter.get_player(1)
    player.location = world.wilds[0]  # towns are safe
    npc = Actors.Raider(world, 50, "Mugger")
    world.add_actor(npc, player.location)

    world.tick()
    assert player.hit_points < player.hit_points_max


def test_a_tick_that_kills_says_so_and_sends_you_home(adapter):
    world = adapter.world
    player = adapter.get_player(1)
    player.location = world.wilds[0]
    player.hit_points = 1
    world.add_actor(Actors.Raider(world, 50, "Mugger"), player.location)

    [event] = [e for e in world.tick() if e.target is player]
    assert "black out" in event.text
    assert player.location == world.starting_town and not player.is_dead


def test_dead_npcs_are_dropped_on_the_next_tick(adapter):
    world = adapter.world
    npc = Actors.Raider(world, 1, "Doomed")
    world.add_actor(npc, world.starting_town)
    npc.take_damage(10)

    world.tick()
    assert npc not in world.npcs


@pytest.mark.parametrize("beyond, moves", [(0, True), (1, False)], ids=["in range", "just out of range"])
def test_only_npcs_near_a_player_take_a_turn(beyond, moves):
    """Within a chunk of a player, raiders wander. Further out, the world holds still until somebody comes."""
    world = GameSpace.World("Wakeland", 128, 128, seed=WORLD_SEED)
    for x in range(0, world.width, GameSpace.CHUNK_SIZE):
        for y in range(0, world.height, GameSpace.CHUNK_SIZE):
            world.space_at(x, y)
    reach = GameSpace.NPC_AWAKE_RADIUS + beyond
    # Walkable all round, so holding still means it wasn't simulated, not that it was boxed in
    start = next(
        world.space_at(x, y)
        for y in range(1, world.height - 1)
        for x in range(1, world.width - reach)
        if all(world.is_space_valid(n) for n in world.get_adjacent_spaces(world.space_at(x, y)))
    )
    npc = Actors.Raider(world, 50, "Lurker")
    world.add_actor(npc, start)
    player = Actors.PlayerCharacter(parent_world=world, name="Watcher")
    world.add_actor(player)
    player.location = world.space_at(start.x + reach, start.y)

    seen = {npc.location}
    for _ in range(50):
        world.tick()
        seen.add(npc.location)
    assert (len(seen) > 1) is moves


def test_raiders_top_out_at_a_couple_a_chunk():
    """A player wakes everything within a chunk of them; at 9 raiders a chunk that was dozens at once."""
    world = GameSpace.World("Crowdland", 128, 128, seed=WORLD_SEED)
    for x in range(0, world.width, GameSpace.CHUNK_SIZE):
        for y in range(0, world.height, GameSpace.CHUNK_SIZE):
            world.space_at(x, y)
    for _ in range(300):  # one spawns a tick until the cap; well past it at the old density
        world.tick()
    chunks = len(world.loaded_chunks())
    assert 0 < len(world.npcs) <= 3 * chunks


def _open_ground(world, width, height=1):
    """The top-left of a width x height block of walkable squares, none of them a town."""
    return next(
        world.space_at(x, y)
        for y in range(world.height - height)
        for x in range(world.width - width)
        if all(
            world.is_space_valid(s) and not isinstance(s, GameSpace.Town)
            for s in (world.space_at(x + i, y + j) for i in range(width) for j in range(height))
        )
    )


@pytest.fixture
def lone_raider(monkeypatch):
    """No tick spawns: the raider a test places is the only one about."""
    monkeypatch.setattr(GameSpace, "WILDS_PER_RAIDER", 10**9)


def test_a_raider_that_spots_you_closes_in_and_warns_you_once(adapter, lone_raider):
    world = adapter.world
    player = adapter.get_player(1)
    sight = GameSpace.NPC_SIGHT
    corner = _open_ground(world, sight + 1)
    player.location = corner
    npc = Actors.Raider(world, 50, "Stalker")
    world.add_actor(npc, world.space_at(corner.x + sight, corner.y))

    [warning] = [e for e in world.tick() if e.target is player]
    assert warning.text == f"Stalker has spotted you, {sight} squares to the east."
    news = []
    for gap in range(sight - 1, -1, -1):  # a square a tick, and no second warning
        assert npc.location.x - player.location.x == gap
        news = [e.text for e in world.tick() if e.target is player]
        assert not any("spotted" in text for text in news)
    assert news == ["Stalker hits you for 2 damage."]  # caught you standing still


def test_a_raider_does_not_see_past_its_sight(adapter, lone_raider):
    world = adapter.world
    player = adapter.get_player(1)
    corner = _open_ground(world, GameSpace.NPC_SIGHT + 2)
    player.location = corner
    npc = Actors.Raider(world, 50, "Shortsighted")
    world.add_actor(npc, world.space_at(corner.x + GameSpace.NPC_SIGHT + 1, corner.y))

    assert [e for e in world.tick() if e.target is player] == []
    assert npc.quarry is None


def test_raiders_leave_you_alone_in_town(adapter, lone_raider):
    world = adapter.world
    player = adapter.get_player(1)
    town = player.location = world.starting_town
    beside = next(
        s
        for s in world.get_adjacent_spaces(town, GameSpace.NPC_SIGHT)
        if world.is_space_valid(s) and not isinstance(s, GameSpace.Town)
    )
    npc = Actors.Raider(world, 50, "Loiterer")
    world.add_actor(npc, beside)

    assert [e for e in world.tick() if e.target is player] == []
    assert npc.quarry is None


def test_a_wounded_raider_runs_from_you(adapter, lone_raider):
    """It used to stand there and take it. Now its kit is something you chase down."""
    world = adapter.world
    player = adapter.get_player(1)
    corner = _open_ground(world, 5, 5)
    player.location = world.space_at(corner.x + 2, corner.y + 2)  # open ground two squares every way
    npc = Actors.Raider(world, 50, "Coward")
    world.add_actor(npc, player.location)  # face to face
    npc.brain.change_state(Behavior.Fleeing())
    hit_points = player.hit_points

    gaps = []
    for _ in range(2):
        assert [e for e in world.tick() if e.target is player] == []  # no hits, no warnings
        gaps.append(npc.location.distance(player.location))
    assert 0 < gaps[0] < gaps[1]
    assert player.hit_points == hit_points


def test_npcs_never_walk_into_unmade_ground():
    """Only players explore: a raider at the edge of the known map stays on it, so the map stays small."""
    world = GameSpace.World("Edgeland", 256, 256, seed=WORLD_SEED)
    size = GameSpace.CHUNK_SIZE
    cx, cy = next(
        (cx, cy)
        for cx, cy in world.loaded_chunks()
        if (cx + 1) * size < world.width and world.loaded_chunk(cx + 1, cy) is None
    )
    edge = next(
        space
        for space in (world.space_at((cx + 1) * size - 1, y) for y in range(cy * size, (cy + 1) * size))
        if space.terrain.walkable
    )
    npc = Actors.Raider(world, 50, "Scout")
    world.add_actor(npc, edge)
    chunks = len(world.loaded_chunks())

    assert npc.attempt_move((1, 0))[0].failed
    assert npc.location is edge and world.loaded_chunk(cx + 1, cy) is None

    watcher = Actors.PlayerCharacter(parent_world=world, name="Watcher")
    world.add_actor(watcher)
    watcher.location = world.space_at(edge.x - 1, edge.y)  # beside it, so it's awake
    for _ in range(200):
        world.tick()
    assert len(world.loaded_chunks()) == chunks


# --- Names: the word lists are data, so the loader is what needs guarding ------------------------


def test_every_name_list_in_the_json_builds_a_usable_generator():
    from Discordia.GameLogic import StringGenerator

    assert set(StringGenerator.GENERATORS) >= {
        "town",
        "wilds",
        "character_male",
        "character_female",
    }
    for key, generator in StringGenerator.GENERATORS.items():
        assert (
            generator.roots and generator.postfixes
        ), f"{key} has nothing to build from"
        assert generator.generate_name().strip(), f"{key} generated an empty name"


def test_a_broken_names_file_fails_at_load_not_mid_game(tmp_path):
    from Discordia.GameLogic import StringGenerator

    broken = tmp_path / "names.json"
    broken.write_text('{"town": {"prefixes": [], "roots": []}}', encoding="utf-8")
    with pytest.raises(TypeError):  # postfixes missing
        StringGenerator.load(broken)


# --- Weapons: the stat blocks are data, so the loader is what needs guarding ---------------------


def test_every_weapon_stat_block_builds_the_weapon_it_names():
    for class_name, stats in Weapons.STATS.items():
        weapon = getattr(Weapons, class_name)()
        assert weapon.name == stats["name"]
        # .damage is behaviour (bursts, pellets, jams); the stat block only sets the base
        assert weapon._base_damage == stats["base_damage"]
        assert weapon.weight_lb == stats.get("weight_lb", 0)


def test_a_misspelled_enum_in_the_stats_fails_at_load(tmp_path):
    bad = tmp_path / "weapons.json"
    bad.write_text('{"AK47": {"caliber": "MM_999"}}', encoding="utf-8")
    with pytest.raises(AttributeError):
        Weapons.load_stats(bad)


def test_every_armor_stat_block_builds_the_armor_it_names():
    for class_name, stats in Armor.STATS.items():
        piece = getattr(Armor, class_name)()
        assert piece.name == stats["name"]
        assert piece.weight_lb == stats["weight_lb"]
        assert piece.coverage == stats["coverage"]
        # armor_count rolls against coverage, so the stat block is checked on the field behind it
        assert piece._armor_count == stats["armor_count"]


# --- Weapon-specific modifiers -------------------------------------------------------------------


def _wielding(weapon, terrain=None):
    """A character holding `weapon` while standing on `terrain`. Modifiers read the player off equip."""
    character = Actors.PlayerCharacter(parent_world=None, name="Tester")
    character.location = Space(1, 1, terrain or GrassTerrain())
    weapon.on_equip(character)
    return weapon


def _ammo_for(weapon, quantity=500):
    actor = Actors.PlayerCharacter(parent_world=None, name="Loader")
    actor.inventory.append(Items.Ammo(caliber=weapon.caliber, quantity=quantity))
    return actor


def test_every_weapon_runs_out_of_damage_without_ever_going_negative():
    """World.attack_() walks outwards until a shot does no damage, so a modifier that never decays hangs it."""
    for class_name in Weapons.STATS:
        for terrain in (MountainTerrain(), WaterTerrain(), GrassTerrain()):
            weapon = _wielding(getattr(Weapons, class_name)(), terrain)
            if not isinstance(weapon, Weapons.RangedWeapon):
                continue
            damages = [weapon.calc_damage(d) for d in range(20)]
            assert min(damages) >= 0, (class_name, damages)
            assert int(damages[-1]) == 0, (class_name, damages)


def test_jezail_and_lebel_want_opposite_ground():
    high, low = MountainTerrain(), GrassTerrain()
    assert _wielding(Weapons.Jezail(), high).calc_damage(1) > _wielding(
        Weapons.Jezail(), low
    ).calc_damage(1)
    assert _wielding(Weapons.Lebel(), low).calc_damage(1) > _wielding(
        Weapons.Lebel(), high
    ).calc_damage(1)


def test_owen_ignores_falloff_in_the_mud():
    wet = _wielding(Weapons.OwenSMG(), WaterTerrain())
    dry = _wielding(Weapons.OwenSMG(), GrassTerrain())
    assert wet.calc_damage(3) == wet.damage
    assert dry.calc_damage(3) < dry.damage


def test_martini_henry_hits_hardest_in_your_face():
    rifle = Weapons.MartiniHenry()
    assert rifle.calc_damage(0) == rifle.damage * 2
    assert rifle.calc_damage(3) < rifle.calc_damage(1)
    assert rifle.calc_damage(9) == 0


def test_mosin_nagant_rewards_distance_up_to_its_range():
    rifle = Weapons.MosinNagant()
    assert rifle.calc_damage(3) > rifle.calc_damage(0)
    assert rifle.calc_damage(rifle.range_) > 0
    assert rifle.calc_damage(rifle.range_ + 1) == 0


def test_belt_fed_fire_ramps_and_a_reload_starts_it_over():
    gun = Weapons.PKM()
    cold = gun.damage
    for _ in range(5):
        gun.on_damage()
    assert gun.damage > cold
    for _ in range(100):
        gun.on_damage()
    assert gun.damage == cold * 2  # the ramp is capped
    gun.reload(_ammo_for(gun))
    assert gun.damage == cold


def test_a_bipod_deploys_itself_on_high_ground():
    on_the_flat = _wielding(Weapons.RPK(), GrassTerrain())
    on_the_rocks = _wielding(Weapons.RPK(), MountainTerrain())
    on_the_flat.calc_damage(1)
    on_the_rocks.calc_damage(1)
    assert on_the_rocks.mounted and not on_the_flat.mounted
    assert on_the_rocks.calc_damage(3) > on_the_flat.calc_damage(3)


def test_mounting_a_machine_gun_steadies_it():
    gun = Weapons.FNMinimi()
    loose = gun.calc_damage(3)
    gun.mounted = True
    assert gun.calc_damage(3) > loose
    gun.mounted = False
    assert gun.calc_damage(3) == loose


def test_ppsh_drum_rips_until_it_is_half_empty():
    smg = Weapons.PPSh41()
    assert smg.burst_size == 3
    while smg.current_capacity > smg.capacity / 2:
        smg.on_damage()
    assert smg.burst_size == 1


def test_the_garand_ping_costs_you_the_shot_after_the_reload():
    rifle = Weapons.M1Garand()
    full_power = rifle.damage
    for _ in range(rifle.capacity):
        rifle.on_damage()
    assert rifle.is_empty
    rifle.reload(_ammo_for(rifle))
    assert rifle.damage == full_power / 2  # they heard the clip go
    rifle.on_damage()
    assert rifle.damage == full_power


def test_a_jammed_sten_still_shoots_and_clears_itself(monkeypatch):
    smg = Weapons.Sten()
    full_power = smg.damage
    monkeypatch.setattr(Weapons.random, "random", lambda: 0.0)  # always jams
    smg.on_damage()
    assert 0 < smg.damage < full_power
    smg.on_damage()
    assert smg.damage == full_power  # cleared, and cannot jam twice running


def test_single_loaders_take_one_round_per_reload():
    rifle = Weapons.Lebel()
    for _ in range(rifle.capacity):
        rifle.on_damage()
    actor = _ammo_for(rifle)
    rifle.reload(actor)
    assert rifle.current_capacity == 1
    rifle.reload(actor)
    assert rifle.current_capacity == 2


def test_a_chambered_rifle_reloads_to_one_over_a_full_magazine():
    rifle = Weapons.LeeEnfield()
    rifle.on_damage()
    rifle.reload(_ammo_for(rifle))
    assert rifle.current_capacity == rifle.capacity + 1


def test_every_generated_town_has_a_named_industry():
    """MilitaryBase is abstract and has no name, but generation used to hand it to towns anyway."""
    industries = {
        GameSpace.Town.generate_town(
            0, 0, GrassTerrain()
        ).industry.name  # raises if abstract
        for _ in range(200)
    }
    assert {"Eastern Military Base", "Western Military Base"} & industries


def test_deaths_and_kills_are_counted_for_the_digest(adapter):
    world = adapter.world
    player = adapter.get_player(1)
    wilds = world.wilds[0]
    player.location = wilds
    player.take_damage(player.hit_points_max)
    assert world.stats.deaths_by_level == {wilds.level: 1}

    mook = Actors.NPC(world, 1, "Mook")
    world.add_actor(mook, player.location)
    player.equip(Weapons.Hammer())
    adapter.attack(player, None)
    assert world.stats.kills == 1
