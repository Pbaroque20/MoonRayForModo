"""Reference cycles are collected on Modo's main thread only (main_thread_gc). A report, 2026-11-18: Modo crashed as a
camera item was clicked during a MoonLightIPR realtime preview, in valet3000's CkptBeginBuf (Modo's undo state, kept
per thread) while a display worker of the kit's was making a threading.Timer: Python had collected a cycle holding
something of Modo's on that worker."""
import gc
import importlib.util
import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('main_thread_gc', ROOT / 'kit/MoonRayForModo/python/moonray_modo/main_thread_gc.py')
main_thread_gc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(main_thread_gc)
THRESHOLDS = (700, 10, 10)


class Due(unittest.TestCase):
    """The generation collected, as Python picks it."""

    def test_nothing_until_the_youngest_is_over(self):
        self.assertIsNone(main_thread_gc.due((700, 50, 50), THRESHOLDS))

    def test_youngest(self):
        self.assertEqual(main_thread_gc.due((701, 3, 3), THRESHOLDS), 0)

    def test_the_oldest_over_its_threshold(self):
        self.assertEqual(main_thread_gc.due((701, 11, 3), THRESHOLDS), 1)
        self.assertEqual(main_thread_gc.due((701, 11, 11), THRESHOLDS), 2)
        self.assertEqual(main_thread_gc.due((701, 0, 11), THRESHOLDS), 2)

    def test_a_full_collection_waits_where_not_allowed(self):
        self.assertEqual(main_thread_gc.due((701, 11, 11), THRESHOLDS, full_allowed=False), 1)
        self.assertEqual(main_thread_gc.due((701, 0, 11), THRESHOLDS, full_allowed=False), 0)

    def test_switched_off_by_threshold(self):
        self.assertIsNone(main_thread_gc.due((5000, 50, 50), (0, 10, 10)))


class Install(unittest.TestCase):

    def test_not_from_another_thread(self):
        answers = []
        worker = threading.Thread(target=lambda: answers.append(main_thread_gc.install()))
        worker.start()
        worker.join()
        self.assertEqual(answers, [False])
        self.assertTrue(gc.isenabled())

    def test_not_without_qt_application(self):
        try:
            from PySide2 import QtCore
        except ImportError:
            self.assertFalse(main_thread_gc.install())
            self.assertTrue(gc.isenabled())
            return
        if QtCore.QCoreApplication.instance() is not None:
            self.skipTest('a Qt application stands already')
        self.assertFalse(main_thread_gc.install())
        self.assertTrue(gc.isenabled())


class Cycle:
    """A cycle that notes the thread it is freed on."""
    freed_on = []

    def __init__(self):
        self.me = self

    def __del__(self):
        Cycle.freed_on.append(threading.current_thread().name)


@unittest.skipIf(importlib.util.find_spec('PySide2') is None, "needs PySide2 (Modo's Python, QT_QPA_PLATFORM=offscreen)")
class OnTheMainThread(unittest.TestCase):

    def test_a_worker_allocating_never_collects_and_the_main_thread_does(self):
        from PySide2 import QtCore, QtWidgets
        # Qt's widget application, as Modo has: other tests in the same process make widgets.
        application = QtCore.QCoreApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
        try:
            self.assertTrue(main_thread_gc.install())
            self.assertFalse(gc.isenabled())
            # Python's own, never a child of Qt's application: Modo frees those after Python is finalized, and crashed.
            self.assertIsNone(main_thread_gc._state['timer'].parent())
            gc.collect()
            Cycle.freed_on.clear()
            Cycle()

            def allocate():
                kept = []
                for i in range(200000):
                    kept.append([i])
                    if len(kept) > 1000:
                        kept.clear()
            worker = threading.Thread(target=allocate, name='kit worker')
            worker.start()
            worker.join()
            self.assertEqual(Cycle.freed_on, [], 'collected on the worker')
            held = [[] for _ in range(1000)]    # the youngest generation over its threshold, as live work keeps it
            deadline = time.perf_counter() + 2.0
            while not Cycle.freed_on and time.perf_counter() < deadline:
                application.processEvents()
                time.sleep(0.01)
            self.assertEqual(Cycle.freed_on, [threading.main_thread().name])
            self.assertFalse(gc.isenabled())
        finally:
            timer = main_thread_gc._state['timer']
            if timer is not None:
                timer.stop()
            main_thread_gc._state['timer'] = None
            gc.enable()


if __name__ == '__main__':
    unittest.main()
