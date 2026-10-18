import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import display, modo_color

CONFIG = '''ocio_profile_version: 1
roles:
  scene_linear: linear
displays:
  default:
    - !<View> {name: None, colorspace: raw}
    - !<View> {name: sRGB, colorspace: sRGB}
    - !<View> {name: rec709, colorspace: rec709}
active_displays: [default]
active_views: [sRGB, rec709, None]
colorspaces:
  - !<ColorSpace>
    name: linear
'''


class ModoColor(unittest.TestCase):
    def tearDown(self):
        modo_color.RESOLVED = None

    def test_what_modo_stores_names_the_space_after_the_configuration(self):
        self.assertEqual(modo_color.space('nuke-default:sRGB'), 'sRGB')
        self.assertEqual(modo_color.space('linear'), 'linear')

    def test_the_views_of_a_configuration_are_read(self):
        displays, first = modo_color.views(CONFIG)
        self.assertEqual(first, 'default')
        self.assertEqual(displays['default'][1], ('sRGB', 'sRGB'))

    def test_the_view_is_the_one_whose_space_is_the_outputs(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / 'config.ocio'
            path.write_text(CONFIG, encoding='utf-8')
            held = modo_color.resolve(path, 'linear', 'rec709')
            self.assertEqual((held['source'], held['display'], held['view']), ('linear', 'default', 'rec709'))
            self.assertIsNone(modo_color.resolve(path, 'linear', 'AdobeRGB'))

    def test_the_display_follows_what_was_read(self):
        modo_color.RESOLVED = {'config': 'C:/configs/config.ocio', 'source': 'linear', 'display': 'default', 'view': 'sRGB'}
        values = display.values({})
        self.assertEqual((values['view'], values['config'], values['source'], values['display'], values['ocio_view']),
                         ('ocio', 'C:/configs/config.ocio', 'linear', 'default', 'sRGB'))

    def test_with_nothing_read_the_display_is_plain_srgb(self):
        modo_color.RESOLVED = None
        self.assertEqual(display.values({})['view'], 'srgb')

    def test_a_scene_set_to_aces_stays_aces(self):
        modo_color.RESOLVED = {'config': 'x', 'source': 'linear', 'display': 'default', 'view': 'sRGB'}
        self.assertEqual(display.values({'view': 'aces'})['config'], display.ACES_CONFIG)

    def test_aces_2_is_its_own_view(self):
        chosen = display.values({'view': 'aces2'})
        self.assertEqual((chosen['view'], chosen['config'], chosen['ocio_view']),
                         ('ocio', display.ACES2_CONFIG, 'ACES 2.0 - SDR 100 nits (Rec.709)'))
        self.assertNotEqual(display.values({'view': 'aces'})['ocio_view'], chosen['ocio_view'])

    def test_what_was_last_chosen_is_what_a_scene_starts_with(self):
        from moonray_modo import display_memory, scene_settings
        self.assertEqual(display_memory.remembered(), {})       # nothing is read outside Modo
        display_memory._held = {'view': 'aces'}
        try:
            self.assertEqual(scene_settings.complete({})['display']['view'], 'aces')
            self.assertEqual(scene_settings.complete({'display': {'view': 'srgb'}})['display']['view'], 'srgb')
        finally:
            display_memory._held = None


if __name__ == '__main__':
    unittest.main()
