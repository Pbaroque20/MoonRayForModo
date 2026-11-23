"""Seas on Modo meshes and on an Ocean Plane wearing a Modo material, in the viewport (ocean_meshes.py,
ocean_viewport.py's surfaces, native-modo/ocean_viewport.cpp's MR_ocean_preview_mesh / _level / _surface_points): an
Ocean Plane's level gives the points its own sea gives, a flat mesh is drawn on its own faces only and through its own
UVs, turned with its item, and a shape that is not flat is not drawn. No Modo; the built libraries (tools/build_ocean.py,
tools/build_modo_bridge.py)."""
import ctypes
import math
import sys
import unittest
from array import array
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import evaluated, ocean, ocean_plane, ocean_viewport  # noqa: E402

OCEAN = ROOT / 'build/native-avx/bin/modo_ocean.dll'
ADAPTER = ROOT / 'build/modo-bridge/MoonRayGeometry.lx'
SEA = {'wind_speed': 12.0, 'wind_direction': 30.0, 'choppiness': 1.2, 'against_wind': 0.3, 'resolution': 512,
       'swell_height': 1.5, 'swell_length': 140.0, 'swell_direction': -20.0}
LIBRARY = ocean.library
IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def built():
    held = LIBRARY(OCEAN)
    return held if held is not None and hasattr(held, 'modo_ocean_preview') else None


def grid(width, depth, rows, columns, height=0.0, uv=None):
    """A flat mesh facing up (+Y), centred on the origin: (points, counts, corners, uvs), the arrays the adapter reads.
    uv(x, z) gives a corner's UV (by default, 0 to 1 across the mesh)."""
    uv = uv or (lambda x, z: ((x + width / 2) / width, (z + depth / 2) / depth))
    points = array('f')
    for j in range(rows + 1):
        for i in range(columns + 1):
            points.extend((-width / 2 + width * i / columns, height, -depth / 2 + depth * j / rows))
    counts, corners, uvs = array('i'), array('i'), array('f')
    for j in range(rows):
        for i in range(columns):
            # Wound to face up: seen from above (+Y), x to the right and z toward the eye, counter-clockwise.
            quad = [j * (columns + 1) + i, (j + 1) * (columns + 1) + i, (j + 1) * (columns + 1) + i + 1, j * (columns + 1) + i + 1]
            counts.append(4)
            corners.extend(quad)
            for corner in quad:
                uvs.extend(uv(points[3 * corner], points[3 * corner + 2]))
    return points, counts, corners, uvs


def nearest(found, point):
    return min(math.dist(point[:3], other[:3]) for other in found)


@unittest.skipUnless(OCEAN.is_file() and ADAPTER.is_file(), 'modo_ocean.dll or the geometry adapter is not built')
class Surfaces(unittest.TestCase):
    def setUp(self):
        if built() is None:
            self.skipTest('this modo_ocean.dll has no modo_ocean_preview')
        bridge = ctypes.CDLL(str(ADAPTER))
        if not hasattr(bridge, 'MR_ocean_preview_surface_draw'):
            self.skipTest('this adapter draws no sea on a surface of its own')
        self.patches = [mock.patch.object(ocean, 'library', lambda path=None: built()),
                        mock.patch.object(evaluated, '_adapter', lambda: bridge)]
        for patch in self.patches:
            patch.start()
        self.assertTrue(ocean_viewport.ready('test-sea', SEA, 4.0))
        self.names = []

    def tearDown(self):
        for name in self.names:
            ocean_viewport.forget_surface(name)
        ocean_viewport.forget('test-sea')
        for patch in self.patches:
            patch.stop()

    def mesh(self, name, made, matrix=IDENTITY, wanted=None):
        self.names.append(name)
        return ocean_viewport.mesh_surface(name, *made, wanted, matrix)

    def test_a_level_is_the_ocean_planes_own_sea(self):
        # An Ocean Plane wearing a Modo material whose sea is its own settings' gives the points its own sea gives.
        tile, height = 60.0, 2.5
        self.names.append('test-level')
        self.assertTrue(ocean_viewport.level('test-level', height, tile))
        own = ocean_viewport.points('test-sea', (13.0, -7.0), height, tile, 1.0, 80.0)
        laid = ocean_viewport.surface_points('test-sea', 'test-level', (1.0, 1.0), tile / ocean.FITTED_SIZE, (13.0, 40.0, -7.0), 1.0, 80.0)
        self.assertTrue(own)
        self.assertEqual(len(laid), len(own))
        for point in laid[::211]:
            self.assertLess(nearest(own, point), 1e-3)

    def test_a_mesh_is_drawn_on_its_faces_only(self):
        tile = 20.0
        # A 30 x 18 m plane at 1 m, its UVs the world's over tile: as the level would lay them.
        made = grid(30.0, 18.0, 3, 5, 1.0, uv=lambda x, z: (x / tile, z / tile))
        code, facts = self.mesh('test-mesh', made)
        self.assertEqual(code, 0)
        self.assertAlmostEqual(facts['area'], 540.0, places=3)
        self.assertAlmostEqual(facts['metres'][0], tile, places=3)
        self.assertAlmostEqual(facts['metres'][1], tile, places=3)
        for got, want in zip(facts['normal'], (0.0, 1.0, 0.0)):
            self.assertAlmostEqual(got, want, places=6)
        self.assertAlmostEqual(facts['extent'][0], 30.0, places=3)
        self.assertAlmostEqual(facts['extent'][1], 18.0, places=3)
        factor = tile / ocean.FITTED_SIZE
        found = ocean_viewport.surface_points('test-sea', 'test-mesh', (1.0, 1.0), factor, (2.0, 30.0, 3.0), 0.5, 100.0)
        self.assertTrue(found)
        reach = ocean.reach(ocean.settings(SEA)) * factor
        for x, y, z, rise in found:
            self.assertLessEqual(abs(x), 15.0 + reach)
            self.assertLessEqual(abs(z), 9.0 + reach)
            self.assertAlmostEqual(y, 1.0 + rise, places=3)
        # The same places the level at 1 m puts its points, where the mesh is.
        self.names.append('test-level-1')
        self.assertTrue(ocean_viewport.level('test-level-1', 1.0, tile))
        level = ocean_viewport.surface_points('test-sea', 'test-level-1', (1.0, 1.0), factor, (2.0, 30.0, 3.0), 0.5, 100.0)
        self.assertGreater(len(level), len(found))
        for point in found[::97]:
            self.assertLess(nearest(level, point), 1e-3)

    def test_turned_with_its_item(self):
        made = grid(12.0, 8.0, 2, 2)
        self.assertEqual(self.mesh('test-flat', made)[0], 0)
        # The same mesh stood up facing +Z (turned 90 degrees about X: y -> z, z -> -y), and 5 m along X.
        turned = [1, 0, 0, 0, 0, 0, 1, 0, 0, -1, 0, 0, 5, 0, 0, 1]
        code, facts = self.mesh('test-wall', made, turned)
        self.assertEqual(code, 0)
        for got, want in zip(facts['normal'], (0.0, 0.0, 1.0)):
            self.assertAlmostEqual(got, want, places=6)

        def turn(p):
            return (p[0] + 5.0, -p[2], p[1])
        flat = ocean_viewport.surface_points('test-sea', 'test-flat', (2.0, 3.0), 0.05, (1.0, 6.0, -2.0), 0.2, 40.0)
        wall = ocean_viewport.surface_points('test-sea', 'test-wall', (2.0, 3.0), 0.05, turn((1.0, 6.0, -2.0)), 0.2, 40.0)
        self.assertEqual(len(flat), len(wall))
        for point in flat[::53]:
            self.assertLess(nearest(wall, turn(point)), 1e-3)

    def test_only_where_its_faces_are(self):
        # An L: three of a 2 x 2 grid's quads (the one at +x, +z left out).
        made = grid(20.0, 20.0, 2, 2)
        wanted = bytes([1, 1, 1, 0])
        code, facts = self.mesh('test-l', made, wanted=wanted)
        self.assertEqual(code, 0)
        self.assertAlmostEqual(facts['area'], 300.0, places=3)
        found = ocean_viewport.surface_points('test-sea', 'test-l', (1.0, 1.0), 0.02, (0.0, 10.0, 0.0), 0.25, 50.0)
        reach = ocean.reach(ocean.settings(SEA)) * 0.02
        self.assertTrue(found)
        self.assertFalse([p for p in found if p[0] > reach + 0.3 and p[2] > reach + 0.3])
        self.assertTrue([p for p in found if p[0] > 2 and p[2] < -2])

    def test_not_flat_not_drawn(self):
        points, counts, corners, uvs = grid(10.0, 10.0, 2, 2)
        points[3 * 4 + 1] = 0.5       # the middle point raised
        self.assertEqual(self.mesh('test-bent', (points, counts, corners, uvs))[0], 1)
        # UVs that are not laid flat on the faces: one corner's thrown off.
        points, counts, corners, uvs = grid(10.0, 10.0, 2, 2)
        uvs[0] += 0.3
        self.assertEqual(self.mesh('test-uv', (points, counts, corners, uvs))[0], 2)
        self.assertIsNone(ocean_viewport.surface_points('test-sea', 'test-bent', (1.0, 1.0), 0.1, (0.0, 5.0, 0.0), 0.5, 20.0))

    def test_spacing_follows_the_eye(self):
        made = grid(200.0, 200.0, 1, 1)
        self.assertEqual(self.mesh('test-wide', made)[0], 0)
        found = ocean_viewport.surface_points('test-sea', 'test-wide', (10.0, 10.0), 0.25, (-100.0, 5.0, -100.0), 0.5, 300.0)
        self.assertLessEqual(len(found), ocean_viewport.MOST_POINTS)
        # Next to the corner nearest the eye, close; at the far corner, sparse.
        near = [p for p in found if math.hypot(p[0] + 100, p[2] + 100) < 10]
        far = [p for p in found if math.hypot(p[0] - 100, p[2] - 100) < 10]
        self.assertGreater(len(near), 4 * max(len(far), 1))


class HowTheSeaIsLaid(unittest.TestCase):
    def test_the_graphs_sea(self):
        # The Ocean Plane's own sea, as a Modo material's graph has it: an Ocean node into a Vector Displacement.
        settings = dict(ocean.DEFAULTS, water_color=[0, 0, 1], foam_color=[1, 1, 1], crest_color=[0, 1, 1], roughness=0.1,
                        foam_roughness=0.5)
        graph = ocean_plane.material(lambda key: settings.get(key, 1.0), 80.0)['node_graph']
        found = ocean_viewport.sea_of(graph)
        self.assertIsNotNone(found)
        self.assertEqual(found['factor'], 1.0)
        self.assertIn('wind_speed', found['params'])
        graph['nodes']['waves']['parameters']['factor'] = '2.5f'
        self.assertEqual(ocean_viewport.sea_of(graph)['factor'], 2.5)
        # An Ocean node as the displacement itself, as graphs before 2026-11-13 had it.
        self.assertEqual(ocean_viewport.sea_of({'nodes': {'o': {'type': 'ocean', 'parameters': {}}}, 'displacement': 'o'})['factor'], 1.0)
        self.assertIsNone(ocean_viewport.sea_of({'nodes': {'o': {'type': 'ocean'}}}))
        self.assertIsNone(ocean_viewport.sea_of(None))

    def test_fit_to_mesh(self):
        # Ten tiles across a 50 x 25 m plane (UVs 0 to 1): tiles 5 m wide, five along V, the sea scaled whole to them.
        repeat_u, repeat_v, scale = ocean_viewport.laid({'fit_to_mesh': True, 'tiles_across': 10.0}, (50.0, 25.0))
        self.assertAlmostEqual(repeat_u, 10.0)
        self.assertAlmostEqual(repeat_v, 5.0)
        self.assertAlmostEqual(scale, 5.0 / ocean.FITTED_SIZE)
        # Fit to Mesh off: its Repeat at its own size; on with nothing to fit to, the same.
        self.assertEqual(ocean_viewport.laid({'fit_to_mesh': False, 'repeat': [3.0, 2.0]}, (50.0, 25.0)), (3.0, 2.0, 1.0))
        self.assertEqual(ocean_viewport.laid({'fit_to_mesh': True, 'repeat': [3.0, 2.0]}, None), (3.0, 2.0, 1.0))


class InTheKit(unittest.TestCase):
    def test_hooked_in(self):
        entities_source = (ROOT / 'kit/MoonRayForModo/lxserv/moonray_entities.py').read_text(encoding='utf-8')
        self.assertIn('lx.bless(OceanPoints,ocean_meshes.PACKAGE', entities_source)
        self.assertIn("lx.bless(AttachOceanPoints,'moonray.ocean.attachPoints')", entities_source)
        self.assertIn('QtCore.QTimer.singleShot(0,attach_ocean_points)', entities_source)
        self.assertIn('ocean_meshes.draw_level(stroke,self.item.Ident(),tag', entities_source)
        properties_source = (ROOT / 'kit/MoonRayForModo/python/moonray_modo/properties.py').read_text(encoding='utf-8')
        self.assertIn('from .ocean_meshes import written', properties_source)
        # Modo keeps a mesh's drawing until the mesh changes: drawn again as the timeline moves and as a sea is written.
        self.assertIn('class OceanTime(lxifc.SelectionListener)', entities_source)
        self.assertIn('ocean_meshes.redraw()', entities_source)
        meshes_source = (ROOT / 'kit/MoonRayForModo/python/moonray_modo/ocean_meshes.py').read_text(encoding='utf-8')
        self.assertIn('view.InvalidateSurface(item)', meshes_source)
        # The package added through the kit's command: added by a script's own step it was never drawn.
        self.assertIn("lx.eval('moonray.ocean.attachPoints')", meshes_source)


if __name__ == '__main__':
    unittest.main()
