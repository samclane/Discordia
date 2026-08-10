"""
Unit tests for the parts of the game rules that don't need a rendered world: weapon maths, geometry,
equipment, stores, events, and the adapter's error contract.

test_all.py already drives a full 100x100 world; these stay small and fast on purpose.
"""

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
    bitmask_to_orientation,
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
    NoWeaponEquippedException,
    NotRegisteredException,
    RangedAttackException,
    WorldAdapter,
)

WORLD_SIZE = 40
WORLD_SEED = 0


@pytest.fixture
def adapter() -> WorldAdapter:
    """A small world with one registered player. Fresh per test: the tests below move and maim him."""
    world = GameSpace.World("Test World", WORLD_SIZE, WORLD_SIZE, seed=WORLD_SEED)
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


@pytest.mark.parametrize(
    "bits, expected",
    [
        (0xFF, "center"),
        (0b01011010, "center"),
        (0b01011000, "n"),
        (0b01001010, "e"),
        (0b00011010, "s"),
        (0b01010010, "w"),
        (0, "center"),
    ],
)
def test_bitmask_picks_the_tile_orientation(bits, expected):
    assert bitmask_to_orientation(bits) == expected


def test_orientation_must_be_a_known_direction():
    terrain = GrassTerrain()
    terrain.orientation = "NE"  # case-insensitive
    assert terrain.orientation == "ne"
    with pytest.raises(ValueError):
        terrain.orientation = "up"


def test_water_ignores_orientation_because_it_has_one_tile():
    water = WaterTerrain()
    water.orientation = "n"
    assert water.orientation == "center"


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


def test_sprite_path_follows_name_and_orientation():
    terrain = SandTerrain()
    terrain.orientation = "se"
    assert terrain.sprite_path.name == "sand_se.png"


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

    event = Events.MerchantEvent(0.25, "<test>", {})
    wilds.add_event(event)
    assert wilds.null_event.probability == pytest.approx(0.75)
    assert sum(e.probability for e in wilds.events) == pytest.approx(1.0)


def test_an_event_can_never_be_more_likely_than_whats_left():
    wilds = Wilds(1, 1, "The Nowhere")
    wilds.add_event(Events.MerchantEvent(5.0, "<greedy>", {}))
    assert wilds.null_event.probability == 0
    assert wilds.events[-1].probability == 1.0


def test_a_quiet_wilds_reports_that_nothing_happened():
    """The null event runs empty: callers read 'no responses' as 'nothing to narrate'."""
    wilds = Wilds(1, 1, "The Nowhere")
    character = Actors.PlayerCharacter(parent_world=None, name="Tester")
    assert wilds.run_event(character) == []


def test_combat_ends_with_the_enemies_dead_and_their_kit_looted():
    enemy = Actors.NPC(None, 1, "Mook")
    enemy.inventory.append(Armor.Helmet())
    event = Events.CombatEvent(1.0, "<test>", [enemy])
    character = Actors.PlayerCharacter(parent_world=None, name="Tester")
    character.equip(Weapons.Hammer())

    responses = list(event.run(character))
    assert enemy.is_dead
    assert responses[-1].is_successful
    assert any(isinstance(item, Armor.Helmet) for item in character.inventory)


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
    adapter.world.map[north.y][north.x].terrain = NullTerrain()
    with pytest.raises(InvalidSpaceException):
        adapter.move_player(player, DIRECTION_VECTORS["n"])
    assert player.location == adapter.world.starting_town  # didn't budge


def test_attacking_bare_handed_raises(adapter):
    player = adapter.get_player(1)
    player.unequip(player.weapon)
    with pytest.raises(NoWeaponEquippedException):
        adapter.attack(player, None)


def test_aiming_a_melee_weapon_at_a_distant_square_raises(adapter):
    player = adapter.get_player(1)
    with pytest.raises(RangedAttackException):
        adapter.attack(player, DIRECTION_VECTORS["n"])


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


def test_an_empty_gun_cannot_shoot(adapter):
    adapter.register_player(2, "Victim")
    attacker = adapter.get_player(1)
    musket = Weapons.Jezail()
    attacker.equip(musket)
    musket.fire()
    assert musket.is_empty

    with pytest.raises(CombatException, match="empty"):
        adapter.attack(attacker, None)


def test_dying_sends_you_back_to_the_starting_town(adapter):
    player = adapter.get_player(1)
    elsewhere = adapter.world.map[0][0]
    player.location = elsewhere

    player.take_damage(player.hit_points_max)
    assert player.location == adapter.world.starting_town


def test_the_map_holds_exactly_width_times_height_spaces(adapter):
    assert len(list(adapter.iter_spaces())) == adapter.width * adapter.height
    assert [(idx, p.name) for idx, p in adapter.iter_registered()] == [(1, "Tester")]


def test_a_player_sees_their_own_neighbourhood(adapter):
    player = adapter.get_player(1)
    nearby = adapter.get_nearby_players(player)
    assert player in nearby

    edge = adapter.world.get_adjacent_spaces(adapter.world.map[0][0], sq_range=2)
    assert all(
        0 <= space.x < adapter.width and 0 <= space.y < adapter.height for space in edge
    )
    assert len(edge) == 9  # a 5x5 window clipped to the top-left corner


def test_screenshots_degrade_gracefully_without_a_renderer(adapter):
    assert adapter.get_player_screenshot(adapter.get_player(1)) == "<No Renderer>"


# --- World tick: NPCs act on real time, not on player input ------------------------------------


def test_ticking_spawns_npcs_and_moves_them_without_the_player(adapter):
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
    seen = {start}
    for _ in range(50):
        world.tick()
        seen.add(npc.location)
        assert world.is_space_valid(npc.location)
    assert len(seen) > 1


def test_a_tick_lets_an_npc_hit_a_player_sharing_its_space(adapter):
    world = adapter.world
    player = adapter.get_player(1)
    npc = Actors.Raider(world, 50, "Mugger")
    world.add_actor(npc, player.location)

    world.tick()
    assert player.hit_points < player.hit_points_max


def test_dead_npcs_are_dropped_on_the_next_tick(adapter):
    world = adapter.world
    npc = Actors.Raider(world, 1, "Doomed")
    world.add_actor(npc, world.starting_town)
    npc.take_damage(10)

    world.tick()
    assert npc not in world.npcs


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
