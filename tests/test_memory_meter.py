"""The preview window's memory meter (memory_meter.py): the machine's RAM, a process's memory and the graphics card's
read from Windows and the driver, and the meter's text, tooltip and warning colours from them. Runs without Qt: a stand-in
for the few PySide2 classes the meter uses."""
import os
import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))


class _Label:
    def __init__(self, parent=None):
        self.text, self.tip, self.enabled = '', '', True

    def setEnabled(self, on): self.enabled = on
    def setTextFormat(self, _): pass
    def setText(self, text): self.text = text
    def setToolTip(self, tip): self.tip = tip


class _Timer:
    def __init__(self, parent=None):
        self.timeout = types.SimpleNamespace(connect=lambda f: None)

    def setInterval(self, _): pass
    def start(self): pass


def _stub_qt():
    if 'PySide2' in sys.modules:
        return
    qt = types.ModuleType('PySide2')
    qt.QtCore = types.SimpleNamespace(QTimer=_Timer, Qt=types.SimpleNamespace(RichText=1))
    qt.QtWidgets = types.SimpleNamespace(QLabel=_Label)
    sys.modules['PySide2'] = qt
    sys.modules['PySide2.QtCore'] = qt.QtCore
    sys.modules['PySide2.QtWidgets'] = qt.QtWidgets


try:
    import PySide2  # noqa: F401
    _STUBBED = False
except ImportError:
    _stub_qt()
    _STUBBED = True
from moonray_modo import memory_meter  # noqa: E402
if _STUBBED:
    # The stand-in only for the meter: the other tests tell a machine without Qt by PySide2 failing to import.
    for name in ('PySide2', 'PySide2.QtCore', 'PySide2.QtWidgets'):
        sys.modules.pop(name, None)


@unittest.skipUnless(os.name == 'nt', 'Windows memory readers')
class MemoryMeter(unittest.TestCase):
    def test_machine_ram(self):
        total, free = memory_meter.machine()
        self.assertGreater(total, 1 << 30)
        self.assertTrue(0 < free <= total)

    def test_this_process(self):
        resident, committed = memory_meter.process(os.getpid())
        self.assertGreater(resident, 1 << 20)
        self.assertGreater(committed, 1 << 20)
        self.assertIsNone(memory_meter.process(0))

    def test_card_reads_or_is_absent(self):
        held = memory_meter.card().memory()
        if held is not None:
            total, used = held
            self.assertTrue(0 < used <= total)

    @unittest.skipIf(not isinstance(memory_meter.MemoryMeter.__mro__[1], type) or memory_meter.QtWidgets.QLabel is not _Label,
                     'with the real Qt the widget is checked in Modo')
    def test_meter_text_and_shortage(self):
        meter = memory_meter.MemoryMeter(lambda: [os.getpid()])
        self.assertIn('Renderer', meter.text)
        self.assertIn('RAM', meter.text)
        self.assertIn('free', meter.tip)
        # Short of RAM: amber, and said so.
        real = memory_meter.machine
        memory_meter.machine = lambda: (64 * (1 << 30), 6 * (1 << 30))
        try:
            meter.refresh()
        finally:
            memory_meter.machine = real
        self.assertIn(memory_meter.COLOURS[1], meter.text)
        self.assertTrue(meter.enabled)
        self.assertIn('running short', meter.tip)
        # Nothing running: the renderer left out.
        meter.processes = lambda: []
        meter.refresh()
        self.assertNotIn('Renderer', meter.text)


if __name__ == '__main__':
    unittest.main()
