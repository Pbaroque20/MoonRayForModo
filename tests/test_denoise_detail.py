import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import denoising


class KeepFineDetail(unittest.TestCase):
    def steps(self, level, fine=True):
        with tempfile.TemporaryDirectory() as folder:
            runtime = pathlib.Path(folder)
            for name in ('denoise.exe', 'oiiotool.exe'):
                (runtime / name).write_bytes(b'')
            guides = {'albedo': 'a.exr', 'normal': 'n.exr'}
            if fine:
                guides['fine'] = 'f.exr'
            return denoising.jobs(runtime, runtime / 'beauty.exr', runtime / 'result', 'optix', guides, level)

    def test_off_is_the_denoiser_alone(self):
        steps = self.steps('off')
        self.assertEqual(len(steps), 3)
        self.assertNotIn('f.exr', ' '.join(steps[-1][1]))

    def test_some_lets_the_render_through_where_the_fibres_are(self):
        steps = self.steps('some')
        self.assertEqual(len(steps), 4)
        mask = steps[2][1]
        self.assertIn('f.exr', mask)
        self.assertTrue(str(steps[-1][2]).endswith('.denoised.exr'))

    def test_the_guides_own_detail_lets_nothing_through(self):
        # On a textured or bumpy surface the guides change at every pixel: the render's noise came back there.
        for level in ('some', 'more'):
            steps = self.steps(level)
            self.assertNotIn('a.exr', steps[2][1])
            self.assertNotIn('n.exr', steps[2][1])
            self.assertNotIn('--absdiff', ' '.join(steps[2][1]))

    def test_without_fibres_it_is_the_denoiser_alone(self):
        steps = self.steps('more', fine=False)
        self.assertEqual(len(steps), 3)

    def test_more_lets_more_through(self):
        some, more = self.steps('some')[2][1], self.steps('more')[2][1]
        self.assertLess(float(some[some.index('--mulc') + 1]), float(more[more.index('--mulc') + 1]))

    def test_the_setting_is_some_unless_said(self):
        self.assertEqual(denoising.settings({})['detail'], 'some')
        with self.assertRaises(ValueError):
            denoising.settings({'detail': 'lots'})


if __name__ == '__main__':
    unittest.main()
