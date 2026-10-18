"""Camera Sequence keys: the camera each frame is rendered through, overlaps, and the frames no key covers."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import camera_sequence

KEYS = {'enabled': True, 'keys': [{'camera': 'wide', 'first': 1, 'last': 24}, {'camera': 'close', 'first': 25, 'last': 48},
                                  {'camera': 'wide', 'first': 60, 'last': 72}]}


class Keys(unittest.TestCase):
    def test_each_frame_has_its_keyed_camera(self):
        self.assertEqual(camera_sequence.camera_at(KEYS, 1), 'wide')
        self.assertEqual(camera_sequence.camera_at(KEYS, 24), 'wide')
        self.assertEqual(camera_sequence.camera_at(KEYS, 25), 'close')
        self.assertEqual(camera_sequence.camera_at(KEYS, 65), 'wide')

    def test_a_frame_no_key_covers_is_the_render_cameras(self):
        self.assertIsNone(camera_sequence.camera_at(KEYS, 50))
        self.assertIsNone(camera_sequence.camera_at(KEYS, 0))
        self.assertEqual(camera_sequence.gaps(KEYS, 1, 72), [(49, 59)])

    def test_switched_off_no_frame_is_keyed(self):
        self.assertIsNone(camera_sequence.camera_at(dict(KEYS, enabled=False), 5))

    def test_where_keys_overlap_the_later_one_is_used(self):
        keys = {'keys': [{'camera': 'a', 'first': 1, 'last': 30}, {'camera': 'b', 'first': 20, 'last': 40}]}
        self.assertEqual(camera_sequence.camera_at(keys, 25), 'b')
        self.assertEqual(camera_sequence.overlaps(keys), [(0, 1)])

    def test_keys_are_kept_whole_and_in_order(self):
        kept = camera_sequence.normalized({'keys': [{'camera': 'b', 'first': 30, 'last': 10}, {'camera': 'a', 'first': '1', 'last': 5}]})
        self.assertEqual(kept['keys'], [{'camera': 'a', 'first': 1, 'last': 5}, {'camera': 'b', 'first': 10, 'last': 30}])
        self.assertTrue(kept['enabled'])
        with self.assertRaises(ValueError):
            camera_sequence.normalized({'keys': [{'first': 1, 'last': 2}]})


if __name__ == '__main__':
    unittest.main()
