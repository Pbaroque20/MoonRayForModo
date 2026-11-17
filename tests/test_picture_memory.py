"""What the preview's pictures take in memory at the render's size (picture_memory): said in the MoonRay Terminal once
a render and size, among the notices when a picture is past 64 MB (a 4K one is), and as a warning where the memory
free is short for pictures that size."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import picture_memory as pm  # noqa: E402

GB = 1024 ** 3


class Figures(unittest.TestCase):
    def test_a_picture_is_float_rgb_and_said_in_mb_or_gb(self):
        self.assertEqual(pm.picture_bytes(3840, 2160), 3840 * 2160 * 12)
        self.assertEqual(pm.size(pm.picture_bytes(3840, 2160)), '94.9 MB')
        self.assertEqual(pm.size(pm.picture_bytes(16384, 16384)), '3.0 GB')
        # The renderer's, the preview's copy, the copy shown, and a stopped render's three of three outputs.
        self.assertEqual(pm.held_bytes(10, 10), 10 * 10 * 12 * 11 + 10 * 10 * 4)

    def test_the_terminal_says_every_size(self):
        line = pm.terminal_line(1920, 1080, 40 * GB)
        self.assertIn('Preview pictures 1920 x 1080: 23.7 MB each in memory', line)
        self.assertIn('40.0 GB of memory free', line)
        self.assertNotIn('short', line)
        self.assertIn('Memory is short', pm.terminal_line(16384, 16384, 10 * GB))


class Notices(unittest.TestCase):
    def test_none_for_pictures_up_to_64_mb(self):
        self.assertIsNone(pm.notice(1920, 1080, 40 * GB))
        self.assertIsNone(pm.notice(2560, 2184, 40 * GB))  # 63.98 MB

    def test_a_4k_render_is_said_with_the_memory_free(self):
        said = pm.notice(3840, 2160, 40 * GB)
        self.assertIn('large: 3840 x 2160, 94.9 MB each in memory', said)
        self.assertIn('40.0 GB of memory free', said)

    def test_a_warning_where_memory_is_short(self):
        said = pm.notice(16384, 16384, 10 * GB)
        self.assertTrue(said.startswith('Memory is short for this render'), said)
        self.assertIn('10.0 GB is free', said)
        self.assertTrue(pm.short(16384, 16384, 10 * GB) and not pm.short(3840, 2160, 40 * GB))


class Watch(unittest.TestCase):
    def test_said_once_a_size_then_looked_at_again_every_few_seconds(self):
        watch = pm.Watch()
        free = [40 * GB]
        original = pm.free_bytes
        pm.free_bytes = lambda: free[0]
        try:
            line, said, changed = watch.seen('a', 3840, 2160, now=0.0)
            self.assertTrue(line and said and changed)
            line, said, changed = watch.seen('a', 3840, 2160, now=1.0)
            self.assertEqual((line, changed), (None, False), 'nothing new within EVERY seconds')
            free[0] = 2 * GB
            line, said, changed = watch.seen('a', 3840, 2160, now=1.0 + pm.EVERY)
            self.assertIsNone(line, 'the size is not said again')
            self.assertTrue(changed and said.startswith('Memory is short'), said)
            line, said, changed = watch.seen('b', 1280, 720, now=2.0 + pm.EVERY)
            self.assertTrue(line, 'a new render says its size')
            self.assertTrue(changed and said is None, 'small pictures take the notice away')
        finally:
            pm.free_bytes = original

    def test_the_memory_free_is_read(self):
        free = pm.free_bytes()
        self.assertTrue(free is None or free > 0)


if __name__ == '__main__':
    unittest.main()
