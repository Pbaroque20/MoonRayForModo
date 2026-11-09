"""A MoonLightIPR Playblast leaves realtime off when its frames are done or it is stopped (2026-11-08: RT stayed On after a
playblast with nothing updating, until another engine was chosen and this one chosen again)."""
import importlib
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))


class Signal:
    def __init__(self, *types_):
        self.slots = []

    def __get__(self, owner, kind=None):
        return self if owner is None else owner.__dict__.setdefault('_signal_%d' % id(self), Signal())

    def connect(self, slot):
        self.slots.append(slot)

    def disconnect(self, slot):
        self.slots.remove(slot)

    def emit(self, *values):
        for slot in list(self.slots):
            slot(*values)


class Timer:
    def __init__(self, *parent):
        self.timeout = Signal()

    def setInterval(self, value):
        pass

    def start(self):
        pass

    def stop(self):
        pass


class Check:
    """The window's hidden realtime switch."""
    def __init__(self, on):
        self.on = on

    def isChecked(self):
        return self.on

    def setChecked(self, on):
        self.on = on


def load():
    """The playblast module read with stand-ins for Qt and Modo, taken away again so other tests find what they did."""
    qt = types.ModuleType('PySide2')
    qt.QtCore = types.SimpleNamespace(QObject=type('QObject', (), {'__init__': lambda self, *a: None}), Signal=Signal, QTimer=Timer)
    qt.QtGui = types.SimpleNamespace()
    qt.QtWidgets = types.SimpleNamespace(QDialog=object, QWidget=object)
    saved = {name: sys.modules.get(name) for name in ('PySide2', 'lx', 'moonray_modo.animation', 'moonray_modo.playblast')}
    sys.modules['PySide2'] = qt
    sys.modules['lx'] = types.SimpleNamespace(eval=lambda command: None)
    sys.modules['moonray_modo.animation'] = types.SimpleNamespace(active=None)
    sys.modules.pop('moonray_modo.playblast', None)
    try:
        return importlib.import_module('moonray_modo.playblast')
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        for name in ('playblast', 'animation'):
            vars(sys.modules['moonray_modo']).pop(name, None)


class Renderer:
    def __init__(self):
        self.finished, self.failed = Signal(), Signal()
        self.moonlightipr_samples = None
        self.stopped = 0

    def stop(self):
        self.stopped += 1


class Panel:
    def __init__(self, realtime):
        self.renderer = Renderer()
        self.ipr_mode = Check(realtime)
        self.status = types.SimpleNamespace(setText=lambda text: setattr(self, 'said', text))
        self.synced = 0

    def _sync_rt(self):
        self.synced += 1


class PlayblastRealtime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playblast = load()

    def running(self, realtime=True):
        panel = Panel(realtime)
        blast = self.playblast.Playblast(panel, ROOT / 'test-results', 1, 3, 24.0)
        blast.running = True
        panel.renderer.finished.connect(blast.finished)
        panel.renderer.failed.connect(blast.failed)
        return panel, blast

    def test_stopped_it_leaves_realtime_off_and_rt_saying_so(self):
        panel, blast = self.running()
        blast.stop()
        self.assertFalse(panel.ipr_mode.isChecked())
        self.assertEqual(panel.synced, 1)
        self.assertEqual(panel.renderer.stopped, 1)

    def test_a_failed_frame_leaves_realtime_off(self):
        panel, blast = self.running()
        blast.failed('the card ran out')
        self.assertFalse(panel.ipr_mode.isChecked())
        self.assertEqual(panel.said, 'Playblast stopped: the card ran out')

    def test_stopping_twice_does_nothing_more(self):
        panel, blast = self.running(realtime=False)
        blast.stop()
        blast.stop()
        self.assertEqual((panel.synced, panel.renderer.stopped), (1, 1))

    def test_the_window_ends_realtime_before_the_playblast_starts(self):
        text = (ROOT / 'kit/MoonRayForModo/python/moonray_modo/panel_tools.py').read_text(encoding='utf-8')
        body = text[text.index('def render_playblast'):text.index('def copy_image')]
        self.assertLess(body.index('self.ipr_mode.setChecked(False)'), body.index('self.stop()'))


if __name__ == '__main__':
    unittest.main()
