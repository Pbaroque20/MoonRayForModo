"""A Modo camera of Spherical Map or Spherical VR projection renders through MoonRay's spherical camera
(host.spherical_camera): it stopped the scene with "Unsupported camera projection" before."""
import math
import pathlib
import sys
import types
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
_lxu = types.ModuleType('lxu')
_lxu.utils = types.ModuleType('lxu.utils')
_stubs = {'lx': types.ModuleType('lx'), 'lxu': _lxu, 'lxu.utils': _lxu.utils, 'lxifc': types.ModuleType('lxifc'),
          'modo': types.ModuleType('modo')}
with mock.patch.dict(sys.modules, {name: module for name, module in _stubs.items() if name not in sys.modules}):
    from moonray_modo import entities, host  # noqa: E402

PLACE = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 1.6, 5, 1]


class Camera:
    id, name = 'cam01', 'Camera'


class SphericalCamera(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(host, 'world_matrix', return_value=PLACE)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_spherical_camera_takes_its_place(self):
        result, warnings = {'entities': []}, []
        host.spherical_camera(result, Camera(), False, warnings)
        (camera,) = result['entities']
        self.assertEqual(camera['class'], 'SphericalCamera')
        # Spherical Map is the sphere seen from outside, as Modo renders it: the camera's +Z in the middle of the picture,
        # +X a quarter to the right. MoonRay's longitudes run backwards for it (360 at the left edge, 0 at the right),
        # about the camera as it stands; a turn alone mirrored the picture front to back.
        self.assertEqual(camera['matrix'], PLACE)
        self.assertEqual((camera['parameters']['min_longitude'], camera['parameters']['max_longitude']), (360.0, 0.0))
        self.assertTrue(camera['parameters']['modo_render_camera'])
        self.assertEqual(entities.validate('SphericalCamera', camera['parameters']), camera['parameters'])
        self.assertFalse(warnings)
        # MoonLightIPR looks through it as MoonRay does: the whole sphere, its longitude falling across the picture.
        lens = entities.camera_projection(camera)
        self.assertEqual(lens['projection'], 'spherical')
        self.assertAlmostEqual(lens['projection_values'][2], -2 * math.pi)
        self.assertAlmostEqual(lens['projection_values'][3], 2 * math.pi)

    def test_spherical_map_looks_as_modo_does(self):
        """Modo's Spherical Map sees (sin L cos f, sin f, cos L cos f) in the camera's axes at longitude L (-pi at the
        left edge) and latitude f: MoonRay's SphericalCamera.cc direction at the same pixel, through the camera's matrix."""
        result = {'entities': []}
        host.spherical_camera(result, Camera(), False, [])
        (camera,) = result['entities']
        low, high = (math.radians(camera['parameters'][k]) for k in ('min_longitude', 'max_longitude'))
        m = camera['matrix']
        for across in (.1, .25, .5, .75, .9):
            for latitude in (-.6, 0.0, .8):
                phi = low + (high - low) * across
                local = (math.cos(latitude) * math.sin(phi), math.sin(latitude), -math.cos(latitude) * math.cos(phi))
                seen = [sum(local[i] * m[i * 4 + j] for i in range(3)) for j in range(3)]
                longitude = 2 * math.pi * (across - .5)
                modo = (math.sin(longitude) * math.cos(latitude), math.sin(latitude), math.cos(longitude) * math.cos(latitude))
                for a, b in zip(seen, modo):
                    self.assertAlmostEqual(a, b, places=6)

    def test_spherical_vr_is_seen_from_inside(self):
        # Spherical VR has the view's direction (-Z) in the middle and +X a quarter to the right, as MoonRay's default
        # whole sphere does once turned a quarter about the camera's up axis (it has the view three quarters across).
        result = {'entities': []}
        host.spherical_camera(result, Camera(), True, [])
        (camera,) = result['entities']
        self.assertEqual(camera['matrix'], [0, 0, 1, 0, 0, 1, 0, 0, -1, 0, 0, 0, 0, 1.6, 5, 1])
        self.assertNotIn('min_longitude', camera['parameters'])

    def test_vr_is_one_picture_with_a_notice(self):
        result, warnings = {'entities': []}, []
        host.spherical_camera(result, Camera(), True, warnings)
        self.assertEqual(len(result['entities']), 1)
        self.assertIn('Spherical VR', warnings[0])

    def test_a_moonray_camera_chosen_to_render_through_stays(self):
        chosen = {'identity': 'm', 'class': 'PerspectiveCamera', 'parameters': {'modo_render_camera': True}}
        result = {'entities': [chosen]}
        host.spherical_camera(result, Camera(), False, [])
        self.assertEqual(result['entities'], [chosen])

    def test_a_drag_moves_it_with_the_camera(self):
        """A realtime drag of the camera (incremental.move_only, the viewport's place for it): the spherical camera made
        for it goes there too, as a fresh reading puts it, and XPU2 RT's step is its place alone (rdla.camera_delta).
        It stayed where the drag began in every engine before."""
        from moonray_modo import incremental, rdla
        moved_to = [0, 0, -1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 2, 1.6, 5, 1]   # turned a quarter about Y, moved along X
        for vr in (False, True):
            result = {'entities': []}
            host.spherical_camera(result, Camera(), vr, [])
            snapshot = {'camera': {'identity': Camera.id, 'matrix': PLACE}, 'entities': result['entities'], 'meshes': []}
            fresh = {'entities': []}
            with mock.patch.object(host, 'world_matrix', return_value=moved_to):
                host.spherical_camera(fresh, Camera(), vr, [])
            # (move_only reads host.world_matrix, host Modo's modules: stood in for, as at the import above.)
            with mock.patch.dict(sys.modules, dict(_stubs, **{'moonray_modo.host': host})):
                moved = incremental.move_only(None, snapshot, [], camera_moved=True, camera_matrix=moved_to)
            self.assertIsNotNone(moved, incremental.REFUSED)
            (camera,) = moved['entities']
            self.assertEqual(camera['matrix'], fresh['entities'][0]['matrix'])
            self.assertEqual(camera['parameters'], fresh['entities'][0]['parameters'])
            self.assertEqual(snapshot['entities'][0]['matrix'], result['entities'][0]['matrix'])   # the scene sent last is kept
            delta = rdla.camera_delta(moved)
            self.assertTrue(delta.startswith('SphericalCamera("/modo/camera")'), delta)
            self.assertIn(rdla.matrix(camera['matrix']), delta)

    def test_it_blurs_as_the_camera_moves(self):
        """With motion blur, the spherical camera stands where the Modo camera stands at the shutter's open and close
        (motion.apply_motion reads it at both ends): MoonRay and XPU2 are given blur(open, close), MoonLightIPR its close
        too (entities.camera_view; it was left sharp there). A drag's step is shown sharp (move_only)."""
        from moonray_modo import incremental, motion, rdla
        opened, closed = PLACE, [0, 0, -1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 1.6, 5, 1]
        for vr in (False, True):
            readings = []
            for place in (PLACE, opened, closed):
                result = {'entities': []}
                with mock.patch.object(host, 'world_matrix', return_value=place):
                    host.spherical_camera(result, Camera(), vr, [])
                readings.append({'camera': {'identity': Camera.id, 'matrix': place, 'projection': 'persp', 'focal_mm': 50.0},
                                 'entities': result['entities'], 'meshes': [], 'lights': []})
            scene = readings[0]
            motion.apply_motion(scene, readings[1], readings[2], [-.25, .25])
            (camera,) = scene['entities']
            self.assertEqual(camera['matrix'], readings[1]['entities'][0]['matrix'])
            self.assertEqual(camera['matrix_close'], readings[2]['entities'][0]['matrix'])
            self.assertNotEqual(camera['matrix'], camera['matrix_close'])
            lines = entities.camera_lines(scene, entities.checked(scene)[0])
            self.assertIn('["node_xform"] = blur(', '\n'.join(lines))
            view = entities.camera_view(scene['camera'], camera, camera['matrix'], lambda what: None)
            self.assertEqual(view['matrix_close'], camera['matrix_close'])
            with mock.patch.dict(sys.modules, dict(_stubs, **{'moonray_modo.host': host})):
                moved = incremental.move_only(None, scene, [], camera_moved=True, camera_matrix=closed)
            (step,) = moved['entities']
            self.assertEqual(step['matrix_close'], step['matrix'])
            # Its step as XPU2 RT is sent it: the same place at both ends, as a perspective camera's step is.
            self.assertIn('blur(%s, %s)' % ((rdla.matrix(step['matrix']),) * 2), rdla.camera_delta(moved))

    def test_the_reading_maps_it(self):
        source = (ROOT / 'kit/MoonRayForModo/python/moonray_modo/host.py').read_text(encoding='utf-8')
        self.assertIn("spherical = projection in ('spherical','sphericalvr')", source)


if __name__ == '__main__':
    unittest.main()
