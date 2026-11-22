"""The Ocean Plane's waves in Modo's viewport (ocean_viewport.py, native-modo/ocean_viewport.cpp, modo_ocean.dll's
modo_ocean_preview): the long waves are the renders' own, the points stand where the sea puts the surface, they are
sparse and bounded, and they stay put as the eye moves. No Modo; the built libraries (tools/build_ocean.py,
tools/build_modo_bridge.py)."""
import ctypes
import math
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import entities, evaluated, ocean, ocean_viewport  # noqa: E402

OCEAN = ROOT / 'build/native-avx/bin/modo_ocean.dll'
ADAPTER = ROOT / 'build/modo-bridge/MoonRayGeometry.lx'
# The Ocean Plane's own sea (its defaults, entity_catalog), at its usual tile.
PLANE = {'wind_speed': 12.0, 'wind_direction': 30.0, 'choppiness': 1.2, 'against_wind': 0.3, 'resolution': 512}


# The kit's own reader of modo_ocean.dll, before the tests stand the built one in for the kit's.
LIBRARY = ocean.library


def built():
    held = LIBRARY(OCEAN)
    return held if held is not None and hasattr(held, 'modo_ocean_preview') else None


@unittest.skipUnless(OCEAN.is_file(), 'modo_ocean.dll is not built (tools/build_ocean.py)')
class LongWaves(unittest.TestCase):
    """modo_ocean_preview against the full tile the renders read."""

    def setUp(self):
        if built() is None:
            self.skipTest('this modo_ocean.dll has no modo_ocean_preview')
        self.patch = mock.patch.object(ocean, 'library', lambda path=None: built())
        self.patch.start()
        self.folder = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.patch.stop()
        self.folder.cleanup()

    def full(self, part, moment):
        paths = [Path(self.folder.name) / name for name in ('d.pfm', 'f.pfm', 's.pfm')]
        self.assertTrue(ocean.native_tile(part, moment, *paths, path=OCEAN))
        return ocean.read_pfm(paths[0])

    def test_the_renders_long_waves(self):
        value = ocean.settings(PLANE)
        for part in ocean.cascade_values(value):
            n, values = self.full(part, 2.5)
            made = ocean_viewport.tiles(dict(PLANE, swell_height=0.0), 2.5)
            width, height, ratio, turn, preview = made[part['cascade']]
            self.assertEqual((width, height), (64, 64))
            self.assertAlmostEqual(ratio, ocean.FITTED_SIZE / part['size'])
            self.assertAlmostEqual(turn, ocean.TURNS[part['cascade']])
            step = n // width
            off = max(abs(preview[(j * width + i) * 3 + c] - values[((j * step) * n + i * step) * 3 + c])
                      for j in range(width) for i in range(width) for c in range(3))
            largest = max(abs(v) for v in values)
            if part['cascade'] < 3:
                # Every wave of the three longer tiles fits in the preview: the same sea, to a float.
                self.assertLess(off, 1e-4 * largest, part['cascade'])
            else:
                # The finest tile's ripples, under a metre, are left out: what is left is a small part of its heights.
                self.assertLess(off, 0.35 * largest)

    def test_one_tile_whole(self):
        part = ocean.settings({'cascades': False, 'resolution': 64})
        n, values = self.full(part, 1.0)
        made = ocean_viewport.tiles({'cascades': False, 'resolution': 64}, 1.0)
        self.assertEqual(len(made), 1)
        self.assertEqual(max(abs(a - b) for a, b in zip(made[0][4], values)), 0.0)

    def test_the_swell_is_one_row(self):
        made = ocean_viewport.tiles(dict(PLANE, swell_height=2.0, swell_length=150.0, swell_direction=40.0), 3.0)
        width, height, ratio, turn, row = made[0]
        self.assertEqual((width, height, turn), (ocean.SWELL_RESOLUTION, 1, 40.0))
        self.assertAlmostEqual(ratio, ocean.FITTED_SIZE / 150.0)
        swell = ocean.swell_values(ocean.settings(dict(PLANE, swell_height=2.0, swell_length=150.0, swell_direction=40.0)))[0]
        expected = ocean.swell_fields(swell, 3.0)[0][:width]
        self.assertLess(max(abs(row[3 * i + c] - expected[i][c]) for i in range(width) for c in range(3)), 1e-6)
        self.assertEqual(len(made), 5)

    def test_a_scrub_costs_milliseconds(self):
        ocean_viewport.tiles(PLANE, 0.0)
        start = time.perf_counter()
        for frame in range(1, 11):
            ocean_viewport.tiles(PLANE, frame / 24.0)
        self.assertLess((time.perf_counter() - start) / 10, 0.1)


def sample(made, u, v):
    """The sea's displacement at the plane's (u, v), read as MoonRay's ImageMap reads each tile (turned, scaled,
    repeated, bilinear between texel centres): written here apart from the adapter's."""
    total = [0.0, 0.0, 0.0]
    for width, height, ratio, turn, values in made:
        c, s = math.cos(math.radians(turn)), math.sin(math.radians(turn))
        su, sv = (u * c + v * s) * ratio, (-u * s + v * c) * ratio
        su, sv = su - math.floor(su), sv - math.floor(sv)
        x, y = su * width - 0.5, sv * height - 0.5
        fx, fy = math.floor(x), math.floor(y)
        tx, ty = x - fx, y - fy
        x0, x1, y0, y1 = int(fx) % width, (int(fx) + 1) % width, int(fy) % height, (int(fy) + 1) % height
        for k in range(3):
            def at(i, j):
                return values[(j * width + i) * 3 + k]
            total[k] += (at(x0, y0) * (1 - tx) + at(x1, y0) * tx) * (1 - ty) + (at(x0, y1) * (1 - tx) + at(x1, y1) * tx) * ty
    return total


@unittest.skipUnless(OCEAN.is_file() and ADAPTER.is_file(), 'modo_ocean.dll or the geometry adapter is not built')
class Points(unittest.TestCase):
    def setUp(self):
        if built() is None:
            self.skipTest('this modo_ocean.dll has no modo_ocean_preview')
        self.patches = [mock.patch.object(ocean, 'library', lambda path=None: built())]
        bridge = ctypes.CDLL(str(ADAPTER))
        if not hasattr(bridge, 'MR_ocean_preview_draw'):
            self.skipTest('this adapter has no MR_ocean_preview_draw')
        self.patches.append(mock.patch.object(evaluated, '_adapter', lambda: bridge))
        for patch in self.patches:
            patch.start()
        self.params = dict(PLANE, swell_height=1.5, swell_length=140.0, swell_direction=-20.0)
        self.assertTrue(ocean_viewport.ready('test-plane', self.params, 4.0))

    def tearDown(self):
        ocean_viewport.forget('test-plane')
        for patch in self.patches:
            patch.stop()

    def test_where_the_sea_puts_them(self):
        made = ocean_viewport.tiles(self.params, 4.0)
        tile, height = 60.0, 2.5
        factor = tile / ocean.FITTED_SIZE
        found = ocean_viewport.points('test-plane', (13.0, -7.0), height, tile, 1.0, 120.0)
        self.assertTrue(found)
        # How far the sea pushes the surface sideways, at most.
        push = factor * sum(max(abs(values[3 * i + c]) for i in range(width * height) for c in (0, 2))
                            for width, height, _, _, values in made)
        # Each point is a place on the plane moved by the sea: found again from the grid point it was moved from.
        for x, y, z, rise in found[::397]:
            gx, gz = None, None
            for step in (1.0, 2.0, 4.0, 8.0, 16.0):
                for cx in [step * k for k in range(math.floor((x - push) / step), math.ceil((x + push) / step) + 1)]:
                    for cz in [step * k for k in range(math.floor((z - push) / step), math.ceil((z + push) / step) + 1)]:
                        moved = sample(made, cx / tile, cz / tile)
                        if abs(cx + moved[0] * factor - x) < 1e-3 and abs(cz - moved[2] * factor - z) < 1e-3:
                            gx, gz = cx, cz
            self.assertIsNotNone(gx, (x, z))
            moved = sample(made, gx / tile, gz / tile)
            self.assertAlmostEqual(y, height + moved[1] * factor, places=3)
            self.assertAlmostEqual(rise, moved[1] * factor, places=3)

    def test_sparse_and_bounded(self):
        tile, spacing, distance = 80.0, 1.0, 250.0
        found = ocean_viewport.points('test-plane', (0.0, 0.0), 0.0, tile, spacing, distance)
        self.assertLess(len(found), ocean_viewport.MOST_POINTS)
        reach = ocean.reach(ocean.settings(self.params))
        self.assertLessEqual(max(math.hypot(x, z) for x, _, z, _ in found), distance + reach)
        # Next to the eye a point every metre; far out, every 8 m.
        near = [p for p in found if math.hypot(p[0], p[2]) < 10]
        far = [p for p in found if 150 < math.hypot(p[0], p[2]) < 200]
        self.assertGreater(len(near) / (math.pi * 10 ** 2), 0.7)
        self.assertLess(len(far) / (math.pi * (200 ** 2 - 150 ** 2)), 0.03)
        # Twice as far: a few levels more, not four times the points.
        twice = ocean_viewport.points('test-plane', (0.0, 0.0), 0.0, tile, spacing, distance * 2)
        self.assertLess(len(twice), 1.5 * len(found))
        # A cap whatever is asked.
        self.assertEqual(len(ocean_viewport.points('test-plane', (0.0, 0.0), 0.0, tile, 0.05, 5000.0, most=1000)), 1000)

    def test_they_stay_put_as_the_eye_moves(self):
        first = set(ocean_viewport.points('test-plane', (0.0, 0.0), 0.0, 80.0, 1.0, 60.0))
        moved = set(ocean_viewport.points('test-plane', (0.3, -0.2), 0.0, 80.0, 1.0, 60.0))
        # The same points where both reach: none slides with the eye.
        shared = first & moved
        self.assertGreater(len(shared), 0.9 * len(first))
        drifted = [p for p in moved - first if math.hypot(p[0], p[2]) < 40]
        self.assertEqual(drifted, [])

    def test_the_timeline_moves_them(self):
        before = ocean_viewport.points('test-plane', (0.0, 0.0), 0.0, 80.0, 2.0, 30.0)
        self.assertTrue(ocean_viewport.ready('test-plane', self.params, 5.0))
        after = ocean_viewport.points('test-plane', (0.0, 0.0), 0.0, 80.0, 2.0, 30.0)
        self.assertEqual(len(before), len(after))
        self.assertGreater(max(abs(a[1] - b[1]) for a, b in zip(before, after)), 0.05)

    def test_nothing_kept_nothing_drawn(self):
        self.assertIsNone(ocean_viewport.points('no-such-plane', (0.0, 0.0), 0.0, 80.0, 1.0, 50.0))


class InTheKit(unittest.TestCase):
    def test_the_settings(self):
        attributes = entities.catalog()['OceanPlaneGeometry']['attributes']
        self.assertIs(attributes['viewport_points']['default'], True)
        self.assertEqual(attributes['viewport_spacing']['default'], 0.5)
        self.assertEqual(attributes['viewport_distance']['default'], 250.0)
        self.assertIn('mr_viewport_points', (ROOT / 'kit/MoonRayForModo/entities.cfg').read_text(encoding='utf-8'))

    def test_drawn_in_the_world(self):
        source = (ROOT / 'kit/MoonRayForModo/lxserv/moonray_entities.py').read_text(encoding='utf-8')
        self.assertIn("world=name=='OceanPlaneGeometry'", source)
        self.assertIn('ocean_viewport.draw(stroke,self.item.Ident()', source)
        self.assertIn("native-modo/ocean_viewport.cpp", (ROOT / 'tools/build_modo_bridge.py').read_text(encoding='utf-8'))

    def test_left_out_of_the_renders(self):
        # The plane's viewport settings are not the sea's: the rendered plane is made as before.
        from moonray_modo import ocean_plane
        for key in ('viewport_points', 'viewport_spacing', 'viewport_distance'):
            self.assertNotIn(key, ocean_plane.OCEAN_KEYS)


if __name__ == '__main__':
    unittest.main()
