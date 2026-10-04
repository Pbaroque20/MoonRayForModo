"""Deferred Qt lifetime checks. Run only in a compatible PySide2 environment."""
import sys,tempfile,unittest
from pathlib import Path
try:
    from PySide2 import QtCore,QtWidgets
except ImportError:raise unittest.SkipTest('Requires the Modo-compatible PySide2 environment')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo.buffer_cache import BufferCache,_retired_workers
from moonray_modo.viewer import SoftwarePreview

class SlowWorker(QtCore.QThread):
    def run(self):self.msleep(2800)

class PreviewLifetime0326(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    def test_close_keeps_worker_inputs_until_exit(self):
        cache=BufferCache();worker=SlowWorker(cache);cache.worker=worker
        worker.finished.connect(cache._memory_finished)
        folder=cache.root;worker.start();cache.close()
        self.assertTrue(folder.exists());self.assertTrue(_retired_workers)
        loop=QtCore.QEventLoop();QtCore.QTimer.singleShot(1500,loop.quit);loop.exec_()
        self.assertFalse(folder.exists());self.assertFalse(_retired_workers)
        cache.deleteLater()
    def test_graph_viewer_does_not_allocate_opengl_widget(self):
        viewer=SoftwarePreview();self.assertNotIsInstance(viewer,QtWidgets.QOpenGLWidget)
        viewer.close();viewer.deleteLater()

class DisplayThreadCompletion(unittest.TestCase):
    def test_finished_signal_waits_for_native_thread_exit(self):
        app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        class Finishing(QtCore.QThread):
            fully_stopped=False
            outcome=(None,0,0,'unused')
            def wait(self,timeout=0):return self.fully_stopped
        cache=BufferCache();worker=Finishing(cache);cache.worker=worker
        cache._memory_finished()
        self.assertIs(cache.worker,worker);self.assertTrue(cache.worker_poll.isActive())
        worker.fully_stopped=True;cache._memory_finished()
        self.assertIsNone(cache.worker);self.assertFalse(cache.worker_poll.isActive())
        cache.close();cache.deleteLater()

if __name__=='__main__':unittest.main()
