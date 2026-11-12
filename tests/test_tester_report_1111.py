"""A tester's report, 2026-11-11: Convert to MoonRay Rect Light reaches an installed kit's menus (moonray_menu, as
install_moonlightipr.py edits the installed layout.cfg), and a frame's .postprocess folder (its denoiser's guides) goes
once its denoised copy is made (postprocess.release). Render missing frames is in test_production.py. No Modo."""
import pathlib
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'kit/MoonRayForModo/python')]
import moonray_menu  # noqa: E402

LAYOUT = ROOT / 'kit/MoonRayForModo/layout.cfg'


class AreaLightEntries(unittest.TestCase):
    def installed(self):
        """An installed layout from before: the checkout's, without the area light's entries."""
        text = LAYOUT.read_bytes().decode('utf-8').replace('\r\n', '\n')
        begin = text.index('    <!-- Right-clicking an area light')
        text = text[:begin] + text[text.index('    <!-- Right-clicking a mesh'):]
        lines = [line for line in text.split('\n') if 'MoonRayMenu_convert_area_light' not in line]
        return '\r\n'.join(lines)

    def test_added_once_and_well_formed(self):
        before = self.installed()
        self.assertNotIn('moonray.light.convert', before)
        after = moonray_menu.area_light_entries(before)
        self.assertEqual(after.count('MoonRayAreaLightContext:sheet'), 1)
        self.assertEqual(after.count('MoonRayMenu_convert_area_light'), 1)
        self.assertEqual(moonray_menu.area_light_entries(after), after)
        self.assertNotIn('\r\r', after)
        ET.fromstring(after.encode('utf-8'))

    def test_the_checkouts_layout_has_them(self):
        text = LAYOUT.read_text(encoding='utf-8')
        self.assertIn('<atom type="Filter">Area Lights</atom>', text)
        self.assertEqual(moonray_menu.area_light_entries(text), text)


class PostprocessRelease(unittest.TestCase):
    def test_the_guides_go_and_nothing_else(self):
        from moonray_modo import postprocess
        with tempfile.TemporaryDirectory() as folder:
            folder = pathlib.Path(folder)
            frame = folder / 'shot.0001.exr'
            frame.write_bytes(b'x')
            (folder / 'shot.denoised.0001.exr').write_bytes(b'x')
            kept = folder / 'shot.0001.exr.postprocess'
            kept.mkdir()
            (kept / 'albedo.exr').write_bytes(b'x')
            postprocess.release(frame)
            self.assertEqual(sorted(p.name for p in folder.iterdir()), ['shot.0001.exr', 'shot.denoised.0001.exr'])
            postprocess.release(frame)   # nothing there: nothing said


if __name__ == '__main__':
    unittest.main()
