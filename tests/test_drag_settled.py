"""The last transforms of a followed MoonLightIPR drag (incremental.out_of_place, panel._drag_settled): what the scene sent
last has of each mesh, instance and the camera, against where Modo has its item. No Modo: items stood in for."""
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))


def place(x):
    return [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, x, 0, 0, 1.0]


class Item:
    def __init__(self, x):
        self.matrix = place(x)


class Scene:
    def __init__(self, **where):
        self.items = {name: Item(x) for name, x in where.items()}

    def item(self, identity):
        if identity not in self.items:
            raise LookupError(identity)
        return self.items[identity]


def out_of_place(scene, snapshot, loose=()):
    host = types.ModuleType('moonray_modo.host')
    host.world_matrix = lambda item: list(item.matrix)
    held = sys.modules.get('moonray_modo.host')
    sys.modules['moonray_modo.host'] = host
    try:
        from moonray_modo import incremental
        return incremental.out_of_place(scene, snapshot, loose)
    finally:
        if held is None:
            sys.modules.pop('moonray_modo.host', None)
        else:
            sys.modules['moonray_modo.host'] = held


SENT = {'camera': {'identity': 'cam', 'matrix': place(0)},
        'meshes': [{'identity': 'box', 'matrix': place(1)},
                   {'identity': 'wheel|0', 'source_item': 'wheel', 'matrix': place(2)},
                   {'identity': 'bolts', 'instances': [place(3), place(4)], 'instance_ids': ['boltA', 'boltB']},
                   {'identity': 'fog', 'volumetric': True, 'matrix': place(9)},
                   # An Ocean Plane's mesh at its item's height alone (ocean_plane.lift): here 0, wherever the item stands across.
                   {'identity': 'sea', '_ocean_plane': True, 'matrix': place(0)}]}


def raised(height, x=0):
    held = place(x)
    held[13] = height
    return held


class LastTransforms(unittest.TestCase):
    def test_all_in_place(self):
        self.assertIsNone(out_of_place(Scene(cam=0, box=1, wheel=2, boltA=3, boltB=4, fog=0, sea=0), SENT))

    def test_a_mesh_left_behind_is_placed_where_its_item_stands(self):
        scene, moved = out_of_place(Scene(cam=0, box=1.5, wheel=2, boltA=3, boltB=4, fog=0, sea=0), SENT)
        self.assertEqual(moved, {'box'})
        self.assertEqual(scene['meshes'][0]['matrix'], place(1.5))
        # The scene sent is not changed in place: only the copy.
        self.assertEqual(SENT['meshes'][0]['matrix'], place(1))
        self.assertIs(scene['meshes'][1], SENT['meshes'][1])

    def test_a_mesh_by_its_source_item_and_an_instance_by_its_own(self):
        scene, moved = out_of_place(Scene(cam=0, box=1, wheel=2.5, boltA=3, boltB=4.5, fog=0, sea=0), SENT)
        self.assertEqual(moved, {'wheel', 'boltB'})
        self.assertEqual(scene['meshes'][2]['instances'], [place(3), place(4.5)])

    def test_the_camera_and_its_shutter_close(self):
        sent = dict(SENT, camera={'identity': 'cam', 'matrix': place(0), 'matrix_close': place(0)})
        scene, moved = out_of_place(Scene(cam=0.25, box=1, wheel=2, boltA=3, boltB=4, fog=0, sea=0), sent)
        self.assertEqual(moved, {'cam'})
        self.assertEqual((scene['camera']['matrix'], scene['camera']['matrix_close']), (place(0.25), place(0.25)))

    def test_loose_copies_and_volumes_are_left_as_they_are_and_a_sea_moved_across_is_in_place(self):
        self.assertIsNone(out_of_place(Scene(cam=0, box=1, wheel=2, boltA=3, boltB=7, fog=5, sea=5), SENT, loose={'boltB'}))

    def test_a_sea_raised_is_placed_at_its_items_height(self):
        scene = Scene(cam=0, box=1, wheel=2, boltA=3, boltB=4, fog=0, sea=5)
        scene.items['sea'].matrix = raised(2.5, x=5)
        placed, moved = out_of_place(scene, SENT)
        self.assertEqual(moved, {'sea'})
        self.assertEqual(placed['meshes'][4]['matrix'], raised(2.5))

    def test_what_modo_cannot_say_is_left(self):
        self.assertIsNone(out_of_place(Scene(cam=0, box=1, boltA=3, boltB=4), SENT))

    def test_the_last_digits_of_a_render_cache_are_no_move(self):
        self.assertIsNone(out_of_place(Scene(cam=0, box=1 + 1e-7, wheel=2, boltA=3, boltB=4, fog=0, sea=0), SENT))


def refreshed(scene, snapshot):
    host = types.ModuleType('moonray_modo.host')
    host.world_matrix = lambda item: list(item.matrix)
    held = sys.modules.get('moonray_modo.host')
    sys.modules['moonray_modo.host'] = host
    try:
        from moonray_modo import incremental
        incremental.refresh_transforms(scene, snapshot)
        return snapshot
    finally:
        if held is None:
            sys.modules.pop('moonray_modo.host', None)
        else:
            sys.modules['moonray_modo.host'] = held


class DragStepsInABlurredScene(unittest.TestCase):
    """A drag step from a scene read with motion blur (the keyed dragon after its first release): the mesh moved stands
    where it now is at the shutter's opening, its close and the frame, so that the step shows it there."""

    def test_a_moved_mesh_is_still_where_it_now_stands(self):
        snapshot = {'meshes': [{'identity': 'dragon', 'matrix': place(-1.0), 'matrix_close': place(-0.9), 'matrix_frame': place(-0.95)},
                               {'identity': 'rock', 'matrix': place(5), 'matrix_close': place(6), 'matrix_frame': place(5.5)}]}
        refreshed(Scene(dragon=2.6, rock=5), snapshot)
        dragon, rock = snapshot['meshes']
        self.assertEqual((dragon['matrix'], dragon['matrix_close'], dragon['matrix_frame']), (place(2.6),) * 3)
        # What did not move keeps its motion.
        self.assertEqual((rock['matrix_close'], rock['matrix_frame']), (place(6), place(5.5)))

    def test_a_moved_instance_and_its_shutter(self):
        snapshot = {'meshes': [{'identity': 'bolts', 'instances': [place(3), place(4)], 'instance_ids': ['boltA', 'boltB'],
                                'instances_close': [place(3.5), place(4.5)], 'instances_frame': [place(3.2), place(4.2)]}]}
        shared_close = snapshot['meshes'][0]['instances_close']
        refreshed(Scene(boltA=3, boltB=7), snapshot)
        bolts = snapshot['meshes'][0]
        self.assertEqual(bolts['instances_close'], [place(3.5), place(7)])
        self.assertEqual(bolts['instances_frame'], [place(3.2), place(7)])
        # The list read is not changed in place: a copy is.
        self.assertEqual(shared_close, [place(3.5), place(4.5)])

    def test_the_camera_moved_stands_there_at_the_shutters_close(self):
        source = (ROOT / 'kit/MoonRayForModo/python/moonray_modo/incremental.py').read_text(encoding='utf-8')
        self.assertIn("if 'matrix_close' in camera:result['camera']['matrix_close']=list(result['camera']['matrix'])", source)


class FirstDragAfterRealtime(unittest.TestCase):
    """The first drags after RT came on, on a test dragon, read the whole scene and waited for the release, twice."""

    def test_surroundings_read_with_motion_blur_are_those_read_sharp(self):
        from moonray_modo.incremental import surroundings
        sharp = {'environments': [{'name': 'Sky', 'matrix': [1, 0]}], 'entities': [{'class': 'EnvLight', 'matrix': [1]}]}
        blurred = {'environments': [{'name': 'Sky', 'matrix': [1, 0], 'matrix_close': [2, 0]}],
                   'entities': [{'class': 'EnvLight', 'matrix': [1], 'matrix_close': [3]}]}
        self.assertEqual(surroundings(sharp), surroundings(blurred))
        self.assertNotEqual(surroundings(sharp), surroundings({'environments': [{'name': 'Sky', 'matrix': [5, 0]}],
                                                               'entities': [{'class': 'EnvLight', 'matrix': [1]}]}))

    def test_what_a_whole_reading_was_made_with_is_seen_even_when_held_back(self):
        tick = (ROOT / 'kit/MoonRayForModo/python/moonray_modo/panel.py').read_text(encoding='utf-8').split('    def _live_tick(self):')[1]
        seen = tick.index('self._last_time=time;self._live_settings=settings')
        self.assertLess(seen, tick.index("self._drag_count('waited: what lights the scene from around it changed')"))
        self.assertEqual(tick.count('self._last_time=time;self._live_settings=settings'), 1)


class Wiring(unittest.TestCase):
    def test_the_panel_looks_once_a_followed_drag_is_let_go(self):
        panel = (ROOT / 'kit/MoonRayForModo/python/moonray_modo/panel.py').read_text(encoding='utf-8')
        self.assertIn("self._drag_followed=False;self._drag_settle_later()", panel)
        self.assertEqual(panel.count('self._drag_followed=True'), 2)
        # Sent sampled to the end, not as a step of a drag.
        self.assertIn("scene.pop('_drag',None)", panel.split('def _drag_settled')[1].split('def _drag_settle_said')[0])


if __name__ == '__main__':
    unittest.main()
