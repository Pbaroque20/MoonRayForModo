"""MoonRay's time per pixel as an output, and the final EXR's compression. No Modo or renderer launch."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from moonray_modo import buffers, options, rdla, scene_settings
from test_production import scene


class TimePerPixelTests(unittest.TestCase):
    def test_an_output_like_the_others(self):
        self.assertEqual(options.AOVS['time_per_pixel'][1], {'result': 5})
        value = scene()
        value['aovs'] = ['time_per_pixel']
        text = rdla.scene_text(value, output_file='final.exr')
        block = text[text.index('RenderOutput("/modo/aov/time_per_pixel")'):]
        block = block[:block.index('}')]
        self.assertIn('["result"] = 5', block)
        self.assertIn('["channel_name"] = "time_per_pixel"', block)
        self.assertIn('aov_time_per_pixel', [f['key'] if isinstance(f, dict) else f[0] for f in scene_settings.FIELDS])

    def test_shown_by_the_average_pixel(self):
        args = buffers.conversion('time_per_pixel', 'in.exr', 'out.png')
        self.assertIn('{TOP.AVGCOLOR}', args)
        self.assertEqual(args[args.index('--ch') + 1], '0,0,0')


class CompressionTests(unittest.TestCase):
    def text(self, **extra):
        value = scene()
        value.update(extra)
        return rdla.scene_text(value, output_file='final.exr')

    def compressions(self, text):
        return sorted({line.strip() for line in text.splitlines() if '"compression"' in line or 'dwa' in line})

    def test_zip_unless_chosen(self):
        self.assertEqual(self.compressions(self.text()), ['["compression"] = 1,'])

    def test_chosen_for_every_output_of_the_exr(self):
        text = self.text(exr={'compression': 4, 'dwa_level': 85.0}, aovs=['depth'])
        self.assertEqual(self.compressions(text), ['["compression"] = 4,'])
        self.assertEqual(text.count('["compression"] = 4,'), 2)

    def test_dwa_has_its_level(self):
        self.assertIn('["exr_dwa_compression_level"] = 45,', self.text(exr={'compression': 9, 'dwa_level': 45.0}))

    def test_lossy_falls_back_to_zip_with_checkpoints(self):
        value = scene()
        value.update(exr={'compression': 8, 'dwa_level': 45.0}, _recovery={'file': 'r.exr', 'resume': False, 'minutes': 1.0, 'guides': {}})
        text = rdla.scene_text(value, output_file='final.exr')
        self.assertNotIn('["compression"] = 8,', text)
        self.assertTrue(any('lossy' in w for w in value['warnings']))

    def test_unknown_refused(self):
        with self.assertRaisesRegex(ValueError, 'Unknown EXR compression'):
            self.text(exr={'compression': 42})

    def test_setting_in_the_form(self):
        keys = [f['key'] if isinstance(f, dict) else f[0] for f in scene_settings.FIELDS]
        self.assertIn('exr_compression', keys)
        self.assertEqual(scene_settings.complete({})['exr'], {'compression': 1, 'dwa_level': 85.0})


if __name__ == '__main__':
    unittest.main()
