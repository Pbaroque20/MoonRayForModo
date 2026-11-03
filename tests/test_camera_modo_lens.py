"""A dw camera that uses the Modo camera's lens renders by its Camera tab: focal length, film, depth of field, F-stop,
focus distance, iris, stereo eye and shutter, not the MoonRay values in its dw tab."""
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import entities

MODO = {'focalLen': .035, 'apertureX': .036, 'apertureY': .024, 'filmFit': 'horizontal', 'offsetX': 0.0, 'offsetY': 0.0,
        'dof': 1, 'fStop': 2.8, 'focusDist': 3.5, 'irisBlades': 6, 'irisRot': 0.0, 'resOverride': 0, 'target': 1.0,
        'stereo': 1, 'stereoEye': 'right', 'ioDist': .07, 'convDist': 5.0}


def camera(own, linked=True):
    held = dict(MODO, **{channel: ('' if plan == 'string' else default) for _, channel, plan, default, _ in entities.channels('PerspectiveCamera')})
    held.update({entities.CHANNEL_PREFIX + key: value for key, value in own.items()})
    held[entities.CHANNEL_PREFIX + 'modo_lens'] = linked
    return SimpleNamespace(id='cam', name='Cam', type='camera', channel=lambda name: SimpleNamespace(get=lambda: held[name]) if name in held else None,
                           PackageTest=lambda package: package == entities.camera_package('PerspectiveCamera'))


def collected(item):
    render = SimpleNamespace(channel=lambda name: SimpleNamespace(get=lambda: {'resX': 1920, 'resY': 1080, 'pAspect': 1.0}[name]))
    fake_modo = types.ModuleType('modo')
    fake_modo.Scene = lambda: SimpleNamespace(renderItem=render)
    host = types.ModuleType('moonray_modo.host')
    host.channel = lambda held, name, default=None: (held.channel(name).get() if held.channel(name) is not None else default)
    host.render_visible = lambda held: True
    host.world_matrix = lambda held: [1.0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    properties = types.ModuleType('moonray_modo.properties')
    properties.read = lambda held: {}
    attributes = types.ModuleType('moonray_modo.primitive_attributes')
    attributes.read = lambda held: {}
    scene = SimpleNamespace(items=lambda kind, superType=False: [item] if kind == 'camera' else [])
    import moonray_modo
    # A module another test imported stays an attribute of the package, which "from . import" takes before sys.modules.
    stubs = {'host': host, 'properties': properties, 'primitive_attributes': attributes}
    warnings = []
    with patch.dict(sys.modules, dict({'modo': fake_modo}, **{'moonray_modo.' + key: module for key, module in stubs.items()})), \
            patch.multiple(moonray_modo, create=True, **stubs):
        sys.modules.pop('moonray_modo.camera_convert', None)
        found = [e for e in entities.collect(scene, warnings) if e['class'] == 'PerspectiveCamera']
        sys.modules.pop('moonray_modo.camera_convert', None)
        if hasattr(moonray_modo, 'camera_convert'):
            del moonray_modo.camera_convert
    assert found, warnings
    return found[0]['parameters']


class ModoLens(unittest.TestCase):
    OWN = {'focal': 80.0, 'dof': False, 'dof_aperture': 16.0, 'mb_shutter_open': -1.0, 'mb_shutter_close': 1.0, 'mb_shutter_bias': .5}

    def test_linked_camera_takes_the_camera_tab(self):
        held = collected(camera(self.OWN))
        self.assertAlmostEqual(held['focal'], 35.0)
        self.assertAlmostEqual(held['film_width_aperture'], 36.0)
        self.assertTrue(held['dof'])
        self.assertAlmostEqual(held['dof_aperture'], 2.8)
        self.assertAlmostEqual(held['dof_focus_distance'], 3.5)
        self.assertEqual((held['bokeh'], held['bokeh_sides']), (True, 6))
        self.assertEqual(held['stereo_view'], 2)
        self.assertAlmostEqual(held['stereo_interocular_distance'], .07)
        self.assertAlmostEqual(held['stereo_convergence_distance'], 5.0)
        # The shutter is the scene's, from its Blur Length and Offset; MoonRay's own bias stays.
        self.assertNotIn('mb_shutter_open', held)
        self.assertNotIn('mb_shutter_close', held)
        self.assertAlmostEqual(held['mb_shutter_bias'], .5)

    def test_a_bokeh_image_turns_the_bokeh_on_whatever_the_blades(self):
        global MODO
        held_modo = MODO
        try:
            MODO = dict(held_modo, irisBlades=0)
            self.assertFalse(collected(camera(self.OWN))['bokeh'])
            held = collected(camera(dict(self.OWN, bokeh_image='C:/bokeh/ring.exr')))
            self.assertTrue(held['bokeh'])
            self.assertEqual(held['bokeh_image'], 'C:/bokeh/ring.exr')
        finally:
            MODO = held_modo

    def test_unlinked_camera_keeps_its_moonray_values(self):
        held = collected(camera(self.OWN, linked=False))
        self.assertAlmostEqual(held['focal'], 80.0)
        self.assertAlmostEqual(held['dof_aperture'], 16.0)
        self.assertAlmostEqual(held['mb_shutter_open'], -1.0)

    def test_new_cameras_are_linked_and_the_switch_heads_their_form(self):
        for name in entities.MODO_LENS_CAMERAS:
            self.assertTrue(entities.starting(name)['modo_lens'])
            self.assertFalse(entities.catalog()[name]['attributes']['modo_lens']['default'])
        config = (ROOT / 'kit/MoonRayForModo/entities.cfg').read_text(encoding='utf-8')
        form = config[config.index('<atom type="Label">dwPerspectiveCamera</atom>\n      <atom type="Layout">'):]
        self.assertLess(form.index('MoonRayEntity_PerspectiveCamera_0:sheet'), form.index('Depth of Field'))
        self.assertIn('<atom type="Label">Lens</atom>', form[:form.index('Depth of Field')])

    def test_the_viewport_passes_a_linked_cameras_own_lens_through(self):
        source = (ROOT / 'kit/MoonRayForModo/lxserv/moonray_entities.py').read_text(encoding='utf-8')
        self.assertIn('lx.symbol.fECHAN_READ|lx.symbol.fECHAN_WRITE', source)
        self.assertIn("slots['modo_lens']", source)


if __name__ == '__main__':
    unittest.main()
