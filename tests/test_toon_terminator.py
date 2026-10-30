"""The toon terminator preference: toon materials lit by their smooth normals on coarse meshes (issue 129).

MoonRay reads MOONRAY_MODO_TOON_TERMINATOR as it starts; the plugin sets it from the MoonRay preference, on by default."""
import os
import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
KIT = ROOT / 'kit/MoonRayForModo'
sys.path.insert(0, str(KIT / 'python'))
from moonray_modo import native


class ToonTerminator(unittest.TestCase):
    def test_on_by_default(self):
        text = (KIT / 'python/moonray_modo/preferences.py').read_text(encoding='utf-8')
        self.assertIn("'toon_terminator': (True, bool)", text)

    def test_environment_carries_it(self):
        with mock.patch.object(native, 'toon_terminator', return_value=True):
            self.assertEqual(native.environment(ROOT)['MOONRAY_MODO_TOON_TERMINATOR'], '1')
        with mock.patch.object(native, 'toon_terminator', return_value=False):
            self.assertEqual(native.environment(ROOT)['MOONRAY_MODO_TOON_TERMINATOR'], '0')

    def test_outside_modo_follows_the_variable(self):
        with mock.patch.dict(sys.modules, {'PySide2': None}):
            with mock.patch.dict(os.environ, {'MOONRAY_MODO_TOON_TERMINATOR': '0'}):
                self.assertFalse(native.toon_terminator())
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop('MOONRAY_MODO_TOON_TERMINATOR', None)
                self.assertTrue(native.toon_terminator())

    def test_toon_albedo_reaches_moonray(self):
        text = (KIT / 'python/moonray_modo/preferences.py').read_text(encoding='utf-8')
        self.assertIn("'toon_albedo': (True, bool)", text)
        with mock.patch.object(native, 'toon_albedo', return_value=False):
            self.assertEqual(native.environment(ROOT)['MOONRAY_MODO_TOON_ALBEDO'], '0')
        with mock.patch.dict(sys.modules, {'PySide2': None}):
            with mock.patch.dict(os.environ, {'MOONRAY_MODO_TOON_ALBEDO': '1'}):
                self.assertTrue(native.toon_albedo())
        self.assertIn('cmd moonray.pref.toonAlbedo ?', (KIT / 'preferences.cfg').read_text(encoding='utf-8'))

    def test_overrides_in_their_own_section_and_the_page_named_with_moonray_version(self):
        from moonray_modo import MOONRAY_RELEASE
        page = (KIT / 'preferences.cfg').read_text(encoding='utf-8')
        # The MoonRay page is named with the release it renders with; its overrides section is not.
        self.assertIn('<hash type="T" key="moonray">MoonRay (%s)</hash>' % MOONRAY_RELEASE, page)
        self.assertIn('<atom type="Label">MoonRay Source Overrides</atom>', page)
        section = page[page.index('<hash type="Sheet" key="MoonRaySourceOverrides:sheet">'):]
        section = section[:section.index('</hash>')]
        for command in ('toonTerminator', 'toonAlbedo', 'lightMotion'):
            self.assertIn('cmd moonray.pref.%s ?' % command, section)
        self.assertIn("lx.bless(switch('light_motion'),'moonray.pref.lightMotion')",
                      (KIT / 'lxserv/moonray_preferences.py').read_text(encoding='utf-8'))

    def test_moving_lights_follow_the_switch(self):
        from moonray_modo import lighting
        light = {'kind': 'SpotLight', 'identity': 'l', 'name': 'L', 'color': [1, 1, 1], 'intensity': 1.0,
                 'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1], 'matrix_close': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 1]}
        for on in (True, False):
            with mock.patch.object(native, 'light_motion', return_value=on):
                lines = []
                lighting.emit({'lights': [light]}, [], 0.0, lines)
                self.assertEqual(any('["mb"] = true' in line for line in lines), on)

    def test_stop_finishing_the_tiles_in_hand_is_an_override_on_by_default(self):
        with mock.patch.dict(sys.modules, {'PySide2': None}):
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop('MOONRAY_MODO_DRAIN', None)
                self.assertTrue(native.drain_tiles())
            with mock.patch.dict(os.environ, {'MOONRAY_MODO_DRAIN': '0'}):
                self.assertFalse(native.drain_tiles())
        page = (KIT / 'preferences.cfg').read_text(encoding='utf-8')
        section = page[page.index('<hash type="Sheet" key="MoonRaySourceOverrides:sheet">'):]
        section = section[:section.index('</hash>')]
        self.assertIn('cmd moonray.pref.drainTiles ?', section)
        self.assertIn("lx.bless(switch('drain_tiles'),'moonray.pref.drainTiles')",
                      (KIT / 'lxserv/moonray_preferences.py').read_text(encoding='utf-8'))
        # The stop asks MoonRay to drain only with the switch on.
        stop = (KIT / 'python/moonray_modo/render.py').read_text(encoding='utf-8')
        self.assertIn("if drain_tiles() and drains(self.active['runtime']) and self.session.drain():", stop)
        self.assertIn("'drain_tiles': (True, bool)", (KIT / 'python/moonray_modo/preferences.py').read_text(encoding='utf-8'))

    def test_the_four_source_switches_reach_moonray(self):
        page = (KIT / 'preferences.cfg').read_text(encoding='utf-8')
        section = page[page.index('<hash type="Sheet" key="MoonRaySourceOverrides:sheet">'):]
        section = section[:section.index('</hash>')]
        # Auto on the graphics card first stands on the XPU page since 2026-10-28.
        xpu = page[page.index('<hash type="Sheet" key="MoonRayXPU:sheet">'):]
        section += xpu[:xpu.index('</hash>')]
        commands = (KIT / 'lxserv/moonray_preferences.py').read_text(encoding='utf-8')
        defaults = (KIT / 'python/moonray_modo/preferences.py').read_text(encoding='utf-8')
        for key, command, variable in (('usd_specular', 'usdSpecular', 'MOONRAY_MODO_USD_SPECULAR'),
                                       ('opaque_alpha', 'opaqueAlpha', 'MOONRAY_MODO_OPAQUE_ALPHA'),
                                       ('transmission_roughness', 'transmissionRoughness', 'MOONRAY_MODO_TRANSMISSION_ROUGHNESS'),
                                       ('auto_xpu', 'autoXpu', 'MOONRAY_MODO_AUTO_XPU')):
            self.assertIn('cmd moonray.pref.%s ?' % command, section)
            self.assertIn("lx.bless(switch('%s'),'moonray.pref.%s')" % (key, command), commands)
            self.assertIn("'%s': (True, bool)" % key, defaults)
            with mock.patch.dict(sys.modules, {'PySide2': None}):
                for value in ('1', '0'):
                    with mock.patch.dict(os.environ, {variable: value}):
                        self.assertEqual(native.environment(KIT)[variable], value)
        # MoonLightIPR follows the rough glass switch as MoonRay does.
        from moonray_modo import moonlightipr_materials
        glass = {'roughness': 0.0, 'transmission': 1.0, 'use_independent_transmission_roughness': True, 'independent_transmission_roughness': 0.6}
        for on, expected in ((True, 0.6), (False, 0.0)):
            with mock.patch.object(native, 'transmission_roughness', return_value=on):
                made = moonlightipr_materials.native_surface('DwaBaseMaterial', dict(glass), lambda what: None)
                self.assertAlmostEqual(made['refraction_roughness'], expected)
        # A session started with other switches is started again: the nine above and XPU2's three (renderer, adaptive
        # passes, devices).
        self.assertEqual(len(native.source_switches()), 12)

    def test_on_the_preferences_page(self):
        page = (KIT / 'preferences.cfg').read_text(encoding='utf-8')
        self.assertIn('cmd moonray.pref.toonTerminator ?', page)
        commands = (KIT / 'lxserv/moonray_preferences.py').read_text(encoding='utf-8')
        self.assertIn("lx.bless(switch('toon_terminator'),'moonray.pref.toonTerminator')", commands)


if __name__ == '__main__':
    unittest.main()
