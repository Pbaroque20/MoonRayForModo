"""MoonRay's realtime preview renders the beauty and the buffer looked at, not every buffer: each was rendered, and
each edit renamed their files, so that a move of the camera was never the camera's alone."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import outputs


class RealtimeOutputs(unittest.TestCase):
    def test_a_preview_rendered_once_has_every_buffer(self):
        self.assertGreater(len(outputs.preview({})), 2)

    def test_realtime_has_the_beauty_and_the_buffer_looked_at(self):
        self.assertEqual(set(outputs.preview({'_geometry_detail': 'fine'})), {'beauty'})
        chosen = next(key for key in outputs.preview({}) if key != 'beauty')
        self.assertEqual(set(outputs.preview({'_geometry_detail': 'fine', 'preview_buffer': chosen})), {'beauty', chosen})

    def test_realtime_composite_keeps_what_it_is_made_of(self):
        self.assertEqual(outputs.preview({'_geometry_detail': 'coarse', 'preview_buffer': 'composite'}), outputs.preview({}))


if __name__ == '__main__':
    unittest.main()
