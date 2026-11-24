"""A Modo camera of Spherical Map or Spherical VR projection renders through MoonRay's spherical camera
(host.spherical_camera): it stopped the scene with "Unsupported camera projection" before."""
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
        # Turned a quarter about its up axis, so that the view's direction is in the middle of the picture as in Modo
        # (MoonRay's whole sphere has it three quarters across): its X axis the camera's Z, its Z the camera's -X.
        self.assertEqual(camera['matrix'], [0, 0, 1, 0, 0, 1, 0, 0, -1, 0, 0, 0, 0, 1.6, 5, 1])
        self.assertTrue(camera['parameters']['modo_render_camera'])
        self.assertEqual(entities.validate('SphericalCamera', camera['parameters']), camera['parameters'])
        self.assertFalse(warnings)
        # MoonLightIPR looks through it as MoonRay does: the whole sphere.
        self.assertEqual(entities.camera_projection(dict(camera, parameters={}))['projection'], 'spherical')

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

    def test_the_reading_maps_it(self):
        source = (ROOT / 'kit/MoonRayForModo/python/moonray_modo/host.py').read_text(encoding='utf-8')
        self.assertIn("spherical = projection in ('spherical','sphericalvr')", source)


if __name__ == '__main__':
    unittest.main()
