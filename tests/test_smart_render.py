import pathlib
import random
import sys
import unittest
from array import array

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import denoising, smart_render

WIDTH, HEIGHT = 240, 160


def picture(sigma, edges=False, holes=0.0, seed=3):
    """A picture of a gradient with noise of sigma times each pixel's brightness; stripes if edges; and a share of
    its pixels not rendered yet."""
    chance = random.Random(seed)
    values = array('f')
    for y in range(HEIGHT):
        for x in range(WIDTH):
            base = 0.2 + 0.6 * x / WIDTH + (0.5 if edges and (x // 24) % 2 else 0)
            value = max(1e-4, base * (1 + chance.gauss(0, sigma))) if chance.random() >= holes else 0.0
            values.extend((value, value, value))
    return values.tobytes()


class Noise(unittest.TestCase):
    def test_reads_lower_as_the_picture_cleans(self):
        read = [smart_render.noise(WIDTH, HEIGHT, picture(sigma))[0] for sigma in (0.5, 0.2, 0.1, 0.05, 0.0)]
        self.assertEqual(read, sorted(read, reverse=True))
        self.assertLess(read[-1], 1e-4)
        # About four tenths of the noise there is, whatever its size.
        self.assertAlmostEqual(read[1] / 0.2, read[2] / 0.1, delta=0.08)

    def test_edges_are_not_taken_for_noise(self):
        plain = smart_render.noise(WIDTH, HEIGHT, picture(0.1))[0]
        striped = smart_render.noise(WIDTH, HEIGHT, picture(0.1, edges=True))[0]
        self.assertAlmostEqual(plain, striped, delta=0.15 * plain)
        self.assertLess(smart_render.noise(WIDTH, HEIGHT, picture(0.0, edges=True))[0], 0.005)

    def test_a_picture_not_yet_rendered_is_not_judged(self):
        value, share = smart_render.noise(WIDTH, HEIGHT, picture(0.0, holes=0.5))
        self.assertIsNone(value)
        self.assertAlmostEqual(share, 0.5, delta=0.05)
        self.assertEqual(smart_render.noise(WIDTH, HEIGHT, bytes(WIDTH * HEIGHT * 12)), (None, 0.0))
        self.assertEqual(smart_render.noise(WIDTH, HEIGHT, b'short'), (None, 0.0))


    def test_a_coarse_picture_is_not_judged(self):
        # As a pass begins: each sample spread over a block of four pixels by four, then two by two.
        fine = array('f')
        fine.frombytes(picture(0.3))
        for block in (4, 2):
            coarse = array('f', fine)
            for y in range(HEIGHT):
                for x in range(WIDTH):
                    source = ((y // block) * block * WIDTH + (x // block) * block) * 3
                    at = (y * WIDTH + x) * 3
                    coarse[at:at + 3] = fine[source:source + 3]
            self.assertIsNone(smart_render.noise(WIDTH, HEIGHT, coarse.tobytes())[0], block)
        self.assertIsNotNone(smart_render.noise(WIDTH, HEIGHT, fine.tobytes())[0])

    def test_a_small_part_still_in_large_blocks_is_enough_not_to_judge(self):
        # As when a render is nearly filled in and its hardest tiles are not: a twentieth of the picture in blocks
        # of sixteen pixels.
        values = array('f')
        values.frombytes(picture(0.05))
        for y in range(48, 96):
            for x in range(96, 144):
                source = ((y // 16) * 16 * WIDTH + (x // 16) * 16) * 3
                at = (y * WIDTH + x) * 3
                values[at:at + 3] = values[source:source + 3]
        self.assertIsNone(smart_render.noise(WIDTH, HEIGHT, values.tobytes())[0])

    def test_a_plain_background_does_not_hide_a_noisy_subject(self):
        values = array('f')
        values.frombytes(picture(0.3))
        alone = smart_render.noise(WIDTH, HEIGHT, values.tobytes())[0]
        # The left two thirds of it a plain backdrop, every pixel the same.
        for y in range(HEIGHT):
            for x in range(2 * WIDTH // 3):
                at = (y * WIDTH + x) * 3
                values[at:at + 3] = array('f', (0.5, 0.5, 0.5))
        backed = smart_render.noise(WIDTH, HEIGHT, values.tobytes())[0]
        self.assertIsNotNone(backed)
        self.assertAlmostEqual(backed, alone, delta=0.3 * alone)


class Stopping(unittest.TestCase):
    def watch(self, level):
        self.now = [0.0]
        return smart_render.Watch(level, lambda: self.now[0])

    def test_stops_after_two_clean_looks_running(self):
        watch = self.watch('medium')
        clean, noisy = picture(0.05), picture(0.5)
        self.assertFalse(watch.look(WIDTH, HEIGHT, noisy))
        self.now[0] = 2.5
        self.assertFalse(watch.look(WIDTH, HEIGHT, clean))      # one clean look is not enough
        self.now[0] = 5.0
        self.assertFalse(watch.look(WIDTH, HEIGHT, noisy))      # and a noisy one starts the count again
        self.now[0] = 7.5
        self.assertFalse(watch.look(WIDTH, HEIGHT, clean))
        self.now[0] = 10.0
        self.assertTrue(watch.look(WIDTH, HEIGHT, clean))
        self.now[0] = 12.5
        self.assertFalse(watch.look(WIDTH, HEIGHT, clean))      # said once
        self.assertLess(watch.noise, smart_render.LEVELS['medium'])

    def test_looks_no_more_often_than_it_should(self):
        watch = self.watch('draft')
        clean = picture(0.02)
        self.assertFalse(watch.look(WIDTH, HEIGHT, clean))
        self.now[0] = 0.5
        self.assertFalse(watch.look(WIDTH, HEIGHT, clean))      # too soon to count as a second look
        self.now[0] = 2.1
        self.assertTrue(watch.look(WIDTH, HEIGHT, clean))

    def test_a_stricter_level_waits_for_a_cleaner_picture(self):
        middling = picture(0.085)      # reads about 0.037
        for level, stops in (('draft', True), ('medium', True), ('fine', False)):
            watch = self.watch(level)
            watch.look(WIDTH, HEIGHT, middling)
            self.now[0] = 3.0
            self.assertEqual(watch.look(WIDTH, HEIGHT, middling), stops, level)

    def test_off_never_stops(self):
        watch = self.watch('off')
        self.assertFalse(watch.look(WIDTH, HEIGHT, picture(0.0)))
        self.now[0] = 5.0
        self.assertFalse(watch.look(WIDTH, HEIGHT, picture(0.0)))


class Settings(unittest.TestCase):
    def test_the_level_is_a_denoising_setting(self):
        self.assertEqual(denoising.settings({})['smart'], 'off')
        self.assertEqual(denoising.settings({'smart': 'fine'})['smart'], 'fine')
        with self.assertRaises(ValueError):
            denoising.settings({'smart': 'sometimes'})
        self.assertEqual(set(smart_render.LEVELS) | {'off'}, set(denoising.SMART))
        self.assertEqual([value for _, value in smart_render.CHOICES], list(denoising.SMART))

    def test_the_form_has_it(self):
        text = (ROOT / 'kit/MoonRayForModo/render_settings.cfg').read_text(encoding='utf-8')
        self.assertIn('cmd moonray.render.smart_render ?', text)


if __name__ == '__main__':
    unittest.main()
