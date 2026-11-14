"""The kit's colour popup (colour_popup), offscreen: a move in the square, on the hue strip, a dragged number and a hex
code each give the colour they should and are followed live; Esc puts the colour back; the scrub fields inside it stay
one drag (one undo) while it is open. Also writes test-results/colour-popup/popup.png, a picture of it.

Run with Modo's Python (PySide2):
  "C:\\Program Files\\Modo16.1v9\\modo\\resrc\\python3kit\\extra64\\python.exe" -S tools/check_colour_popup.py
with PYTHONHOME/PYTHONPATH and QT_QPA_PLATFORM=offscreen as moonlight-dev-environment says (this script sets the Qt
ones)."""
import colorsys
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODO = pathlib.Path(r'C:\Program Files\Modo16.1v9\modo')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QPA_PLATFORM_PLUGIN_PATH', str(MODO / 'qtplugins/platforms'))
for folder in (MODO, MODO / 'resrc/python3kit/extra64'):
    if folder.is_dir() and hasattr(os, 'add_dll_directory'):
        os.add_dll_directory(str(folder))
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))

from PySide2 import QtCore, QtGui, QtWidgets  # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
from moonray_modo import colour_popup, scrub_field  # noqa: E402

failures = []


def mouse(widget, kind, point, buttons=QtCore.Qt.LeftButton):
    button = QtCore.Qt.NoButton if kind == QtCore.QEvent.MouseMove else QtCore.Qt.LeftButton
    held = buttons if kind != QtCore.QEvent.MouseButtonRelease else QtCore.Qt.NoButton
    event = QtGui.QMouseEvent(kind, QtCore.QPointF(point), QtCore.QPointF(widget.mapToGlobal(point)), button, held,
                              QtCore.Qt.NoModifier)
    QtWidgets.QApplication.sendEvent(widget, event)


def click(widget, point):
    mouse(widget, QtCore.QEvent.MouseButtonPress, point)
    mouse(widget, QtCore.QEvent.MouseButtonRelease, point)


def near(a, b, what, tolerance=2e-3):
    if any(abs(x - y) > tolerance for x, y in zip(a, b)):
        failures.append('%s: %s, expected %s' % (what, [round(v, 4) for v in a], [round(v, 4) for v in b]))


seen = []
popup = colour_popup.ColourPopup((0.8, 0.2, 0.1), None, 'Base color')
popup.changed.connect(seen.append)
popup.place(None)
popup.show()
app.processEvents()

# The square: right edge, top: full saturation and value of the hue.
hue = popup.hue
click(popup.square, QtCore.QPoint(popup.square.width() - 1, 0))
near(popup.rgb, colorsys.hsv_to_rgb(hue, 1, 1), 'square corner')
# The strip, a third down: green.
click(popup.strip, QtCore.QPoint(5, round((popup.strip.height() - 1) / 3.0)))
near(popup.rgb, (0, 1, 0), 'strip at a third', 2e-2)
# Typed numbers: red field.
popup.fields['R'].setValue(0.5)
near(popup.rgb, (0.5, 1, 0), 'red field', 2e-2)
# A dragged number, as scrub_field drags it: right 40 pixels is 10 steps of 0.01.
field = popup.fields['B']
start = field.value()
edit = field.lineEdit()
centre = edit.rect().center()
mouse(edit, QtCore.QEvent.MouseButtonPress, centre)
# The popup as pick() opens it: one drag held.
scrub_field._drag['held'] = scrub_field._drag['active'] = True
number = scrub_field._drag['number']
mouse(edit, QtCore.QEvent.MouseMove, centre + QtCore.QPoint(40, 0))
mouse(edit, QtCore.QEvent.MouseButtonRelease, centre + QtCore.QPoint(40, 0))
if abs(field.value() - (start + 0.1)) > 1e-6:
    failures.append('dragged blue: %s from %s' % (field.value(), start))
if scrub_field.scrub_in_progress() != number:
    failures.append('a drag inside the popup ended its held drag')
scrub_field._drag['held'] = scrub_field._drag['active'] = False
near(popup.rgb, (0.5, 1, start + 0.1), 'after the drag', 2e-2)
# Hex.
popup.hex.setText('#336699')
popup.hex.editingFinished.emit()
near(popup.rgb, (0x33 / 255.0, 0x66 / 255.0, 0x99 / 255.0), 'hex')
if not seen or tuple(seen[-1]) != popup.rgb:
    failures.append('changed did not follow the colour')
# The picture, for a look.
folder = ROOT / 'test-results/colour-popup'
folder.mkdir(parents=True, exist_ok=True)
popup.grab().save(str(folder / 'popup.png'))
# Esc: the colour it had, said to the caller.
QtWidgets.QApplication.sendEvent(popup, QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Escape, QtCore.Qt.NoModifier))
if popup.chosen() is not None or tuple(seen[-1]) != popup.original:
    failures.append('Esc did not put the colour back')
# The buttons: Cancel puts the colour back as Esc does, OK keeps it.
for button, kept in (('cancel', False), ('ok', True)):
    told = []
    other = colour_popup.ColourPopup((0.8, 0.2, 0.1))
    other.changed.connect(told.append)
    other.show()
    other._strip_moved(0.5)
    getattr(other, button).click()
    if other.isVisible():
        failures.append('%s did not close the popup' % button)
    if kept and (other.chosen() is None or other.chosen() == other.original):
        failures.append('OK did not keep the colour')
    if not kept and (other.chosen() is not None or tuple(told[-1]) != other.original):
        failures.append('Cancel did not put the colour back')
# The lightness bar: the top is white, halfway the colour at full lightness 0.5, the bottom black; through white and
# back the colour comes back.
light = colour_popup.ColourPopup((0.8, 0.2, 0.1))
light.show()
height = light.lightness.height() - 1
click(light.lightness, QtCore.QPoint(5, 0))
near(light.rgb, (1, 1, 1), 'lightness top')
click(light.lightness, QtCore.QPoint(5, height))
near(light.rgb, (0, 0, 0), 'lightness bottom')
click(light.lightness, QtCore.QPoint(5, round(height * (1 - 0.45))))
near(light.rgb, (0.8, 0.2, 0.1), 'lightness back to the colour', 2e-2)
light.close()
# A grey keeps its hue in the square.
grey = colour_popup.ColourPopup((0.5, 0.5, 0.5))
grey._strip_moved(0.6)
grey.fields['V'].setValue(0.3)
if abs(grey.hue - 0.6) > 1e-6:
    failures.append('a grey lost its hue: %s' % grey.hue)

# In the graph: a colour field's swatch opens the popup, the field follows it, and the whole visit is one undo, as one
# drag of a number is (remember, as the graph editor has it, on a stand-in editor).
import types  # noqa: E402
from unittest import mock  # noqa: E402
for name in ('lx', 'lxu', 'lxu.command', 'lxu.object', 'lxu.select', 'lxifc', 'modo', 'modo.constants'):
    sys.modules.setdefault(name, mock.MagicMock())
from moonray_modo.node_editor import Editor as NodeEditor  # noqa: E402
from moonray_modo.node_widgets import VectorField  # noqa: E402
editor = types.SimpleNamespace(undo_states=[], redo_states=[], graph={'v': None},
                               material_preview=types.SimpleNamespace(graph_changed=lambda g: None), publish_soon=lambda: None)


def take(i, k, l, v):
    before = dict(editor.graph)
    editor.graph = {'v': [round(x, 4) for x in v]}
    NodeEditor.remember(editor, before)


def visit(moves, escape):
    """The popup as a user goes through it: moves on the square, then Esc or a click outside."""
    def run(self):
        for s in moves:
            self._square_moved(s, 0.5)
        if escape:
            QtWidgets.QApplication.sendEvent(self, QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Escape, QtCore.Qt.NoModifier))
        return 0
    return mock.patch.object(colour_popup.ColourPopup, 'exec_', run)


field = VectorField('n1', 'base_color', -1, {'type': 'Rgb', 'default': 'Rgb(0.18, 0.18, 0.18)'}, [0.18, 0.18, 0.18])
field.changed.connect(take)
with visit([0.2, 0.5, 0.9], False):
    field.choose()
if len(editor.undo_states) != 1:
    failures.append('a colour picked in the popup is %d undo steps, not 1' % len(editor.undo_states))
if abs(field.spins[1].value() - field.spins[0].value()) < 1e-3:
    failures.append('the field did not take the colour picked')
picked = field.value()
with visit([0.3, 0.7], True):
    field.choose()
if any(abs(a - b) > 1e-6 for a, b in zip(field.value(), picked)):
    failures.append('Esc did not put the field back: %s, was %s' % (field.value(), picked))
if scrub_field.scrub_in_progress() is not None:
    failures.append('a drag is left going on after the popup')

print('\n'.join(failures) if failures else 'colour popup: all checks passed')
sys.exit(1 if failures else 0)
