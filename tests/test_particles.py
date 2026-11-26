"""Modo's Blob and Sprite items made from their particles (moonray_modo/particles.py, native-port/modo_particles.cpp)."""
import math
import os
import struct
import sys
import tempfile
import unittest
from array import array
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / 'kit/MoonRayForModo'
sys.path.insert(0, str(KIT / 'python'))
from moonray_modo import particles, incremental, motion  # noqa: E402

TOOL = ROOT / 'build/native-avx/bin/modo_particles.exe'
# A runtime with the OpenVDB and TBB libraries the tool needs, where one is on this machine.
RUNTIMES = [Path(os.environ.get('MOONRAY_MODO_RUNTIME', '') or ROOT / 'missing'), ROOT.parents[2] / 'dist/personal-kit/Luxology/Kits/MoonRayForModo/runtime',
            ROOT / 'dist/personal-kit/Luxology/Kits/MoonRayForModo/runtime']
RUNTIME = next((r for r in RUNTIMES if (r / 'moonray.exe').is_file()), None)


class Measured(unittest.TestCase):
    """What Modo's renders showed (tools/probe_cl_blob_field.py, measured by tools/measure_blob_field.py)."""

    def test_lone_blob_radius_at_each_level(self):
        # Radius 1: the blob's radius at Level 0.1, 0.25, 0.5, 0.75, 0.9 in Modo's render.
        for level, seen in ((0.1, 0.1856), (0.25, 0.3023), (0.5, 0.4541), (0.75, 0.6083), (0.9, 0.7319)):
            self.assertAlmostEqual(particles.surface_radius(1.0, level), seen, delta=0.004)

    def test_neck_between_two_particles(self):
        # Two particles 0.8 apart, Radius 1, Level 0.5: Modo's neck was 0.9175 high; 1.6 apart they do not meet.
        def field(x, y, d):
            return sum(max(0.0, 1 - ((x - c) ** 2 + y * y)) ** 3 for c in (-d / 2, d / 2))
        t = particles.threshold(0.5)
        neck = max(y / 1000 for y in range(1000) if field(0, y / 1000, 0.8) >= t)
        self.assertAlmostEqual(2 * neck, 0.9175, delta=0.01)
        self.assertLess(field(0, 0, 1.6), t)

    def test_size_random_follows_the_particle_id(self):
        # Size Random 50 %: the radius is 1 - 0.5 (1 - id) of the Radius (Modo's eleven blobs, ids 0, .5, .25, ...).
        made = particles.radii(0.6, 0.5, [0.0, 0.5, 0.25, 0.75, 1.0])
        self.assertEqual([round(r, 4) for r in made], [0.3, 0.45, 0.375, 0.525, 0.6])
        self.assertEqual([round(r, 4) for r in particles.radii(1.0, 0.0, [0.1, 0.9], [2.0, 0.5])], [2.0, 0.5])

    def test_sprite_tables(self):
        self.assertEqual(particles.sprite_table(0.0)[0], 2.0)
        self.assertFalse(any(particles.sprite_table(1.0)))
        between = particles.sprite_table(0.375)
        low, high = particles.SPRITE_TABLES[0.25], particles.SPRITE_TABLES[0.5]
        self.assertAlmostEqual(between[10], (low[10] + high[10]) / 2, places=6)
        # The depth through a puff's middle at Falloff 0.5, Density 1, Radius 1: Modo's alpha 0.8594 (tau 1.962).
        table = particles.SPRITE_TABLES[0.5]
        n = len(table) - 1
        tau = 2 * sum((table[i] + table[i + 1]) / 2 / n for i in range(n))
        self.assertAlmostEqual(tau, 1.962, delta=0.06)


class Arithmetic(unittest.TestCase):
    def test_points_placed_by_a_matrix(self):
        matrix = [2, 0, 0, 0, 0, 2, 0, 0, 0, 0, 2, 0, -4, 1, 0, 1]
        self.assertEqual(list(particles.placed(array('f', [0, 0, 0, 0.5, 0, 0]), matrix)), [-4, 1, 0, -3, 1, 0])
        self.assertEqual(list(particles.turned(array('f', [1, 0, 0]), matrix)), [2, 0, 0])
        self.assertEqual(list(particles.placed(array('f', [1, 2, 3]), particles.IDENTITY)), [1, 2, 3])

    def test_velocities_from_two_moments(self):
        now = array('f', [0, 0, 0, 1, 0, 0])
        later = array('f', [0, 0.5, 0, 1, 0, 0])
        self.assertEqual(list(particles.moved(now, later, 0.5)), [0, 1, 0, 0, 0, 0])
        self.assertIsNone(particles.moved(now, now, 0.5))
        # Another count: matched by their IDs, a particle not found later still.
        later = array('f', [9, 9, 9, 1, 1, 0])
        self.assertEqual(list(particles.moved(now, later[3:], 1.0, [0.1, 0.2], [0.2])), [0, 0, 0, 0, 1, 0])
        self.assertIsNone(particles.moved(now, later[3:], 1.0))

    def test_cells_kept_within_the_budget(self):
        few = particles.blob_cell([1.0] * 10, 0.5, 'high', 10)
        self.assertAlmostEqual(few, particles.surface_radius(1.0, 0.5) / particles.QUALITY['high'])
        many = particles.blob_cell([1.0] * 100000, 0.5, 'high', 100000)
        self.assertGreater(many, few)
        self.assertLessEqual(100000 * 4.18879 / many ** 3, particles.BUDGET * 1.001)

    def test_request_layout(self):
        asked = particles.request(1, array('f', [1, 2, 3, 4, 5, 6]), array('f', [0.5, 0.25]), array('f', [1, 1]), 0.1, level=0.5,
                                  velocities=array('f', [7, 8, 9, 10, 11, 12]))
        self.assertEqual(asked[:4], b'MPR1')
        mode, count, flags, level, cell, n = struct.unpack_from('<3I2fI', asked, 4)
        self.assertEqual((mode, count, flags, n), (1, 2, 1, 0))
        body = array('f')
        body.frombytes(asked[4 + 24:])
        self.assertEqual(list(body), [1, 2, 3, 0.5, 1, 7, 8, 9, 4, 5, 6, 0.25, 1, 10, 11, 12])

    def test_answer_read(self):
        data = b'MPM1' + struct.pack('<5I', 3, 1, 3, 1, 0) + array('f', range(9)).tobytes() + array('f', [1] * 9).tobytes() + \
            array('i', [3]).tobytes() + array('i', [0, 1, 2]).tobytes()
        points, speed, counts, corners = particles.blob_answer(data)
        self.assertEqual((len(points), len(speed), list(counts), list(corners)), (9, 9, [3], [0, 1, 2]))
        with self.assertRaises(ValueError):
            particles.blob_answer(data[:-4])


class Reading(unittest.TestCase):
    """particles.apply on a reading, Modo stood in for."""

    def test_earlier_particles_replaced_and_source_points_left_out(self):
        class Item:
            def __init__(self, identity, kind):
                self.id, self.type, self.name, self.parent = identity, kind, identity, None

            def itemGraph(self, name):
                return mock.Mock(reverse=lambda: [SOURCE] if self.type == 'blob' else [])
        SOURCE = Item('cloud', 'mesh')
        blob = Item('blob1', 'blob')
        scene = mock.Mock(items=lambda kind, superType=False: [blob] if kind == 'blob' else [])
        result = {'meshes': [{'identity': particles.PREFIX + 'blob|old'}, {'identity': 'floor|0|'}], 'time': 0.0, 'fps': 24.0,
                  'extra_geometry': [{'kind': 'points', 'source_item': 'cloud', 'identity': 'cloud|points'},
                                     {'kind': 'vdb', 'identity': particles.PREFIX + 'sprite|old'}]}
        made = {'name': 'blob1', 'identity': particles.PREFIX + 'blob|blob1'}
        held = {'positions': array('f', [0, 0, 0]), 'ids': array('f', [0.5]), 'sizes': None, 'velocities': None}
        host = mock.Mock(render_visible=lambda item: True)
        with mock.patch.dict(sys.modules, {'moonray_modo.host': host, 'lx': mock.Mock()}), \
                mock.patch.object(particles, 'read', return_value=held), mock.patch.object(particles, 'settings', return_value={}), \
                mock.patch.object(particles, 'unread', return_value=['Stretch']), mock.patch.object(particles, 'velocities_of', return_value=None), \
                mock.patch.object(particles, 'blob_mesh', return_value=made):
            warnings = []
            particles.apply(scene, result, warnings)
        self.assertEqual([m['identity'] for m in result['meshes']], ['floor|0|', made['identity']])
        self.assertEqual(result['extra_geometry'], [])
        self.assertEqual(result['particle_items'], ['blob1', 'cloud'])
        self.assertIn('Blob blob1: Stretch is not followed.', warnings)

    def test_moving_a_source_reads_the_scene_again(self):
        transform = mock.Mock(type='translation')
        transform.itemGraph.return_value.forward.return_value = [mock.Mock(id='cloud')]
        other = mock.Mock(type='translation')
        other.itemGraph.return_value.forward.return_value = [mock.Mock(id='chair')]
        scene = mock.Mock(item=lambda identity: {'t1': transform, 't2': other}[identity])
        cache = {'particle_items': ['blob1', 'cloud']}
        self.assertTrue(incremental.touches_particles(scene, ['t1'], cache))
        self.assertFalse(incremental.touches_particles(scene, ['t2'], cache))
        self.assertTrue(incremental.touches_particles(scene, ['blob1'], cache))
        self.assertFalse(incremental.touches_particles(scene, ['t1'], {}))
        self.assertIs(incremental.classify(scene, ['t1'], cache), False)

    def test_blob_rebuilt_in_the_shutter_is_blurred_along_its_velocities(self):
        from moonray_modo.rows import Rows, Faces
        identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
        camera = {'identity': 'cam', 'matrix': identity, 'focal_mm': 50}

        def blob(points, speed):
            mesh = {'identity': particles.PREFIX + 'blob|b', 'name': 'b', 'matrix': identity, 'volumetric': True,
                    'vertices': Rows(array('f', points), 3, 'p%d' % len(points)), 'faces': Faces(array('i', [0, 1, 2]), array('i', [3]), 'f'),
                    'velocities': Rows(array('f', speed), 3, 'v')}
            return {'camera': dict(camera), 'lights': [], 'meshes': [mesh], 'fps': 24}
        scene = blob([0, 0, 0, 1, 0, 0, 0, 1, 0], [24, 0, 0] * 3)
        # The shutter's ends made other meshes (more points): the frame's is moved along its velocities.
        motion.apply_motion(scene, blob([0] * 12, [0] * 12), blob([0] * 15, [0] * 15), [-0.25, 0.25])
        made = scene['meshes'][0]
        self.assertEqual([round(v, 4) for v in made['vertices'][0]], [-0.25, 0, 0])
        self.assertEqual([round(v, 4) for v in made['vertices_close'][0]], [0.25, 0, 0])

    def test_sprite_with_velocities_blurs_without_a_notice(self):
        identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
        camera = {'identity': 'cam', 'matrix': identity, 'focal_mm': 50}

        def reading(path):
            return {'camera': dict(camera), 'meshes': [], 'lights': [], 'extra_geometry': [
                {'kind': 'vdb', 'identity': particles.PREFIX + 'sprite|s', 'file': path, 'velocity_grid': 'v', 'matrix': identity}]}
        scene = reading('b.vdb')
        motion.apply_motion(scene, reading('a.vdb'), reading('c.vdb'), [-0.25, 0.25])
        self.assertFalse([w for w in scene['warnings'] if 'Animated VDB' in w])


@unittest.skipUnless(TOOL.is_file() and RUNTIME is not None, 'modo_particles.exe not built (tools/build_particles_tool.py) or no runtime')
class Native(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.dict(os.environ, {'MOONRAY_MODO_PARTICLES_TOOL': str(TOOL), 'MOONRAY_MODO_RUNTIME': str(RUNTIME)})
        patch.start()
        self.addCleanup(patch.stop)

    def test_lone_blob_is_a_ball_of_its_radius_facing_out(self):
        cell = particles.blob_cell([1.0], 0.5, 'high', 1)
        asked = particles.request(1, array('f', [1, 2, 3]), array('f', [1.0]), array('f', [1.0]), cell, level=particles.threshold(0.5),
                                  velocities=array('f', [0, 2, 0]))
        points, speed, counts, corners = particles.blob_answer(particles.run(asked, '.mpm'))
        expected = particles.surface_radius(1.0, 0.5)
        distances = [math.dist(points[i:i + 3], (1, 2, 3)) for i in range(0, len(points), 3)]
        self.assertLess(max(abs(d - expected) for d in distances), 1e-3)
        self.assertTrue(all(abs(speed[i + 1] - 2) < 1e-4 for i in range(0, len(speed), 3)))
        # The first face turns anticlockwise seen from outside.
        a, b, c = (points[3 * corners[k]:3 * corners[k] + 3] for k in range(3))
        u = [b[i] - a[i] for i in range(3)]
        v = [c[i] - a[i] for i in range(3)]
        normal = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
        self.assertGreater(sum(n * (a[i] - (1, 2, 3)[i]) for i, n in enumerate(normal)), 0)
        self.assertEqual(sum(counts), len(corners))

    def test_sprite_file(self):
        asked = particles.request(2, array('f', [0, 0, 0]), array('f', [0.5]), array('f', [1.0]), 0.05, table=particles.sprite_table(0.5))
        made = particles.run(asked, '.vdb')
        try:
            self.assertGreater(made.stat().st_size, 1000)
        finally:
            made.unlink()


if __name__ == '__main__':
    unittest.main()
