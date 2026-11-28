"""Modo's Photometric lights by their IES profiles (ies_lights): reading an IES file, the profile toward a direction as
Modo's renderer reads it (nadir along the light's -Z, C0 toward its +Y, the C planes folded about C0-C180), the cube of
cookie projectors MoonRay is given, and MoonLightIPR's records of them. No Modo or renderer launch."""
import math
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
for _name in ('modo', 'lx', 'lxifc', 'lxu'):
    sys.modules.setdefault(_name, types.ModuleType(_name))
from moonray_modo import ies_lights as ies  # noqa: E402

IDENTITY = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]


def ies_text(vertical, horizontal, rows, multiplier=1.0, tilt='NONE'):
    lines = ['IESNA:LM-63-2002', '[TEST] test', 'TILT=' + tilt]
    if tilt == 'INCLUDE':
        lines += ['1', '3', '0 45 90', '1 .9 .8']
    lines += ['1 1000 %g %d %d 1 2 0 0 0' % (multiplier, len(vertical), len(horizontal)), '1 1 100',
              ' '.join('%g' % v for v in vertical), ' '.join('%g' % h for h in horizontal)]
    lines += [' '.join('%g' % c for c in row) for row in rows]
    return '\n'.join(lines) + '\n'


DOWN = ies_text([0, 30, 40, 45, 90], [0], [[100, 80, 20, 0, 0]])
# All round: C0 200, C90 100, C180 50, C270 10 at the nadir and 30 degrees.
ROUND = ies_text([0, 30, 90], [0, 90, 180, 270, 360], [[200, 200, 0], [100, 100, 0], [50, 50, 0], [10, 10, 0], [200, 200, 0]])


class Parse(unittest.TestCase):
    def test_reads_the_angles_and_candela_multiplied(self):
        profile = ies.parse(ies_text([0, 90], [0, 90], [[10, 5], [20, 0]], multiplier=2.0))
        self.assertEqual(profile['vertical'], [0, 90])
        self.assertEqual(profile['horizontal'], [0, 90])
        self.assertEqual(profile['candela'], [[20, 10], [40, 0]])

    def test_a_tilt_table_is_passed_over(self):
        profile = ies.parse(ies_text([0, 90], [0], [[10, 5]], tilt='INCLUDE'))
        self.assertEqual(profile['candela'], [[10, 5]])

    def test_not_an_ies_file_is_refused(self):
        with self.assertRaises(ValueError):
            ies.parse('nothing here')
        with self.assertRaises(ValueError):
            ies.parse('TILT=NONE\n1 2 3\n')


class Profile(unittest.TestCase):
    def test_divided_by_the_largest_and_read_in_straight_lines(self):
        profile = ies.parse(DOWN)
        self.assertAlmostEqual(ies.relative(profile, 0, 0), 1.0)
        self.assertAlmostEqual(ies.relative(profile, 15, 0), .9)
        self.assertAlmostEqual(ies.relative(profile, 35, 123), .5)
        self.assertEqual(ies.relative(profile, 120, 0), 0.0)

    def test_planes_folded_about_c0_c180_as_modo_reads_a_whole_round(self):
        profile = ies.parse(ROUND)
        self.assertAlmostEqual(ies.relative(profile, 0, 0), 1.0)
        self.assertAlmostEqual(ies.relative(profile, 0, 90), .5)
        self.assertAlmostEqual(ies.relative(profile, 0, 180), .25)
        # Toward C270 Modo reads C90 (folded), not the file's C270.
        v, h = ies.angles((-1.0, 0.0, -1.0))
        self.assertAlmostEqual(h, 90.0)

    def test_a_quadrant_is_mirrored_into_the_others(self):
        profile = ies.parse(ies_text([0, 90], [0, 90], [[100, 0], [50, 0]]))
        self.assertAlmostEqual(ies.relative(profile, 0, 120), ies.relative(profile, 0, 60))
        self.assertAlmostEqual(ies.relative(profile, 0, 180), 1.0)

    def test_angles_nadir_along_minus_z_and_c0_toward_plus_y(self):
        self.assertAlmostEqual(ies.angles((0, 0, -1))[0], 0.0)
        self.assertAlmostEqual(ies.angles((0, 0, 1))[0], 180.0)
        self.assertEqual([round(a, 6) for a in ies.angles((0, 1, 0))], [90.0, 0.0])
        self.assertEqual([round(a, 6) for a in ies.angles((0, -1, 0))], [90.0, 180.0])
        self.assertEqual([round(a, 6) for a in ies.angles((1, 0, 0))], [90.0, 90.0])
        self.assertEqual([round(a, 6) for a in ies.angles((-1, 0, 0))], [90.0, 90.0])


class Faces(unittest.TestCase):
    def test_each_face_looks_along_its_own_axis_and_is_a_turn(self):
        looks = {'nadir': (0, 0, -1), 'zenith': (0, 0, 1), 'plus_x': (1, 0, 0), 'minus_x': (-1, 0, 0), 'plus_y': (0, 1, 0), 'minus_y': (0, -1, 0)}
        for name, axes in ies.FACES:
            self.assertEqual(tuple(-v for v in axes[2]), looks[name])
            x, y, z = axes
            cross = (x[1] * y[2] - x[2] * y[1], x[2] * y[0] - x[0] * y[2], x[0] * y[1] - x[1] * y[0])
            self.assertEqual(cross, tuple(z), name)

    def test_a_face_picture_is_the_profile_toward_each_texel_top_row_up(self):
        profile = ies.parse(ROUND)
        values = ies.face_values(profile, dict(ies.FACES)['nadir'], size=8)
        # The nadir face's top row looks toward the light's +Y (C0, the brightest), its bottom row toward -Y (C180).
        top, bottom = sum(values[:8]), sum(values[-8:])
        self.assertGreater(top, bottom)

    def test_a_downlight_lights_the_nadir_face_alone(self):
        names = [name for name, _, _ in ies.faces(ies.parse(DOWN), size=16)]
        self.assertEqual(names, ['nadir'])
        up = ies.parse(ies_text([0, 90, 135, 180], [0], [[0, 0, 50, 100]]))
        self.assertIn('zenith', [name for name, _, _ in ies.faces(up, size=16)])
        self.assertNotIn('nadir', [name for name, _, _ in ies.faces(up, size=16)])

    def test_a_projector_turns_with_the_light_without_its_size(self):
        light = [2.0, 0, 0, 0, 0, 0, -2.0, 0, 0, 2.0, 0, 0, 1.0, 2.0, 3.0, 1.0]
        placed = ies.projector_matrix(light, dict(ies.FACES)['nadir'])
        self.assertEqual([round(v, 9) for v in placed], [1.0, 0, 0, 0, 0, 0, -1.0, 0, 0, 1.0, 0, 0, 1.0, 2.0, 3.0, 1.0])


class Emit(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        ies._HELD.clear()

    def written(self, target, values, width, height):
        Path(target).write_text('%d %d %d' % (width, height, len(values)))

    def profile(self, text):
        path = self.folder / 'lamp.ies'
        path.write_text(text)
        return str(path)

    def test_one_face_is_one_cookie_and_more_are_added_by_a_combine(self):
        with mock.patch('moonray_modo.textures.cache_root', lambda: self.folder), mock.patch('moonray_modo.light_images.write_picture', self.written):
            lines = []
            refs = ies.emit({'ies': self.profile(DOWN), 'matrix': IDENTITY}, '/modo/light/a', lines)
            self.assertEqual(refs, ['CookieLightFilter_v2("/modo/light/a/ies/nadir")'])
            self.assertTrue(any('"projector_focal"] = 12' in line for line in lines))
            self.assertTrue(any('"projector_film_width_aperture"] = 24' in line for line in lines))
            ies._HELD.clear()
            lines = []
            refs = ies.emit({'ies': self.profile(ROUND.replace('200 200 0', '200 200 90')), 'matrix': IDENTITY}, '/modo/light/b', lines)
            self.assertEqual(refs, ['CombineLightFilter("/modo/light/b/ies")'])
            self.assertTrue(any('["mode"] = 3' in line for line in lines))
            # Made once: the faces are found again in the cache.
            ies._HELD.clear()
            again = []
            self.assertEqual(ies.emit({'ies': self.profile(ROUND.replace('200 200 0', '200 200 90')), 'matrix': IDENTITY}, '/modo/light/b', again), refs)

    def test_moonlightipr_records_turn_the_projector_y_round(self):
        with mock.patch('moonray_modo.textures.cache_root', lambda: self.folder), mock.patch('moonray_modo.light_images.write_picture', self.written):
            made = ies.records({'ies': self.profile(DOWN), 'matrix': IDENTITY})
        self.assertEqual(len(made), 1)
        self.assertEqual(made[0]['kind'], 'cookie')
        # rows give (across, up, divisor); the projector's own y turned round: up runs the other way.
        self.assertLess(made[0]['rows'][1][1], 0)

    def test_a_missing_file_is_refused(self):
        with self.assertRaises(ValueError):
            ies.profile_faces(str(self.folder / 'none.ies'))


class Wiring(unittest.TestCase):
    def test_a_photometric_light_makes_moonray_scalar(self):
        core = types.ModuleType('PySide2.QtCore')
        core.QObject, core.Signal, core.QTimer = object, (lambda *args: None), object
        package = types.ModuleType('PySide2')
        package.QtCore = core
        try:
            with mock.patch.dict(sys.modules, {'PySide2': package, 'PySide2.QtCore': core}):
                from moonray_modo import render
        except (ImportError, AttributeError) as exc:
            self.skipTest('render needs Qt here: %s' % exc)
        self.assertEqual(render.scalar_only({'lights': [{'kind': 'SphereLight', 'ies': 'C:/a.ies'}]}), render.COOKIE)
        self.assertIsNone(render.scalar_only({'lights': [{'kind': 'SphereLight'}]}))

    def test_moonlightipr_takes_the_profile_with_the_lights_filters(self):
        from moonray_modo import moonlightipr_scene
        with mock.patch('moonray_modo.ies_lights.records', lambda light: [{'kind': 'cookie', 'marked': True}]):
            self.assertEqual(moonlightipr_scene.ies_records({'ies': 'C:/a.ies'}, []), [{'kind': 'cookie', 'marked': True}])
        self.assertEqual(moonlightipr_scene.ies_records({}, []), [])
        warnings = []
        self.assertEqual(moonlightipr_scene.ies_records({'ies': 'C:/missing/none.ies', 'name': 'P', 'matrix': IDENTITY}, warnings), [])
        self.assertIn('without its IES profile', warnings[0])


if __name__ == '__main__':
    unittest.main()
