"""MoonRay LS's resolution as a share of the render's (1/2 to 1/16, or as realtime), never larger than the realtime
preview; a width limit in pixels chosen before taken to the nearest share of a 1920-wide render (ipr.prepare,
preferences.get('ipr/fraction'))."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_preview_fraction import Store, preferences  # noqa: E402
from moonray_modo.ipr import prepare  # noqa: E402


def read(**stored):
    held = preferences.Preferences.__new__(preferences.Preferences)
    held.store = Store(stored)
    return held.get('ipr/fraction')


class Choice(unittest.TestCase):
    def test_the_choices(self):
        self.assertEqual([value for _, value in preferences.LS_FRACTIONS], [1, 2, 4, 8, 16])

    def test_a_quarter_where_nothing_was_chosen(self):
        self.assertEqual(read(), 4)

    def test_a_width_limit_chosen_before_becomes_the_nearest_share(self):
        self.assertEqual(read(**{'ipr/width': '640'}), 4)
        self.assertEqual(read(**{'ipr/width': '960'}), 2)
        self.assertEqual(read(**{'ipr/width': '1280'}), 2)
        self.assertEqual(read(**{'ipr/width': '240'}), 8)
        self.assertEqual(read(**{'ipr/width': '80'}), 16)

    def test_a_share_chosen_is_kept_and_nonsense_is_not(self):
        for value in (1, 2, 4, 8, 16):
            self.assertEqual(read(**{'ipr/fraction': str(value), 'ipr/width': '80'}), value)
        self.assertEqual(read(**{'ipr/fraction': '3', 'ipr/width': '960'}), 2)


class Size(unittest.TestCase):
    def size(self, scene_w, scene_h, preview_w, preview_h, share):
        _, w, h = prepare({'width': scene_w, 'height': scene_h}, preview_w, preview_h, 4, None, 32, 100.0, share=share)
        return w, h

    def test_a_tall_picture_shrinks_as_a_wide_one(self):
        # A 1180 x 2000 portrait, realtime at a third: LS at a quarter of the render.
        self.assertEqual(self.size(1180, 2000, 393, 667, 4), (295, 501))
        self.assertEqual(self.size(1920, 1080, 640, 360, 4), (480, 270))

    def test_never_larger_than_realtime(self):
        self.assertEqual(self.size(1920, 1080, 640, 360, 2), (640, 360))
        self.assertEqual(self.size(1920, 1080, 640, 360, 1), (640, 360))

    def test_a_share_not_offered_is_refused(self):
        with self.assertRaises(ValueError):
            self.size(1920, 1080, 640, 360, 3)


if __name__ == '__main__':
    unittest.main()
