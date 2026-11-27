"""Surface Grids and Dots against Modo's own renders (fixtures/surface_procedurals_modo.json, from tools/
probe_cl_surface_procedurals.py through tools/check_surface_procedurals.py fixture): a plane, its UVs 0 to 1, under a
UV map and a Planar locator, each of the Grid's and Dots' types, soft and hard edges, bias and gain, UV Rotation and
the Wraps. The plugin bakes the pattern (procedurals.sample) and lays it by the kit's UV transform, the pattern moved by
procedurals.uv_offset."""
import ctypes
import json
import math
import pathlib
import sys
import unittest
from array import array

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
sys.path.insert(0, str(ROOT / 'tools'))

from moonray_modo import procedurals  # noqa: E402
import check_surface_procedurals  # noqa: E402


class SurfaceProcedurals(unittest.TestCase):
    def test_each_is_what_modo_renders(self):
        cases = json.loads((ROOT / 'tests/fixtures/surface_procedurals_modo.json').read_text())
        self.assertGreaterEqual(len(cases), 15)
        for name, case in cases.items():
            errors = []
            for x, y, value in case['samples']:
                found = check_surface_procedurals.plugin_value(case, x, y)
                # Modo's filtered picture against the exact pattern: a little apart in a soft edge.
                self.assertLess(abs(found - value), .06, '%s at %s' % (name, (x, y)))
                errors.append(abs(found - value))
            self.assertLess(sum(errors) / len(errors), .01, name)

    def test_modo_s_lines_and_dots(self):
        hard = {'kind': 'grid', 'pattern': 'square', 'width': .2, 'transition': 0.0, 'bias': .5, 'gain': .5,
                'color1': [0.0] * 3, 'color2': [1.0] * 3, 'alpha1': 1.0, 'alpha2': 1.0}
        value = lambda data, u, v: procedurals.sample(data, u, v)[0][0]
        # Square lines half way across each unit; dots on the whole numbers.
        self.assertEqual(value(hard, .5, .3), 0.0)
        self.assertEqual(value(hard, .2, .3), 1.0)
        self.assertEqual(value(dict(hard, kind='dots', width=.4), 1.0, 2.0), 0.0)
        self.assertEqual(value(dict(hard, kind='dots', width=.4), .5, .5), 1.0)
        # The colour is colour 1 to half the width, then meets colour 2 over the transition beyond it.
        soft = dict(hard, transition=.2)
        self.assertEqual(value(soft, .59, 0.0), 0.0)
        self.assertAlmostEqual(value(soft, .7, 0.0), .5)
        self.assertEqual(value(soft, .81, 0.0), 1.0)
        # The environment's Grid and Dots are the same.
        self.assertEqual(procedurals.environment_sample(soft, .7, .3), procedurals.sample(soft, .7, .3))

    def test_the_offset_turns_and_wraps_about_the_middle(self):
        self.assertIsNone(procedurals.uv_offset(0.0, [1.0, 1.0]))
        self.assertIsNone(procedurals.uv_offset(0.0, [3.0, 1.0]))
        self.assertEqual(procedurals.uv_offset(0.0, [2.0, 1.0]), [.5, 0.0])
        # The middle of the UVs, turned and scaled about 0 by the plugin and moved by the offset, stays at (0.5, 0.5)
        # (whole units apart do not show).
        for rotation, scale in ((.5, [2.0, 3.0]), (-1.2, [1.5, .5]), (math.pi / 2, [1.0, 1.0])):
            offset = procedurals.uv_offset(rotation, scale) or [0.0, 0.0]
            c, s = math.cos(rotation), math.sin(rotation)
            u, v = (.5 * c - .5 * s) * scale[0] + offset[0], (.5 * s + .5 * c) * scale[1] + offset[1]
            self.assertAlmostEqual(u % 1.0, .5)
            self.assertAlmostEqual(v % 1.0, .5)

    def test_the_adapter_bakes_modo_s_shapes_with_the_offset(self):
        held = None
        for build in sorted((ROOT / 'build').glob('modo-geometry*/MoonRayGeometry.lx'), key=lambda p: -p.stat().st_mtime):
            try:
                library = ctypes.CDLL(str(build))
            except OSError:
                continue
            if hasattr(library, 'MR_procedural_bake'):
                held = library
                break
        if held is None:
            self.skipTest('geometry adapter with MR_procedural_bake not built (tools/build_modo_bridge.py)')
        resolution = 64
        for kind, shape in (('grid', 'line'), ('grid', 'square'), ('grid', 'triangle'), ('grid', 'hexagon'), ('dots', 'square'), ('dots', 'hexagon')):
            data = {'kind': kind, 'pattern': shape, 'width': .3, 'transition': .2, 'bias': .4, 'gain': .6,
                    'color1': [.9, .2, .1], 'color2': [.1, .3, .8], 'alpha1': 1.0, 'alpha2': .5, 'offset': [.3, .7]}
            settings = procedurals.native_settings(data)
            self.assertEqual(len(settings), 33)
            rgb, alpha = array('f', bytes(12 * resolution * resolution)), array('f', bytes(12 * resolution * resolution))
            call = held.MR_procedural_bake
            call.argtypes = [ctypes.POINTER(ctypes.c_double), ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
            call.restype = ctypes.c_int
            if call((ctypes.c_double * len(settings))(*settings), len(settings), resolution, rgb.buffer_info()[0], alpha.buffer_info()[0], 0):
                self.skipTest('geometry adapter built before the bake took an offset')
            for y in range(0, resolution, 7):
                for x in range(0, resolution, 5):
                    colour, a = procedurals.sample(data, (x + .5) / resolution, (y + .5) / resolution)
                    at = 3 * (y * resolution + x)
                    for k in range(3):
                        self.assertAlmostEqual(rgb[at + k], colour[k], places=5)
                    self.assertAlmostEqual(alpha[at], a, places=5)


if __name__ == '__main__':
    unittest.main()
