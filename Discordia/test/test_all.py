import logging
import os
import random
import tempfile
import unittest
from pathlib import Path
from typing import Iterator, List

from PIL import Image

from Discordia.GameLogic import GameSpace, Actors, Weapons, Armor
from Discordia.GameLogic.Actors import PlayerCharacter, PlayerClass
from Discordia.GameLogic.GameSpace import MountainTerrain, PlayerActionResponse
from Discordia.GameLogic.Weapons import Jezail
from Discordia.Interface.Database import Database
from Discordia.Interface.Rendering.DesktopApp import WindowRenderer
from Discordia.Interface.WorldAdapter import WorldAdapter
from Discordia.GameLogic.Items import Equipment, EquipmentSet, OffHandEquipment

Armor.random()  # Keep Armor import; we need the namespace

LOG = logging.getLogger("Discordia.test")
logging.basicConfig(level=logging.INFO)


def clean_screenshots():
    """ Delete all files in the screenshot folder """
    folder = Path("./Discordia/PlayerViews")
    for file_ in os.listdir(folder):
        file_path = os.path.join(folder, file_)
        try:
            if os.path.isfile(file_path) and file_ != "README.md":
                os.unlink(file_path)
        except Exception as e:
            raise e


class TestGeneral(unittest.TestCase):
    WORLD_WIDTH = 100
    WORLD_HEIGHT = 100
    NUM_USERS = 25
    NUM_STEPS = 250

    random_seed = 0

    @classmethod
    def setUpClass(cls) -> None:
        assert cls.NUM_USERS > 0

        # Fixed by default so failures reproduce; set DISCORDIA_TEST_SEED to fuzz.
        cls.random_seed = int(os.environ.get("DISCORDIA_TEST_SEED", 0))

        clean_screenshots()

        LOG.info("Discordia server started")

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.world = GameSpace.World("Test World",
                                     self.WORLD_WIDTH,
                                     self.WORLD_HEIGHT,
                                     seed=self.random_seed)
        self.adapter = WorldAdapter(self.world)
        self.display = WindowRenderer(self.adapter)
        
        for idx in range(self.NUM_USERS):
            self.adapter.register_player(idx, player_name=f"User{idx}")

        self.display.on_draw()

    def _move_randomly(self) -> Iterator[List[PlayerActionResponse]]:
        """
        All users move one step in a random direction, if they can
        """
        for idx in range(self.NUM_USERS):
            direction = random.choice(list(GameSpace.DIRECTION_VECTORS.values()))
            player = self.adapter.get_player(idx)
            yield player.attempt_move(direction)

    def test_hp(self):
        for u in [self.adapter.get_player(n) for n in range(self.NUM_USERS)]:
            self.assertEqual(u.hit_points, u.hit_points_max)
            self.assertEqual(u.hit_points_max, u.player_class.hit_points_max_base)

    def test_move_randomly(self):
        """
        Have actors move randomly about the map, triggering Events. Test `fail_count` to make sure they can move at
        least some of the time.
        """
        fail_count = 0
        for step in range(self.NUM_STEPS):
            for result in self._move_randomly():
                if len(result) == 1 and result[0].failed:
                    fail_count += 1

        self.assertLess(fail_count, self.NUM_USERS * self.NUM_STEPS, "Failed every movement attempt.")
        LOG.info(f"Successes: {(self.NUM_USERS * self.NUM_STEPS) - fail_count} - Failcount: {fail_count}")

    def test_screenshot(self):
        """
        Ensure that all actors are able to take pictures that aren't completely transparent or black
        """
        for _ in range(3):
            for _ in self._move_randomly():
                pass
        self.display.on_draw()
        for idx in range(self.NUM_USERS):
            player = self.adapter.get_player(idx)
            self.adapter.get_player_screenshot(player)
            img: Image.Image = Image.open(Path(f"./Discordia/PlayerViews/User{idx}_screenshot.png"))
            self.assertFalse(all(p == (0, 0, 0, 255) for p in img.getdata()), "Black screenshot taken")
            self.assertFalse(all(p == (0, 0, 0, 0) for p in img.getdata()), "Transparent screenshot taken")
            self.assertGreater(img.height, 1)
            self.assertGreater(img.width, 1)

    def test_store_purchasing(self):
        """
        Have randomly moving users buy weapons from towns they encounter
        """
        successes = 0
        for idx in range(self.NUM_USERS):
            player = self.adapter.get_player(idx)
            player.currency += 10000
        for step in range(self.NUM_STEPS):
            for result in self._move_randomly():
                if (len(result) == 1 and result[0].failed) or len(result) == 0:
                    """ If failed to move, or everyone is dead: keep going. """
                    continue

                self.assertTrue(isinstance(result[0].source, PlayerCharacter))
                player: PlayerCharacter = result[0].source # type: ignore
                if self.adapter.is_town(player.location):
                    self.assertIsNotNone(player.location.name)
                    self.assertTrue(isinstance(player.location, GameSpace.Town))
                    if player.location.store.inventory:  # type: ignore
                        town: GameSpace.Town = player.location  # type: ignore
                        index = random.randrange(len(town.store.inventory))
                        if town.store.sell_item(index, player):
                            item = player.inventory[-1]
                            player.equip(item)
                            if isinstance(item, Weapons.Weapon):
                                self.assertTrue(player.has_weapon_equipped)
                                self.assertTrue(player.weapon == item)
                                self.assertFalse(isinstance(player.weapon, Weapons.Fist))
                                self.assertIsNotNone(player.weapon)
                            elif isinstance(item, Equipment):
                                # Not armor_count: that's a random coverage roll and can legitimately be 0
                                self.assertIn(item, list(player.equipment_set))
                            successes += 1
        LOG.info(f"Buying Successes: {successes}")
        self.assertGreater(successes, 0, "All transactions failed")

    def test_ensure_starting_fist(self):
        """
        Ensure users start with fists equipped
        """
        id_ = 1234560
        name = "abcdefgh"
        self.adapter.register_player(id_, name)
        player = self.adapter.get_player(id_)
        self.assertTrue(isinstance(player.weapon, Weapons.Fist))

    def test_equip_slots(self):
        """
        Equipment lands in the right slot, unequip empties it, junk is rejected
        """
        equipment_set = EquipmentSet()
        helmet = Armor.Helmet()
        equipment_set.equip(helmet)
        self.assertIs(equipment_set.head, helmet)
        equipment_set.unequip(helmet)
        self.assertIsNot(equipment_set.head, helmet)

        fist = Weapons.Fist()  # Both a Main- and an OffHandEquipment
        equipment_set.equip(fist)
        self.assertIs(equipment_set.main_hand, fist)
        equipment_set.equip(fist, OffHandEquipment)
        self.assertIs(equipment_set.off_hand, fist)

        with self.assertRaises(ValueError):
            equipment_set.equip(object())  # type: ignore

    def test_database_roundtrip(self):
        """
        Save a played-in world and load it back: same map, same characters, same gear.
        """
        player = self.adapter.get_player(0)
        player.player_class = Actors.RaiderClass()
        player.currency = 4321
        player.hit_points -= 7
        player.equip(Jezail())
        player.inventory.append(Armor.Helmet())
        for _ in self._move_randomly():
            pass

        path = Path(self.temp_dir.name) / "roundtrip.db"
        database = Database(path)
        database.save(self.adapter)
        database.close()

        loaded = Database(path)
        adapter = loaded.load()
        self.assertIsNotNone(adapter)
        assert adapter is not None  # for the type checker
        loaded.close()

        self.assertEqual(adapter.world.seed, self.world.seed)
        self.assertEqual([str(space.terrain) for space in adapter.iter_spaces()],
                         [str(space.terrain) for space in self.adapter.iter_spaces()])
        self.assertEqual(len(list(adapter.iter_registered())), self.NUM_USERS)

        restored = adapter.get_player(0)
        self.assertEqual(restored.name, player.name)
        self.assertEqual(restored.currency, player.currency)
        self.assertEqual(restored.hit_points, player.hit_points)
        self.assertIsInstance(restored.player_class, Actors.RaiderClass)
        self.assertIsInstance(restored.weapon, Jezail)
        self.assertEqual([type(item) for item in restored.inventory], [Armor.Helmet])
        self.assertEqual((restored.location.x, restored.location.y), (player.location.x, player.location.y))

    def test_database_starts_empty(self):
        """
        A database nobody has saved to yet has no world to hand back
        """
        database = Database(Path(self.temp_dir.name) / "empty.db")
        self.assertIsNone(database.load())
        database.close()

    def test_astar_pathfinding(self):
        self.display.on_draw()
        self.display.get_world_view(title="astar_before")
        start = self.world.starting_town
        found_path = None
        end_index = 1
        for end_index in range(end_index, len(self.world.towns)-1):
            end = self.world.towns[end_index]
            found_path = GameSpace.AStarPathfinder(self.world).astar(start, end)
            if found_path:
                found_path = list(found_path)
                break
        if not found_path:
            self.fail("no path found")
        for space in found_path:
            self.world.map[space.y][space.x].terrain = GameSpace.NullTerrain()
        if end_index > 1:
            LOG.info(f"end_index: {end_index}")
        self.display.on_draw()
        self.display.get_world_view(title="astar_after")

    def test_function_closest(self):
        start = self.world.starting_town
        town_list = start.closest(self.world.towns, size=len(self.world.towns))  # type: ignore
        min_dist = 0
        self.assertTrue(len(self.world.towns) > 0, "No towns")
        self.assertTrue(len(town_list) > 0, "closest doesn't work")
        for town in town_list:
            LOG.info(f"Distance: {start.distance(town)}")
            self.assertGreaterEqual(start.distance(town), min_dist)
            min_dist = start.distance(town)

    def test_body_types(self):
        body_codes = [body().size_code for body in Actors.BodyType.__subclasses__()]
        sort = sorted(body_codes)
        self.assertEqual(body_codes, sort)

    def test_different_classes(self):
        self.display.on_draw()
        for idx in range(self.NUM_USERS):
            player = self.adapter.get_player(idx)
            new_class: PlayerClass = random.choice(PlayerClass.__subclasses__())()
            player.player_class = new_class
            self.assertEqual(player.hit_points_max, new_class.hit_points_max_base)
        for _ in range(50):
            for _ in self._move_randomly():
                pass
        self.display.on_draw()
        self.display.get_world_view("classes")

    def test_jezail_buff(self):
        user: PlayerCharacter = next(self.adapter.iter_players())
        rifle = Jezail()
        user.equip(rifle)
        dmg1 = rifle.calc_damage(1)
        user.location.terrain = MountainTerrain()
        dmg2 = rifle.calc_damage(1)
        self.assertTrue(dmg2 == 2 * dmg1)

    """
    # This test always returns with pytest status 1. Even xfail won't save it. We have transgressed upon God's domain
    def test_window(self):

        update_display(self.display, True, True)
    """

    def tearDown(self) -> None:
        LOG.info(f"Sprite-Miss Count: {self.display._sprite_cache.miss_count}")
        # self.display.on_draw()
        # self.display.get_world_view()
