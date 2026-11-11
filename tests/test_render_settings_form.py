"""The Render item's form (kit/MoonRayForModo/render_settings.cfg) is what tools/generate_render_forms.py makes from
moonray_modo/scene_settings.py, byte for byte: a setting or label changed in one and not the other fails here."""
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class Form(unittest.TestCase):
    def test_generated_form_is_the_kit_form(self):
        with tempfile.TemporaryDirectory() as folder:
            made = pathlib.Path(folder) / 'render_settings.cfg'
            subprocess.run([sys.executable, str(ROOT / 'tools/generate_render_forms.py'), str(made)], check=True, capture_output=True)
            kit = (ROOT / 'kit/MoonRayForModo/render_settings.cfg').read_bytes().replace(b'\r\n', b'\n')
            self.assertEqual(made.read_bytes().replace(b'\r\n', b'\n'), kit,
                             'run tools/generate_render_forms.py: the form and scene_settings.py differ')


if __name__ == '__main__':
    unittest.main()
