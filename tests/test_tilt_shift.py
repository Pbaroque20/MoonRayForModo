"""The tilt-shift camera (tools/port_tilt_shift.py): a MoonRay Source Override, in the kit, MoonRay, XPU2 and MoonLightIPR.
No Modo."""
import math
import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
KIT = ROOT / 'kit/MoonRayForModo'
sys.path.insert(0, str(KIT / 'python'))

from moonray_modo import camera_convert, entities, moonlightipr_scene, native, rdla  # noqa: E402


def text(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


def look_at(eye, target):
    back = [e - t for e, t in zip(eye, target)]
    length = math.sqrt(sum(v * v for v in back))
    back = [v / length for v in back]
    right = [back[2], 0.0, -back[0]]
    length = math.sqrt(sum(v * v for v in right))
    right = [v / length for v in right]
    up = [back[1] * right[2] - back[2] * right[1], back[2] * right[0] - back[0] * right[2], back[0] * right[1] - back[1] * right[0]]
    return right + [0.0] + up + [0.0] + back + [0.0] + list(eye) + [1.0]


def scene(kind='TiltShiftCamera', modo_dof=False, **parameters):
    """A ground plane seen through a MoonRay camera item, the Modo camera's own depth of field off."""
    camera = dict({'focal': 50.0, 'film_width_aperture': 36.0, 'dof': True, 'dof_aperture': 2.0, 'dof_focus_distance': 12.0,
                   'modo_render_camera': True}, **parameters)
    matrix = look_at([0, 7.5, 9.5], [0, 0, -2.5])
    return {'camera': {'matrix': matrix, 'focal_mm': 50.0, 'film_mm': 36.0, 'dof': modo_dof},
            'materials': {'': {'color': [.5, .5, .5], 'roughness': .6}},
            'meshes': [{'name': 'Ground', 'identity': 'ground', 'vertices': [[-9, 0, -9], [9, 0, -9], [9, 0, 9], [-9, 0, 9]],
                        'faces': [[0, 3, 2, 1]], 'material': ''}],
            'lights': [], 'environments': [],
            'entities': [{'identity': 'tilt', 'name': 'Tilt', 'class': kind, 'matrix': matrix, 'parameters': camera}]}


class Switched(unittest.TestCase):
    def setUp(self):
        self.held = os.environ.pop('MOONRAY_MODO_TILT_SHIFT', None)

    def tearDown(self):
        os.environ.pop('MOONRAY_MODO_TILT_SHIFT', None)
        if self.held is not None:
            os.environ['MOONRAY_MODO_TILT_SHIFT'] = self.held

    def camera_text(self, **parameters):
        rdl = rdla.scene_text(scene(**parameters), 64, 40, 1, 0.0, 'out.exr')
        start = rdl.index('local camera')
        return rdl[start:rdl.index('}', start)], rdl

    def test_written_as_a_tilt_shift_camera(self):
        camera, rdl = self.camera_text(lens_tilt=-4.0, tilt_direction=30.0)
        self.assertTrue(camera.startswith('local camera = TiltShiftCamera('))
        self.assertIn('["lens_tilt"] = -4', camera)
        self.assertIn('["tilt_direction"] = 30', camera)
        # Its own depth of field switches MoonRay's on, though the Modo camera's is off.
        self.assertIn('["enable_dof"] = true', rdl)

    def test_switched_off_it_is_a_perspective_camera(self):
        os.environ['MOONRAY_MODO_TILT_SHIFT'] = '0'
        self.assertFalse(native.tilt_shift())
        camera, _ = self.camera_text(lens_tilt=-4.0, tilt_direction=30.0)
        self.assertTrue(camera.startswith('local camera = PerspectiveCamera('))
        self.assertNotIn('lens_tilt', camera)
        self.assertNotIn('tilt_direction', camera)
        self.assertIn('["dof_focus_distance"] = 12', camera)

    def test_no_depth_of_field_no_enable(self):
        _, rdl = self.camera_text(dof=False)
        self.assertIn('["enable_dof"] = false', rdl)

    def test_moonlightipr_view(self):
        entity = scene(lens_tilt=-4.0, tilt_direction=30.0)['entities'][0]
        view = entities.camera_view({'matrix': entity['matrix']}, entity, entity['matrix'], print)
        self.assertEqual((view['projection'], view['dof'], view['lens_tilt'], view['tilt_direction']), ('persp', True, -4.0, 30.0))
        os.environ['MOONRAY_MODO_TILT_SHIFT'] = '0'
        view = entities.camera_view({'matrix': entity['matrix']}, entity, entity['matrix'], print)
        self.assertNotIn('lens_tilt', view)
        self.assertTrue(view['dof'])


class FocusPlane(unittest.TestCase):
    def test_hinge_rule(self):
        # Merklinger's hinge rule: the plane's slope from the camera is focus distance * sin(tilt) / f, f in metres.
        camera = {'dof': True, 'focal_mm': 50.0, 'focus_distance': 12.0, 'lens_tilt': 2.0, 'tilt_direction': 0.0}
        slope = 12.0 * math.sin(math.radians(2.0)) / .05
        tilt = moonlightipr_scene.lens_focus_tilt(camera)
        self.assertAlmostEqual(tilt[0], 0.0, places=9)
        self.assertAlmostEqual(tilt[1], -slope, places=9)
        # Turned sideways (90): toward the right; in a scene of centimetres, f is a hundred times as many units.
        tilt = moonlightipr_scene.lens_focus_tilt(dict(camera, tilt_direction=90.0), scene_scale=.01)
        self.assertAlmostEqual(tilt[0], slope / 100, places=6)
        self.assertAlmostEqual(tilt[1], 0.0, places=9)

    def test_square_without_tilt_or_lens(self):
        self.assertEqual(moonlightipr_scene.lens_focus_tilt({'dof': True, 'focal_mm': 50.0, 'lens_tilt': 0.0}), [0.0, 0.0])
        self.assertEqual(moonlightipr_scene.lens_focus_tilt({'dof': False, 'focal_mm': 50.0, 'lens_tilt': 3.0}), [0.0, 0.0])


class InTheKit(unittest.TestCase):
    def test_catalog_and_forms(self):
        attributes = entities.catalog()['TiltShiftCamera']['attributes']
        for key in ('lens_tilt', 'tilt_direction', 'modo_lens', 'modo_render_camera', 'focal', 'dof_focus_distance', 'horizontal_film_offset'):
            self.assertIn(key, attributes)
        self.assertEqual(attributes['horizontal_film_offset']['label'], 'horizontal shift')
        self.assertIn('moonray.cameraKind.TiltShiftCamera', text('kit/MoonRayForModo/entities.cfg'))
        self.assertIn('dwTiltShiftCamera', text('kit/MoonRayForModo/entities.cfg'))

    def test_a_perspective_camera_everywhere(self):
        for listed in (entities.VIEWED_CAMERAS, entities.MODO_LENS_CAMERAS, entities.PERSPECTIVE_CAMERAS, dict(camera_convert.KINDS)):
            self.assertIn('TiltShiftCamera', listed)
        self.assertEqual(entities.lens_inputs('TiltShiftCamera'), entities.lens_inputs('PerspectiveCamera'))
        self.assertEqual(camera_convert.taken('TiltShiftCamera'), camera_convert.taken('PerspectiveCamera'))
        number = {'focal': 35.0, 'film_width_aperture': 36.0, 'horizontal_film_offset': 2.0, 'vertical_film_offset': -1.0}.get
        self.assertEqual(entities.modo_lens('TiltShiftCamera', number), entities.modo_lens('PerspectiveCamera', number))
        self.assertEqual(entities.starting('TiltShiftCamera').get('modo_lens'), True)

    def test_the_switch_is_wired(self):
        self.assertIn("'tilt_shift': (True, bool)", text('kit/MoonRayForModo/python/moonray_modo/preferences.py'))
        self.assertIn("lx.bless(switch('tilt_shift'),'moonray.pref.tiltShift')", text('kit/MoonRayForModo/lxserv/moonray_preferences.py'))
        self.assertIn('cmd moonray.pref.tiltShift ?', text('kit/MoonRayForModo/preferences.cfg'))
        self.assertIn("env['MOONRAY_MODO_TILT_SHIFT']", text('kit/MoonRayForModo/python/moonray_modo/native.py'))
        self.assertIn('tilt_shift()', text('kit/MoonRayForModo/python/moonray_modo/native.py').split('def source_switches')[1].split('def ')[0])


class InTheRenderers(unittest.TestCase):
    def test_moonray_port(self):
        port = text('tools/port_tilt_shift.py')
        self.assertIn('MOONRAY_MODO_TILT_SHIFT', port)
        self.assertIn('return !value || value[0] != \'0\';', port)
        self.assertIn('TiltShiftCamera', text('patches/native-windows/README.md'))

    def test_xpu2_follows(self):
        scene_code, camera_code = text('xpu2/interactive/cpu_scene.h'), text('xpu2/interactive/camera_core.h')
        self.assertIn('{"TiltShiftCamera",{', scene_code)
        self.assertIn('modoSourceOverride("MOONRAY_MODO_TILT_SHIFT")', scene_code)
        self.assertIn('c.focusNormal', camera_code)
        self.assertIn('"TiltShiftCamera"', text('xpu2/interactive/entity_classes.h'))
        self.assertIn('TiltShiftCamera.so.proxy', text('xpu2/interactive/build_session.py'))

    def test_moonlightipr_follows(self):
        self.assertIn('in.floats(camera.focusTilt, 2);', text('moonlightipr/session/scene_loader.cpp'))
        self.assertIn('params.focusTilt', text('moonlightipr/src/device/kernel.cu'))
        self.assertIn("b'MLSb'", text('kit/MoonRayForModo/python/moonray_modo/moonlightipr_scene.py'))


if __name__ == '__main__':
    unittest.main()
