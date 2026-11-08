"""Offscreen Qt check that the MoonShine graph's numbers drag as the preview window's EV does (scrub_field): a decimal
NumericField and a whole-number IntegerField step with the pointer, Ctrl finer, from the number or the arrows, and a
whole drag is one undo in the graph editor's remember(). Run with Modo's Python as check_scrub_field.py is."""
import os, sys, types
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'kit', 'MoonRayForModo', 'python'))
from PySide2 import QtCore, QtGui, QtWidgets
application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
from moonray_modo import scrub_field
from moonray_modo.node_widgets import NumericField, IntegerField

results = {}


def drag(field, dx, modifiers=QtCore.Qt.NoModifier, on_edit=True):
    target = field.lineEdit() if on_edit else field
    start = QtCore.QPoint(10, 8)
    if not on_edit:
        option = QtWidgets.QStyleOptionSpinBox(); field.initStyleOption(option)
        start = field.style().subControlRect(QtWidgets.QStyle.CC_SpinBox, option, QtWidgets.QStyle.SC_SpinBoxDown, field).center()

    def send(kind, point, buttons):
        application.sendEvent(target, QtGui.QMouseEvent(kind, point, target.mapToGlobal(point), QtCore.Qt.LeftButton if kind != QtCore.QEvent.MouseMove else QtCore.Qt.NoButton, buttons, modifiers))
    send(QtCore.QEvent.MouseButtonPress, start, QtCore.Qt.LeftButton)
    for step in range(1, 11):
        send(QtCore.QEvent.MouseMove, start + QtCore.QPoint(int(dx * step / 10), 0), QtCore.Qt.LeftButton)
    send(QtCore.QEvent.MouseButtonRelease, start + QtCore.QPoint(dx, 0), QtCore.Qt.NoButton)
    application.processEvents()


number = NumericField('n1', 'roughness', -1, {'type': 'Float'}, 0.5)
number.resize(120, 22); number.show(); application.processEvents()
seen = []
number.changed.connect(lambda i, k, l, v: seen.append(v))
drag(number, 40); results['float right 40 px'] = round(number.value(), 6)
drag(number, -40); results['float back left'] = round(number.value(), 6)
drag(number, 40, QtCore.Qt.ControlModifier); results['float Ctrl right 40 px'] = round(number.value(), 6)
results['float published each step'] = len(seen) >= 20
number.setValue(0.5); drag(number, 40, on_edit=False); results['float from the down arrow, right'] = round(number.value(), 6)

whole = IntegerField('n1', 'samples', -1, {'type': 'Int', 'min': 0, 'max': 64}, 4)
whole.resize(120, 22); whole.show(); application.processEvents()
drag(whole, 40); results['int right 40 px'] = whole.value()
drag(whole, -400); results['int past the bottom'] = whole.value()

# One drag, one undo: remember() as the graph editor has it, on a stand-in editor. Modo's own modules are stood in for.
from unittest import mock
for name in ('lx', 'lxu', 'lxu.command', 'lxu.object', 'lxu.select', 'lxifc', 'modo', 'modo.constants'):
    sys.modules.setdefault(name, mock.MagicMock())
from moonray_modo.node_editor import Editor as NodeEditor
editor = types.SimpleNamespace(undo_states=[], redo_states=[], graph={'v': 0},
                               material_preview=types.SimpleNamespace(graph_changed=lambda g: None), publish_soon=lambda: None)
remember = NodeEditor.remember
field = NumericField('n1', 'k', -1, {'type': 'Float'}, 0.0)
field.resize(120, 22); field.show(); application.processEvents()


def take(i, k, l, v):
    before = dict(editor.graph); editor.graph = {'v': v}; remember(editor, before)
field.changed.connect(take)
drag(field, 40); results['one drag, undo states'] = len(editor.undo_states)
drag(field, 40); results['two drags, undo states'] = len(editor.undo_states)
results['undo goes back to before the drag'] = editor.undo_states[-1] == {'v': 1.0}
field.setValue(5.0); results['a typed value, undo states'] = len(editor.undo_states)
results['no drag going on after'] = scrub_field.scrub_in_progress() is None

expected = {'float right 40 px': 1.5, 'float back left': 0.5, 'float Ctrl right 40 px': 0.6, 'float published each step': True,
            'float from the down arrow, right': 1.5, 'int right 40 px': 14, 'int past the bottom': 0,
            'one drag, undo states': 1, 'two drags, undo states': 2, 'undo goes back to before the drag': True,
            'a typed value, undo states': 3, 'no drag going on after': True}
bad = {k: (results.get(k), v) for k, v in expected.items() if results.get(k) != v}
print(results)
print('OK' if not bad else 'FAILED %s' % bad)
sys.exit(1 if bad else 0)
