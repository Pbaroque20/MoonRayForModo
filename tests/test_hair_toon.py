"""MoonLightIPR's reading of MoonRay's HairToonMaterial: the hair colour under up to three toon highlights, each a
surface's (Toon_Surface) or one off the fibre (Toon_Hair). No Modo or renderer launch."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import moonlightipr_materials as materials


def read(parameters):
    notes = []
    return materials.native_surface('HairToonMaterial', parameters, notes.append), notes


class HairToonTests(unittest.TestCase):
    def test_default_is_the_hair_colour_under_one_surface_highlight(self):
        surface, _ = read({'hair_color': [.4, .2, .1]})
        self.assertEqual(surface['color'], [.4, .2, .1])
        toon = surface['_toon']
        self.assertFalse(toon['diffuse'])
        self.assertTrue(toon['specular'])
        self.assertEqual(toon['more'], [])
        model, roughness, plain, under, beyond = toon['kind']
        self.assertEqual((model, plain), (0.0, 1.0))
        self.assertEqual(under, .5)                 # its indirect reflections' roughness
        self.assertEqual(len(toon['shine']), materials.TOON_STEPS)

    def test_three_highlights_and_the_fibre_model(self):
        surface, _ = read({'specular_2_show': True, 'specular_3_show': True, 'specular_3_model': 3, 'specular_3_roughness': .3,
                           'specular_2_tint': [.3, 1, .3]})
        toon = surface['_toon']
        self.assertEqual(len(toon['more']), 2)
        self.assertEqual(toon['more'][0]['numbers'][4:7], [.3, 1.0, .3])
        self.assertEqual(toon['more'][1]['kind'][:2], [1.0, .3])
        # The second highlight's ramp ends lit by default: past its end it is 1.
        self.assertEqual(toon['more'][0]['kind'][4], 1.0)

    def test_no_highlight_and_no_diffuse(self):
        surface, _ = read({'specular_1_show': False, 'show_hair_diffuse': False})
        self.assertIsNone(surface['_toon'])
        self.assertEqual(surface['color'], [0.0, 0.0, 0.0])

    def test_written_for_the_session(self):
        import struct
        surface, _ = read({'specular_2_show': True})
        toon = surface['_toon']
        # What the scene file carries after the first ramp: how many follow, the diffuse ramp's end and the first's kind,
        # then each further highlight.
        self.assertEqual(len(toon['lit_beyond']) + len(toon['kind']), 8)
        self.assertEqual(len(toon['more'][0]['shine']) + len(toon['more'][0]['numbers']) + len(toon['more'][0]['kind']), materials.TOON_STEPS + 13)


if __name__ == '__main__':
    unittest.main()
