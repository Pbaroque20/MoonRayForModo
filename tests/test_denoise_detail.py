import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import denoising


class KeepFineDetail(unittest.TestCase):
    def steps(self, level):
        with tempfile.TemporaryDirectory() as folder:
            runtime = pathlib.Path(folder)
            for name in ('denoise.exe', 'oiiotool.exe'):
                (runtime / name).write_bytes(b'')
            return denoising.jobs(runtime, runtime / 'beauty.exr', runtime / 'result', 'optix', {'albedo': 'a.exr', 'normal': 'n.exr'}, level)

    def test_off_is_the_denoiser_alone(self):
        steps = self.steps('off')
        self.assertEqual(len(steps), 3)
        self.assertNotIn('--absdiff', ' '.join(steps[-1][1]))

    def test_some_lets_the_render_through_where_the_guides_are_fine(self):
        steps = self.steps('some')
        self.assertEqual(len(steps), 4)
        mask = steps[2][1]
        self.assertEqual(mask.count('--absdiff'), 2)
        self.assertIn('a.exr', mask)
        self.assertIn('n.exr', mask)
        self.assertTrue(str(steps[-1][2]).endswith('.denoised.exr'))

    def test_more_lets_more_through(self):
        some, more = self.steps('some')[2][1], self.steps('more')[2][1]
        self.assertLess(float(some[some.index('--max') + 2]), float(more[more.index('--max') + 2]))

    def test_the_setting_is_some_unless_said(self):
        self.assertEqual(denoising.settings({})['detail'], 'some')
        with self.assertRaises(ValueError):
            denoising.settings({'detail': 'lots'})


if __name__ == '__main__':
    unittest.main()
