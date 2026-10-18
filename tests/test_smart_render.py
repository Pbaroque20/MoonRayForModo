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


def coarsened(values, block, left, top, right, bottom):
    """values with a part of the picture as it is before it is filled in: each block of pixels the same."""
    for y in range(top, bottom):
        for x in range(left, right):
            source = ((y // block) * block * WIDTH + (x // block) * block) * 3
            at = (y * WIDTH + x) * 3
            values[at:at + 3] = values[source:source + 3]
    return values


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

    def test_a_subject_on_a_black_background_is_judged_by_the_subject(self):
        # Two thirds of the picture black, as the origami cheetah's is: it was never judged at all.
        values = array('f')
        values.frombytes(picture(0.1))
        alone = smart_render.noise(WIDTH, HEIGHT, values.tobytes())[0]
        for y in range(HEIGHT):
            for x in range(2 * WIDTH // 3):
                at = (y * WIDTH + x) * 3
                values[at:at + 3] = array('f', (0.0, 0.0, 0.0))
        value, share = smart_render.noise(WIDTH, HEIGHT, values.tobytes())
        self.assertIsNotNone(value)
        self.assertAlmostEqual(value, alone, delta=0.3 * alone)
        self.assertAlmostEqual(share, 1 / 3.0, delta=0.05)

    def test_a_picture_with_nothing_in_it_is_not_judged(self):
        self.assertEqual(smart_render.noise(WIDTH, HEIGHT, bytes(WIDTH * HEIGHT * 12)), (None, 0.0))
        self.assertEqual(smart_render.noise(WIDTH, HEIGHT, b'short'), (None, 0.0))

    def test_a_reading_is_there_to_show_while_much_of_the_picture_is_coarse(self):
        values = array('f')
        values.frombytes(picture(0.1))
        whole = smart_render.reading(WIDTH, HEIGHT, values.tobytes())
        self.assertFalse(whole[2])
        # The left half of it still in blocks of four pixels.
        coarsened(values, 4, 0, 0, WIDTH // 2, HEIGHT)
        value, share, coarse = smart_render.reading(WIDTH, HEIGHT, values.tobytes())
        self.assertTrue(coarse)
        # Read from the part that is filled in, so much what it read of the whole.
        self.assertAlmostEqual(value, whole[0], delta=0.25 * whole[0])
        # And it is not stopped by: the reading a render is stopped by has nothing to say yet.
        self.assertIsNone(smart_render.noise(WIDTH, HEIGHT, values.tobytes())[0])

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

    def test_a_few_tiles_still_being_filled_in_do_not_hold_it_back(self):
        # A twentieth of the picture in blocks of sixteen pixels, as the hardest tiles are late in a render: a
        # render that is stopped finishes those before its picture is taken.
        values = array('f')
        values.frombytes(picture(0.05))
        alone = smart_render.noise(WIDTH, HEIGHT, values.tobytes())[0]
        coarsened(values, 16, 96, 48, 144, 96)
        value = smart_render.noise(WIDTH, HEIGHT, values.tobytes())[0]
        self.assertIsNotNone(value)
        self.assertAlmostEqual(value, alone, delta=0.2 * alone)

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

    def test_a_picture_half_coarse_is_not_stopped_however_clean_the_rest(self):
        values = array('f')
        values.frombytes(picture(0.02))
        coarsened(values, 4, 0, 0, WIDTH // 2, HEIGHT)
        watch = self.watch('draft')
        for moment in (0.0, 3.0, 6.0):
            self.now[0] = moment
            self.assertFalse(watch.look(WIDTH, HEIGHT, values.tobytes()))
        self.assertTrue(watch.coarse)
        self.assertIsNotNone(watch.noise)

    def test_a_clean_picture_with_a_few_coarse_tiles_is_stopped(self):
        values = array('f')
        values.frombytes(picture(0.02))
        coarsened(values, 16, 96, 48, 144, 96)
        watch = self.watch('medium')
        self.assertFalse(watch.look(WIDTH, HEIGHT, values.tobytes()))
        self.now[0] = 3.0
        self.assertTrue(watch.look(WIDTH, HEIGHT, values.tobytes()))

    def test_off_never_stops(self):
        watch = self.watch('off')
        self.assertFalse(watch.look(WIDTH, HEIGHT, picture(0.0)))
        self.now[0] = 5.0
        self.assertFalse(watch.look(WIDTH, HEIGHT, picture(0.0)))


class Settings(unittest.TestCase):
    def test_the_level_is_a_denoising_setting(self):
        self.assertEqual(denoising.settings({})['smart'], 'off')
        self.assertEqual(denoising.settings({'engine': 'optix', 'smart': 'fine'})['smart'], 'fine')
        # With the Denoiser Off, Smart Render is off too: it stops a render for a denoiser to finish.
        self.assertEqual(denoising.settings({'engine': 'off', 'smart': 'fine'})['smart'], 'off')
        with self.assertRaises(ValueError):
            denoising.settings({'smart': 'sometimes'})
        self.assertEqual(set(smart_render.LEVELS) | {'off'}, set(denoising.SMART))
        self.assertEqual([value for _, value in smart_render.CHOICES], list(denoising.SMART))

    def test_the_form_has_it(self):
        text = (ROOT / 'kit/MoonRayForModo/render_settings.cfg').read_text(encoding='utf-8')
        self.assertIn('cmd moonray.render.smart_render ?', text)


class ImportantParts(unittest.TestCase):
    def test_a_noisy_subject_is_not_hidden_by_a_clean_gradient_around_it(self):
        # A smooth ramp all over, as a floor is, and a noisy square in the middle of it a sixth of the picture.
        import random as chance_
        chance = chance_.Random(3)
        values = array('f')
        for y in range(HEIGHT):
            for x in range(WIDTH):
                level = 0.2 + 0.6 * x / WIDTH + 0.1 * y / HEIGHT
                if WIDTH // 3 <= x < 2 * WIDTH // 3 and HEIGHT // 4 <= y < 3 * HEIGHT // 4:
                    level *= 1 + chance.gauss(0, 0.2)
                values.extend((max(1e-4, level),) * 3)
        value = smart_render.noise(WIDTH, HEIGHT, values.tobytes())[0]
        # Read from the subject: far from the nothing the ramp reads.
        self.assertGreater(value, 0.02)

    def test_a_picture_noisy_all_over_reads_as_it_did(self):
        whole = smart_render.noise(WIDTH, HEIGHT, picture(0.1))[0]
        self.assertGreater(whole, 0.03)
        self.assertLess(whole, 0.2)


class OneOrOther(unittest.TestCase):
    def test_smart_render_switched_on_switches_safe_denoising_off(self):
        from moonray_modo import denoising
        self.assertEqual(denoising.one_or_other({'engine': 'optix', 'safe': True, 'smart': 'medium'}, 'smart'),
                         {'engine': 'optix', 'safe': False, 'smart': 'medium'})

    def test_safe_denoising_switched_on_switches_smart_render_off(self):
        from moonray_modo import denoising
        self.assertEqual(denoising.one_or_other({'engine': 'optix', 'safe': True, 'smart': 'fine'}, 'safe')['smart'], 'off')

    def test_switching_one_off_leaves_the_other(self):
        from moonray_modo import denoising
        self.assertTrue(denoising.one_or_other({'safe': True, 'smart': 'off'}, 'smart')['safe'])
        self.assertEqual(denoising.one_or_other({'safe': False, 'smart': 'draft'}, 'safe')['smart'], 'draft')

    def test_a_scene_saved_with_both_has_smart_render(self):
        from moonray_modo import denoising
        read = denoising.settings({'engine': 'optix', 'safe': True, 'smart': 'draft'})
        self.assertFalse(read['safe'])
        self.assertEqual(read['smart'], 'draft')

    def test_the_render_settings_form_keeps_them_apart(self):
        from moonray_modo import scene_settings
        fields = {entry['key']: entry for entry in scene_settings.FIELDS}
        stored = {}
        scene_settings.put(stored, fields['denoise_safe'], True)
        self.assertTrue(stored['denoising']['safe'])
        level = [key for _, key in fields['smart_render']['choices']].index('medium')
        scene_settings.put(stored, fields['smart_render'], level)
        self.assertEqual((stored['denoising']['safe'], stored['denoising']['smart']), (False, 'medium'))
        scene_settings.put(stored, fields['denoise_safe'], True)
        self.assertEqual((stored['denoising']['safe'], stored['denoising']['smart']), (True, 'off'))


if __name__ == '__main__':
    unittest.main()
