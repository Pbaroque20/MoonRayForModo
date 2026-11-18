"""The MoonRay Source Overrides are on when their variable is not set, so moonray.exe started by hand (a headless render,
a farm) renders as Modo does; the kit sets every one to 1 or 0, so in Modo the preferences still decide."""
import importlib.util
import os
import re
import sys
import unittest
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import native

spec = importlib.util.spec_from_file_location('port_switches_default_on', ROOT / 'tools/port_switches_default_on.py')
defaults = importlib.util.module_from_spec(spec)
spec.loader.exec_module(defaults)
PATCHES = ROOT / 'patches/native-windows'


class SwitchesOnByDefault(unittest.TestCase):
    def test_the_patches_read_every_switch_as_on_unless_0(self):
        reads = 0
        for path in PATCHES.glob('*.patch'):
            text = path.read_text(encoding='utf-8')
            self.assertIsNone(defaults.OLD_READ.search(text), path.name)
            self.assertIsNone(re.search(defaults.VARIABLE + '=1', text), path.name)
            reads += len(defaults.NEW_READ.findall(text))
        self.assertEqual(reads, sum(defaults.READS.values()))
        named = set()
        for path in PATCHES.glob('*.patch'):
            named.update(re.findall(r'getenv\("MOONRAY_MODO_(\w+)"\)', path.read_text(encoding='utf-8')))
        self.assertEqual(named - {'SESSION', 'CL1_POOL_SCALE'}, set(defaults.SWITCHES))

    def test_the_port_tools_write_the_new_reading(self):
        for path in (ROOT / 'tools').glob('port_*.py'):
            text = path.read_text(encoding='utf-8')
            if path.name == 'port_camera_light_lpe.py':
                # Its first form's reading, which it takes out of a tree, is the one left.
                self.assertEqual(len(defaults.OLD_READ.findall(text)), 1)
            else:
                self.assertIsNone(defaults.OLD_READ.search(text), path.name)
        self.assertIn("return !value || value[0] != '0';", (ROOT / 'tools/port_source_switches.py').read_text(encoding='utf-8'))

    def test_the_kit_sets_every_switch(self):
        for on in (True, False):
            with mock.patch.dict(os.environ, {}), mock.patch.object(native, '_switch', lambda key, variable: on):
                env = native.environment(ROOT)
            for name in defaults.SWITCHES:
                self.assertEqual(env['MOONRAY_MODO_' + name], '1' if on else '0', name)


if __name__ == '__main__':
    unittest.main()
