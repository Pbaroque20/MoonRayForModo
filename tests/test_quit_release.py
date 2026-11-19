"""What Modo holds of the kit's is let go of as Modo quits, while Python still stands (quit_release). Modo crashed on
the way out in python39.dll (PyErr_Occurred, PyDict_Pop) under lxPython3.lx's exit code: listeners the kit had added
for good were still held, and freed after Python was finalized."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location('quit_release', ROOT / 'kit/MoonRayForModo/python/moonray_modo/quit_release.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeLx:
    """lx as listen() and release() use it: Unknown makes a new COM object at every call, as Modo's Python does."""
    def __enter__(self):
        self.added, self.removed = [], []
        self.missing = False
        fake = self

        class Unknown:
            def __init__(self, held):
                self.held = held

        class Service:
            def AddListener(self, com):
                fake.added.append(com)

            def RemoveListener(self, com):
                if com not in fake.added:
                    raise LookupError('not found')
                fake.removed.append(com)

        lx = types.ModuleType('lx')
        lx.object = types.SimpleNamespace(Unknown=Unknown)
        lx.service = types.SimpleNamespace(Listener=Service)
        self.kept = sys.modules.get('lx')
        sys.modules['lx'] = lx
        return self

    def __exit__(self, *exc):
        if self.kept is None:
            sys.modules.pop('lx', None)
        else:
            sys.modules['lx'] = self.kept


class Release(unittest.TestCase):

    def test_listeners_are_taken_out_by_the_com_object_modo_was_given(self):
        quit_release = load()
        with FakeLx() as lx:
            first, second = object(), object()
            com_first = quit_release.listen(first)
            com_second = quit_release.listen(second)
            self.assertEqual(lx.added, [com_first, com_second])
            self.assertIs(com_first.held, first)
            quit_release.release()
            self.assertEqual(lx.removed, [com_second, com_first])
            self.assertTrue(quit_release.released[0])
            quit_release.release()       # twice is harmless
            self.assertEqual(lx.removed, [com_second, com_first])

    def test_tables_are_forgotten(self):
        quit_release = load()
        clients = {'form': 'event'}
        quit_release.forget(clients.clear)
        with FakeLx():
            quit_release.release()
        self.assertEqual(clients, {})

    def test_a_fault_stops_nothing_else(self):
        quit_release = load()
        clients = {'form': 'event'}

        def fails():
            raise RuntimeError('Modo is quitting')
        quit_release.forget(clients.clear)
        quit_release.forget(fails)
        with FakeLx() as lx:
            quit_release.listen(object())
            lx.added.clear()         # Modo no longer knows it: RemoveListener raises
            quit_release.release()
        self.assertEqual(clients, {})

    def test_not_hooked_without_qt_application(self):
        quit_release = load()
        try:
            from PySide2 import QtCore
        except ImportError:
            self.assertFalse(quit_release.hook())
            return
        if QtCore.QCoreApplication.instance() is not None:
            self.skipTest('a Qt application stands already')
        self.assertFalse(quit_release.hook())


@unittest.skipIf(importlib.util.find_spec('PySide2') is None, "needs PySide2 (Modo's Python, QT_QPA_PLATFORM=offscreen)")
class Windows(unittest.TestCase):
    """At Python's exit the kit's windows are destroyed, found among the wrappers Python holds; no other window is."""

    def test_the_kits_windows_go_and_no_other(self):
        from PySide2 import QtWidgets
        import shiboken2
        from PySide2 import QtCore
        standing = QtCore.QCoreApplication.instance()
        if standing is not None and not isinstance(standing, QtWidgets.QApplication):
            self.skipTest('a Qt application without widgets stands already')
        application = standing or QtWidgets.QApplication(sys.argv[:1])
        quit_release = load()
        KitWindow = type('KitWindow', (QtWidgets.QWidget,), {'__module__': 'moonray_modo.fake'})
        kits = KitWindow()
        inside = QtWidgets.QLabel('held', kits)          # a child of the kit's window, not a window itself
        other = QtWidgets.QWidget()                       # a window of someone else's
        with FakeLx():
            quit_release.windows()
        self.assertFalse(shiboken2.isValid(kits))
        self.assertFalse(shiboken2.isValid(inside))
        self.assertTrue(shiboken2.isValid(other))
        self.assertEqual(quit_release.destroyed, ['KitWindow'])
        self.assertTrue(quit_release.released[0])
        other.deleteLater()


class Wired(unittest.TestCase):
    """Every listener the kit adds for good goes through listen(), and every notifier's table through forget()."""

    def test_no_listener_added_around_it(self):
        kit = ROOT / 'kit/MoonRayForModo'
        direct = []
        for path in list((kit / 'lxserv').glob('*.py')) + list((kit / 'python/moonray_modo').glob('*.py')):
            if path.name == 'quit_release.py':
                continue
            text = path.read_text(encoding='utf-8')
            if 'AddListener(' in text and path.name != 'changes.py':    # the panel's own, taken out as it closes
                direct.append(path.name)
        self.assertEqual(direct, [])

    def test_every_notifier_table_is_forgotten(self):
        kit = ROOT / 'kit/MoonRayForModo'
        missing = []
        for path in list((kit / 'lxserv').glob('*.py')) + list((kit / 'python/moonray_modo').glob('*.py')):
            text = path.read_text(encoding='utf-8')
            for line in text.splitlines():
                if line.startswith('class ') and '(lxifc.Notifier)' in line:
                    name = line.split()[1].split('(')[0]
                    if 'quit_release.forget(%s.clients.clear)' % name not in text:
                        missing.append('%s.%s' % (path.name, name))
        self.assertEqual(missing, [])


if __name__ == '__main__':
    unittest.main()
