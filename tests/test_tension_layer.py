"""Modo's Tension texture (moonray_modo.tension) against the values Modo's own renders gave (probe_gui_tension_layer.py,
probe_gui_tension_angle.py): Area as the faces' area now over at rest less 1; Angle at a fold of 30, 60, 90 and 180
degrees; and the weights handed on, over the gradient's span."""
import math
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import tension  # noqa: E402


def grid(n=4):
    points = [(i / float(n) - .5, j / float(n) - .5, 0.0) for i in range(n + 1) for j in range(n + 1)]
    faces = [(i * (n + 1) + j, (i + 1) * (n + 1) + j, (i + 1) * (n + 1) + j + 1, i * (n + 1) + j + 1) for i in range(n) for j in range(n)]
    return points, faces


def folded(points, degrees):
    a = math.radians(degrees)
    return [(x * math.cos(a), y, x * math.sin(a)) if x > 0 else (x, y, z) for x, y, z in points]


class TensionArea(unittest.TestCase):
    def test_stretch_and_shrink(self):
        rest, faces = grid()
        for scale, expected in ((2, 1.0), (3, 2.0), (.5, -.5)):
            now = [(x * scale, y, z) for x, y, z in rest]
            for v in tension.values('area', rest, now, faces):
                self.assertAlmostEqual(v, expected, places=6)

    def test_shear_keeps_area(self):
        rest, faces = grid()
        now = [(x + y, y, z) for x, y, z in rest]
        self.assertTrue(all(abs(v) < 1e-9 for v in tension.values('area', rest, now, faces)))

    def test_half_stretched(self):
        rest, faces = grid()
        now = [(x * 2 if x > 0 else x, y, z) for x, y, z in rest]
        found = tension.values('area', rest, now, faces)
        self.assertAlmostEqual(found[2 * 5 + 2], 0.5)  # on the line between: two faces of each
        self.assertAlmostEqual(found[1 * 5 + 2], 0.0)
        self.assertAlmostEqual(found[3 * 5 + 2], 1.0)


class TensionAngle(unittest.TestCase):
    def test_folds(self):
        rest, faces = grid()
        for degrees, modo in ((30, .0975), (60, .50), (90, 1.99), (180, 4.0)):
            found = tension.values('angle', rest, folded(rest, degrees), faces)
            self.assertAlmostEqual(found[2 * 5 + 2], modo, delta=0.03 * max(1.0, modo))
            self.assertAlmostEqual(found[1 * 5 + 2], 0.0)
            self.assertAlmostEqual(found[3 * 5 + 2], 0.0, places=6)

    def test_flat_stays_zero(self):
        rest, faces = grid()
        self.assertTrue(all(v == 0.0 for v in tension.values('angle', rest, [(x * 2, y, z) for x, y, z in rest], faces)))


class Weights(unittest.TestCase):
    def test_span_and_reuse(self):
        rest, faces = grid()
        name = tension.map_name('area', -1.0, 3.0)
        scene = {'materials': {'m': {'layers': [{'vmap': name, 'tension': {'kind': 'area', 'low': -1.0, 'high': 3.0}}]}},
                 'meshes': [{'name': 'Sheet', 'material': 'm', 'vertices': [(x * 2, y, z) for x, y, z in rest], 'faces': faces,
                             tension.REST: rest}]}
        tension.apply(scene, [])
        mesh = scene['meshes'][0]
        self.assertNotIn(tension.REST, mesh)
        self.assertTrue(all(abs(v[0] - .5) < 1e-9 for v in mesh['point_attributes'][name]['values']))
        warnings = []
        tension.apply(scene, warnings)  # kept from the last read: its weights stay
        self.assertEqual(warnings, [])
        self.assertTrue(all(abs(v[0] - .5) < 1e-9 for v in mesh['point_attributes'][name]['values']))


if __name__ == '__main__':
    unittest.main()
