import os
import pathlib
import subprocess
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import native


class LowLatency(unittest.TestCase):
    def test_all_threads_becomes_all_but_one(self):
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_LOW_LATENCY': '1'}), mock.patch('os.cpu_count', return_value=12):
            self.assertEqual(native.render_threads(0), 11)
            self.assertEqual(native.render_threads(6), 6)            # a count set by hand is kept
            args = native.arguments('scene.rdla', 'out.exr', 0, 'xpu')
            self.assertEqual(args[args.index('-threads') + 1], '11')
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_LOW_LATENCY': '1'}), mock.patch('os.cpu_count', return_value=4):
            self.assertEqual(native.render_threads(0), 0)            # a small processor keeps them all
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_LOW_LATENCY': '0'}), mock.patch('os.cpu_count', return_value=12):
            self.assertEqual(native.render_threads(0), 0)
            self.assertNotIn('-threads', native.arguments('scene.rdla', 'out.exr', 0, 'xpu'))

    @unittest.skipUnless(os.name == 'nt', 'Windows priority classes')
    def test_a_renderer_is_put_below_normal_priority(self):
        import ctypes
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        try:
            with mock.patch.dict(os.environ, {'MOONRAY_MODO_LOW_LATENCY': '1'}):
                self.assertTrue(native.lower_priority(child.pid))
            kernel = ctypes.windll.kernel32
            handle = kernel.OpenProcess(0x0400, False, child.pid)      # PROCESS_QUERY_INFORMATION
            try:
                self.assertEqual(kernel.GetPriorityClass(handle), 0x4000)
            finally:
                kernel.CloseHandle(handle)
            with mock.patch.dict(os.environ, {'MOONRAY_MODO_LOW_LATENCY': '0'}):
                self.assertFalse(native.lower_priority(child.pid))
        finally:
            child.kill()
            child.wait()


if __name__ == '__main__':
    unittest.main()
