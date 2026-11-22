"""MoonRay's iridescence in MoonLightIPR: the colour table the plugin works out, and the record the session reads. No Modo."""
import math
import pathlib
import re
import struct
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
KIT = ROOT / 'kit/MoonRayForModo/python'
sys.path.insert(0, str(KIT))

from moonray_modo import iridescence, moonlightipr_materials as materials  # noqa: E402
from moonray_modo.working_space import configuration  # noqa: E402

STEPS = iridescence.IRIDESCENCE_STEPS


def near(test, a, b, places=4):
    for x, y in zip(a, b):
        test.assertAlmostEqual(x, y, places=places)


def at(table, index):
    i = round(index * (STEPS - 1))
    return table[i * 3:i * 3 + 3]


def surface(**parameters):
    notes = []
    return materials.native_surface('DwaBaseMaterial', parameters, notes.append), notes


class Colours(unittest.TestCase):
    def test_hue_and_hsv_as_moonray_has_them(self):
        self.assertEqual(iridescence.rgb_to_hue([1, 0, 0]), 0.0)
        self.assertAlmostEqual(iridescence.rgb_to_hue([0, 1, 0]), 1 / 3)
        self.assertAlmostEqual(iridescence.rgb_to_hue([0, 0, 1]), 2 / 3)
        self.assertEqual(iridescence.rgb_to_hue([.4, .4, .4]), 0.0)
        for colour in ([.9, .2, .1], [.1, .5, .8], [.3, .9, .4]):
            near(self, iridescence.hsv_to_rgb(iridescence.rgb_to_hsv(colour)), colour)
            near(self, iridescence.hsl_to_rgb(iridescence.rgb_to_hsl(colour)), colour)
        near(self, iridescence.hue_to_rgb(1 / 6), [1, 1, 0])
        near(self, iridescence.hue_to_rgb(1.0), [1, 0, 0])

    def test_one_colour_walks_the_whole_wheel(self):
        # MoonRay's defaults: primary and secondary both red, so the index runs from red round the wheel to red.
        table = iridescence.surface(lambda key, missing: {'iridescence': 1.0}.get(key, missing), print, True, False)['table']
        self.assertEqual(len(table), STEPS * 3)
        for index, expected in ((0.0, [1, 0, 0]), (1 / 3, [0, 1, 0]), (.5, [0, 1, 1]), (2 / 3, [0, 0, 1]), (1.0, [1, 0, 0])):
            near(self, at(table, index), expected, places=1)

    def test_flipped_with_one_colour_is_that_colour(self):
        near(self, iridescence.hue_colour(.37, [.2, .6, 1.0], [.2, .6, 1.0], True), [.2, .6, 1.0])

    def test_two_colours_go_round_and_come_back(self):
        blue, red = [0, 0, 1], [1, 0, 0]
        # Blue (2/3) to red (1, past the top of the wheel) over the first two thirds, then straight back to blue.
        near(self, iridescence.hue_colour(0.0, blue, red, False), blue)
        near(self, iridescence.hue_colour(1 / 3, blue, red, False), [1, 0, 1], places=3)
        near(self, iridescence.hue_colour(.5, blue, red, False), iridescence.hue_to_rgb(2 / 3 + .75 / 3), places=3)
        near(self, iridescence.hue_colour(.999, blue, red, False), blue, places=2)
        # The other way round: blue down through green (1/3) and cyan to red at 0.
        self.assertGreater(iridescence.hue_colour(.4, blue, red, True)[1], .9)

    def test_ramp_reads_as_moonray_reads_it(self):
        rainbow = iridescence.ColorRamp([0, .167, .333, .5, .667, .833, 1], [[1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 1, 1], [0, 0, 1], [1, 0, 1], [1, 0, 0]],
                                        [4] * 7, iridescence.SPACE_RGB)
        near(self, rainbow(.5), [0, 1, 1])
        near(self, rainbow(-1), [1, 0, 0])
        near(self, rainbow(2), [1, 0, 0])
        # Smooth: sin(t pi / 2) of the way from one point to the next.
        weight = math.sin(.5 * math.pi / 2)
        near(self, rainbow(.0835), [1, weight, 0], places=3)
        # Blended in HSV, the same stretch keeps full saturation.
        hsv = iridescence.ColorRamp([0, 1], [[1, 0, 0], [0, 0, 1]], [1, 1], iridescence.SPACE_HSV)
        self.assertAlmostEqual(max(hsv(.5)), 1.0, places=5)
        # The shortest way round the wheel: red to blue goes through magenta, not green.
        self.assertLess(hsv(.5)[1], 1e-5)
        # Catmull-Rom (MoonRay's takes no account of how far apart the points are) through evenly spaced points on a line
        # is the line; a monotone cubic never overshoots.
        line = iridescence.ColorRamp([0, .25, .5, .75, 1], [[v] * 3 for v in (0, .25, .5, .75, 1)], [5] * 5, iridescence.SPACE_RGB)
        near(self, line(.375), [.375] * 3)
        steps = iridescence.ColorRamp([0, .4, .6, 1], [[0] * 3, [0] * 3, [1] * 3, [1] * 3], [6] * 4, iridescence.SPACE_RGB)
        self.assertTrue(all(0 <= steps(i / 100)[0] <= 1 for i in range(101)))
        # Points out of order are sorted, as MoonRay sorts them.
        unsorted = iridescence.ColorRamp([1, 0], [[0, 0, 1], [1, 0, 0]], [1, 1], iridescence.SPACE_RGB)
        near(self, unsorted(.25), [.75, 0, .25])

    def test_colours_are_given_in_the_working_space(self):
        # MoonRay is given its Rgb attributes in ACEScg when that is the working space (shader_library.emit), and the
        # hue wheel is read from them there; the ramp's colours it is given as they are.
        parameters = {'iridescence': 1.0, 'iridescence_primary_color': [1, 0, 0], 'iridescence_secondary_color': [0, 0, 1]}
        get = lambda key, missing: parameters.get(key, missing)  # noqa: E731
        plain = iridescence.surface(get, print, True, False)['table']
        with configuration({'working_space': 'acescg'}):
            working = iridescence.surface(get, print, True, False)['table']
        self.assertNotEqual(plain[:3], working[:3])


class Surfaces(unittest.TestCase):
    def test_none_without_its_lobe(self):
        self.assertIsNone(surface(iridescence=0.0)[0]['_iridescence'])
        self.assertIsNone(surface(iridescence=1.0, show_specular=False)[0]['_iridescence'])
        self.assertIsNone(surface(iridescence=1.0, iridescence_apply_to=1)[0]['_iridescence'])
        coat = surface(iridescence=1.0, iridescence_apply_to=1, show_clearcoat=True)[0]['_iridescence']
        self.assertEqual(coat['apply'], iridescence.APPLY_COAT)
        found, notes = surface(iridescence=.6, iridescence_exponent=2.0, iridescence_thickness=3.0, iridescence_at_0_incidence=.25)
        shimmer = found['_iridescence']
        self.assertEqual((shimmer['apply'], shimmer['strength'], shimmer['exponent'], shimmer['thickness'], shimmer['at0'], shimmer['at90']),
                         (iridescence.APPLY_SPECULAR, .6, 2.0, 3.0, .25, 1.0))
        self.assertNotIn('iridescence', notes)

    def test_other_dwa_materials_and_toon(self):
        notes = []
        metal = materials.native_surface('DwaMetalMaterial', {'iridescence': 1.0}, notes.append)
        self.assertIsNotNone(metal['_iridescence'])
        moist = materials.native_surface('DwaSkinMaterial', {'iridescence': 1.0, 'iridescence_apply_to': 1, 'show_moisture': True}, notes.append)
        self.assertEqual(moist['_iridescence']['apply'], iridescence.APPLY_COAT)
        toon = materials.native_surface('DwaToonMaterial', {'iridescence': 1.0, 'specular_model': 2}, notes.append)
        self.assertIsNone(toon['_iridescence'])
        self.assertIn('iridescence on a toon highlight', notes)

    def test_record(self):
        compiler = materials.Compiler()
        material = {'shader': 'DwaBaseMaterial', 'color': [.5] * 3, 'raw_color': [.5] * 3, 'roughness': .3,
                    'native_shader': 'DwaBaseMaterial', 'native_parameters': {'iridescence': .75, 'iridescence_apply_to': 1, 'show_clearcoat': True}}
        record = compiler.material(material, 'shiny')
        base = struct.calcsize('<46f4I')
        flags = struct.unpack_from('<I', record, 46 * 4)[0]
        self.assertTrue(flags & materials.MATERIAL_IRIDESCENT)
        self.assertEqual(len(record), base + 4 + 5 * 4 + STEPS * 12)
        apply, strength = struct.unpack_from('<If', record, base)
        self.assertEqual((apply, strength), (1, .75))
        plain = compiler.material(dict(material, native_parameters={}), 'plain')
        self.assertEqual(len(plain), base)
        self.assertFalse(struct.unpack_from('<I', plain, 46 * 4)[0] & materials.MATERIAL_IRIDESCENT)


class CoatBending(unittest.TestCase):
    def material(self, **parameters):
        albedo = [.06, .06, .07]
        row = {'name': 'c', 'base_layer_id': 'c', 'shader': 'DwaBaseMaterial', 'color': albedo, 'raw_color': albedo, 'roughness': .25,
               'layer_opacity': 1.0, 'layer_blend': 'normal', 'material_groups': [], 'layers': []}
        record = materials.Compiler().material({'material_stack': [dict(row, native_shader='DwaBaseMaterial', native_parameters=dict(
            albedo=albedo, show_clearcoat=True, **parameters))]}, 'coat')
        return struct.unpack_from('<I', record, 46 * 4)[0]

    def test_a_coat_bends_unless_told_not_to(self):
        # MoonRay's clearcoat_bending is on unless switched off: only then is the coat marked straight.
        bent = self.material()
        self.assertTrue(bent & materials.MATERIAL_COAT_DIMS)
        self.assertFalse(bent & materials.MATERIAL_COAT_STRAIGHT)
        self.assertTrue(self.material(clearcoat_bending=False) & materials.MATERIAL_COAT_STRAIGHT)

    def test_in_step_with_the_gpu(self):
        shared = (ROOT / 'moonlightipr/src/device/shared.h').read_text(encoding='utf-8')
        self.assertIn('MATERIAL_COAT_STRAIGHT = 1u << 17', shared)
        self.assertEqual(materials.MATERIAL_COAT_STRAIGHT, 1 << 17)
        self.assertIn('materialFlags & (1u << 17)', (ROOT / 'moonlightipr/session/scene_loader.cpp').read_text(encoding='utf-8'))


class InStep(unittest.TestCase):
    def test_numbers_agree_with_the_gpu_and_the_session(self):
        shared = (ROOT / 'moonlightipr/src/device/shared.h').read_text(encoding='utf-8')
        self.assertIn('const unsigned IRIDESCENCE_STEPS = %d;' % STEPS, shared)
        self.assertIn('MATERIAL_IRIDESCENT = 1u << 16', shared)
        loader = (ROOT / 'moonlightipr/session/scene_loader.cpp').read_text(encoding='utf-8')
        self.assertIn('const uint32_t IRIDESCENCE_STEPS = %d;' % STEPS, loader)
        self.assertIn('materialFlags & (1u << 16)', loader)
        self.assertEqual(materials.MATERIAL_IRIDESCENT, 1 << 16)

    def test_every_set_of_features_has_its_kernel(self):
        shared = (ROOT / 'moonlightipr/src/device/shared.h').read_text(encoding='utf-8')
        everything = int(re.search(r'FEATURE_ALL = (\d+)', shared).group(1))
        self.assertEqual(everything, 127)
        variants = (ROOT / 'tools/compile_moonlightipr_variants.py').read_text(encoding='utf-8')
        self.assertEqual(int(re.search(r'^ALL = (\d+)', variants, re.M).group(1)), everything + 1)


if __name__ == '__main__':
    unittest.main()
