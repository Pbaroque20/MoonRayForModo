"""MoonLightIPR lays a light's picture across it as MoonRay does (form W): a MoonRay light's texture repeats, mirroring,
rotation, translation, coverage and border colour reach it (entities.texture_transform, moonlightipr_scene.
picture_transform), as the transform XPU2 builds (xpu2/interactive/light_image_build.h) and the kernel reads
(lightPicture). A report: a RectLight's Texture Reps U and V did nothing in MoonLightIPR."""
import math
import struct
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
for name in ('modo', 'lx', 'lxifc', 'lxu'):
    sys.modules.setdefault(name, types.ModuleType(name))

from moonray_modo import entities, moonlightipr_scene  # noqa: E402


def xpu2(rotation, translation, coverage, reps_u, reps_v):
    """XPU2's build of the transform (light_image_build.h), its 3 x 3 row-vector matrix."""
    tx, ty = -translation[0], -translation[1]
    sx, sy = reps_u / coverage[0], reps_v / coverage[1]
    theta = rotation * math.pi / 180.0
    c, s = math.cos(theta), math.sin(theta)
    return [c * sx, s * sx, 0.0, -s * sy, c * sy, 0.0, c * sx * tx - s * sy * ty, s * sx * tx + c * sy * ty, 1.0]


def lookup(packed, u, v):
    """The kernel's lightPicture in MoonRay's (u, v): where in one repeat of the picture it reads, or 'border'."""
    m, reps_u, reps_v, flags = packed[:6], packed[6], packed[7], packed[11]
    if not flags & 1:
        return u, v
    tu, tv = u * m[0] + v * m[2] + m[4], u * m[1] + v * m[3] + m[5]
    if tu < 0 or tu > reps_u or tv < 0 or tv > reps_v:
        return 'border'
    fu, fv = math.floor(tu), math.floor(tv)
    tu, tv = tu - fu, tv - fv
    if flags & 2 and int(fu) & 1:
        tu = 1 - tu
    if flags & 4 and int(fv) & 1:
        tv = 1 - tv
    return tu, tv


class FromTheLight(unittest.TestCase):
    def entity(self, **parameters):
        return {'class': 'RectLight', 'parameters': parameters}

    def test_left_alone_it_is_moonrays_defaults(self):
        settings = entities.texture_transform(self.entity())
        self.assertEqual(settings, {'rotation': 0.0, 'translation': [0.0, 0.0], 'coverage': [1.0, 1.0], 'reps_u': 1.0, 'reps_v': 1.0,
                                    'mirror_u': False, 'mirror_v': False, 'border': [1.0, 1.0, 1.0]})
        packed = moonlightipr_scene.picture_transform({'texture_transform': settings})
        self.assertEqual(packed[11], 0, 'read once across the light, as before')

    def test_its_settings_are_read(self):
        settings = entities.texture_transform(self.entity(texture_reps_u=3.0, texture_reps_v=2.0, texture_mirror_u=True,
                                                          texture_rotation=30.0, texture_translation=[0.25, 0.5],
                                                          texture_coverage=[0.5, 1.0], texture_border_color=[0.1, 0.2, 0.3]))
        self.assertEqual((settings['reps_u'], settings['reps_v'], settings['mirror_u'], settings['mirror_v']), (3.0, 2.0, True, False))
        self.assertEqual((settings['rotation'], settings['translation'], settings['coverage'], settings['border']),
                         (30.0, [0.25, 0.5], [0.5, 1.0], [0.1, 0.2, 0.3]))


class Packed(unittest.TestCase):
    def test_the_matrix_is_xpu2s(self):
        for rotation, translation, coverage, reps in ((0, (0, 0), (1, 1), (2, 3)), (30, (0.25, -0.5), (0.5, 2), (1, 1)), (-90, (0, 0.1), (1, 1), (4, 1))):
            packed = moonlightipr_scene.picture_transform({'texture_transform': {
                'rotation': rotation, 'translation': list(translation), 'coverage': list(coverage), 'reps_u': reps[0], 'reps_v': reps[1]}})
            m = xpu2(rotation, translation, coverage, *reps)
            for got, wanted in zip(packed[:6], (m[0], m[1], m[3], m[4], m[6], m[7])):
                self.assertAlmostEqual(got, wanted, places=6)
            self.assertEqual(packed[11] & 1, 1)

    def test_two_repeats_read_the_picture_twice_and_mirror_turns_the_second(self):
        packed = moonlightipr_scene.picture_transform({'texture_transform': {'reps_u': 2.0, 'reps_v': 1.0, 'mirror_u': True}})
        self.assertEqual(packed[6:8], [2.0, 1.0])
        left, right = lookup(packed, 0.2, 0.5), lookup(packed, 0.7, 0.5)
        self.assertAlmostEqual(left[0], 0.4)
        self.assertAlmostEqual(right[0], 1 - 0.4, msg='the second repeat mirrored')
        plain = moonlightipr_scene.picture_transform({'texture_transform': {'reps_u': 2.0}})
        self.assertAlmostEqual(lookup(plain, 0.7, 0.5)[0], 0.4)

    def test_past_the_coverage_is_the_border(self):
        packed = moonlightipr_scene.picture_transform({'texture_transform': {'coverage': [0.5, 1.0], 'border': [0.0, 0.0, 0.0]}})
        self.assertEqual(lookup(packed, 0.75, 0.5), 'border')
        self.assertAlmostEqual(lookup(packed, 0.25, 0.5)[0], 0.5)
        self.assertEqual(packed[8:11], [0.0, 0.0, 0.0])


class Scene(unittest.TestCase):
    def test_each_light_record_carries_it(self):
        light = {'kind': 'RectLight', 'name': 'card', 'identity': 'a', 'color': [1.0, 1.0, 1.0], 'intensity': 1.0,
                 'matrix': [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0], 'filters': [], 'width': 1.0, 'height': 1.0,
                 'texture': 'card.png', 'texture_transform': {'reps_u': 2.0, 'reps_v': 3.0}}
        compiler = mock.Mock()
        compiler.texture.return_value = 4
        distant, local = moonlightipr_scene.lights({'lights': [light]}, [], compiler=compiler)
        record = local[0]
        head = struct.calcsize('<I20fiI')
        self.assertEqual(struct.unpack_from('<I20fiI', record)[21], 4)
        block = struct.unpack_from('<11fI', record, head)
        self.assertEqual(block[6:8], (2.0, 3.0))
        self.assertEqual(block[11] & 1, 1)


if __name__ == '__main__':
    unittest.main()
