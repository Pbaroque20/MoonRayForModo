"""MoonRay LS renders at the realtime preview's share of the render's resolution (Realtime preview resolution, Full
to 1/16), a tall picture shrunk as a wide one (ipr.prepare with share); its own resolution row is gone."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_preview_fraction import preferences  # noqa: E402
from moonray_modo.ipr import prepare  # noqa: E402


class Size(unittest.TestCase):
    def size(self, scene_w, scene_h, preview_w, preview_h, share):
        _, w, h = prepare({'width': scene_w, 'height': scene_h}, preview_w, preview_h, 4, None, 32, 100.0, share=share)
        return w, h

    def test_ls_has_no_resolution_of_its_own(self):
        self.assertNotIn('ipr/fraction', preferences.KEYS)
        self.assertFalse(hasattr(preferences, 'LS_FRACTIONS'))

    def test_every_share_offered_is_taken(self):
        for _, share in preferences.FRACTIONS:
            scene_w, scene_h = 1920, 1080
            preview = (round(scene_w / share), round(scene_h / share))
            self.assertEqual(self.size(scene_w, scene_h, preview[0], preview[1], share), preview)

    def test_a_tall_picture_shrinks_as_a_wide_one(self):
        self.assertEqual(self.size(1180, 2000, 148, 250, 8), (148, 250))

    def test_a_share_not_offered_is_refused(self):
        with self.assertRaises(ValueError):
            self.size(1920, 1080, 640, 360, 5)


if __name__ == '__main__':
    unittest.main()
