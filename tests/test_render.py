"""Lifecycle tests run inside Modo's Qt runtime by the host probe."""
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
try:
    from PySide2 import QtCore
    from moonray_modo.render import Renderer
except ImportError:
    QtCore = None


@unittest.skipIf(QtCore is None, 'Run inside Modo for the Qt lifecycle tests')
class RenderTests(unittest.TestCase):
    def setUp(self):
        self.app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])
        self.renderer = Renderer()
        self.renderer.active = {'output': None, 'generation': 3}
        self.renderer.passes = []
        self.renderer.image_path = pathlib.Path(self.renderer.directory.name) / 'render.png'
        self.errors, self.images = [], []
        self.renderer.failed.connect(self.errors.append)
        self.renderer.image_ready.connect(self.images.append)

    def tearDown(self):
        self.renderer.close()

    def test_crash_never_publishes_partial_output(self):
        self.renderer.image_path.write_bytes(b'partial' * 10)
        self.renderer._exited(0xC000001D, QtCore.QProcess.CrashExit)
        self.assertFalse(self.images)
        self.assertIn('unsupported CPU instruction', self.errors[0])

    def test_zero_byte_output_is_not_success(self):
        self.renderer.image_path.touch()
        self.renderer._exited(0, QtCore.QProcess.NormalExit)
        self.assertTrue(self.errors)
        self.assertFalse(self.images)

    def test_stop_discards_late_completion(self):
        self.renderer.image_path.write_bytes(b'not_a_real_image' * 3)
        self.renderer.stop()
        self.renderer._exited(0, QtCore.QProcess.NormalExit)
        self.assertFalse(self.images)
        self.assertFalse(self.errors)

    def test_stale_refinement_callback_does_not_start(self):
        self.renderer._begin_pass(2)
        self.assertEqual(self.renderer.process.state(), QtCore.QProcess.NotRunning)

    def test_failed_render_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            final = pathlib.Path(directory) / 'final.exr'
            final.write_bytes(b'previous render')
            self.renderer.active['output'] = str(final)
            self.renderer._exited(1, QtCore.QProcess.NormalExit)
            self.assertEqual(final.read_bytes(), b'previous render')

    def test_final_copy_failure_is_reported(self):
        self.renderer.image_path.write_bytes(b'not_a_real_image' * 3)
        self.renderer.active['output'] = str(pathlib.Path(self.renderer.directory.name) / 'missing' / 'final.exr')
        self.renderer._exited(0, QtCore.QProcess.NormalExit)
        self.assertIn('Cannot save render', self.errors[0])
