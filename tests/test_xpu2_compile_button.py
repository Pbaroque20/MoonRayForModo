"""Compile XPU2 Shaders: pressed, the button and the state say Compiling, however soon the compile is over. No Modo."""
import importlib.util
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo'


def load():
    lx = types.ModuleType('lx')
    lx.bless = lambda *args: None
    lxu = types.ModuleType('lxu')
    command = types.ModuleType('lxu.command')
    command.BasicCommand = object
    lxu.command = command
    lxifc = types.ModuleType('lxifc')
    lxifc.Notifier = object
    with patch.dict(sys.modules, {'lx': lx, 'lxu': lxu, 'lxu.command': command, 'lxifc': lxifc}):
        spec = importlib.util.spec_from_file_location('moonray_xpu2_under_test', ROOT / 'lxserv/moonray_xpu2.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class CompileButton(unittest.TestCase):
    def setUp(self):
        self.module = load()
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        native = types.ModuleType('moonray_modo.native')
        native.xpu2_shaders_log = lambda: Path(self.folder.name) / 'xpu2-shaders.log'
        native.xpu2_shaders_state = lambda: ('stale', 'new programs')
        package = types.ModuleType('moonray_modo')
        package.native = native
        patcher = patch.dict(sys.modules, {'moonray_modo': package, 'moonray_modo.native': native})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_button_says_what_it_is_doing(self):
        self.assertEqual(self.module.button_name('Out of date (new programs)'), 'Compile XPU2 Shaders')
        self.assertEqual(self.module.button_name('Not compiled'), 'Compile XPU2 Shaders')
        self.assertEqual(self.module.button_name('Compiling 40%'), 'Compiling XPU2 Shaders...')
        self.assertEqual(self.module.button_name(self.module.UP_TO_DATE), 'Re-compile XPU2 Shaders')

    def test_out_of_date_until_pressed(self):
        self.assertTrue(self.module.state().startswith('Out of date'))

    def test_a_compile_over_at_once_still_says_compiling_for_a_moment(self):
        self.module._pressed[0] = time.monotonic()
        self.assertEqual(self.module.state(), 'Compiling 0%')
        self.module._pressed[0] = time.monotonic() - self.module.SHOWN_AT_LEAST - 1
        self.assertTrue(self.module.state().startswith('Out of date'))


if __name__ == '__main__':
    unittest.main()
