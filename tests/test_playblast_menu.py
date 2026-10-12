import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import moonray_menu


class PlayblastMenu(unittest.TestCase):
    def test_kit_menu_has_the_playblast_after_the_animation(self):
        text = (ROOT / 'kit/MoonRayForModo/layout.cfg').read_text(encoding='utf-8')
        self.assertEqual(text.count('cmd moonray.page playblast'), 1)
        self.assertLess(text.index('cmd moonray.page animation'), text.index('cmd moonray.page playblast'))
        self.assertLess(text.index('cmd moonray.page playblast'), text.index('cmd moonray.page bake'))

    def test_the_window_knows_the_page(self):
        text = (ROOT / 'kit/MoonRayForModo/python/moonray_modo/panel_tools.py').read_text(encoding='utf-8')
        self.assertIn("'playblast': self.render_playblast", text)
        self.assertIn("'preview', 'playblast')", text)

    def test_an_installed_menu_gains_the_entry_once(self):
        old = ('<list type="Control" val="cmd moonray.page animation">\r\n<atom type="Label">Render Animation...</atom>\r\n</list>\r\n'
               '<list type="Control" val="cmd moonray.page bake"></list>\r\n')
        new = moonray_menu.playblast_entry(old)
        self.assertEqual(new.count('cmd moonray.page playblast'), 1)
        self.assertLess(new.index('Render Animation'), new.index('MoonLightIPR Playblast...'))
        self.assertLess(new.index('MoonLightIPR Playblast...'), new.index('moonray.page bake'))
        self.assertEqual(moonray_menu.playblast_entry(new), new)


if __name__ == '__main__':
    unittest.main()
