"""Offscreen Qt check of scrub_field.ScrubSpinBox (the preview window's EV and gamma): a drag across the number steps
it, Ctrl finer and Shift coarser, within its range; a click without a drag only puts the cursor in it. Run with Modo's
Python as moonlight-dev-environment says (QT_QPA_PLATFORM=offscreen)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'kit', 'MoonRayForModo', 'python'))
from PySide2 import QtCore, QtGui, QtWidgets
application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
from moonray_modo.scrub_field import ScrubSpinBox

field = ScrubSpinBox()
field.setRange(-20, 20); field.setSingleStep(.25); field.setValue(0)
field.resize(120, 24); field.show(); application.processEvents()
edit = field.lineEdit()
seen = []
field.valueChanged.connect(seen.append)


def send(kind, point, buttons, button=QtCore.Qt.LeftButton, modifiers=QtCore.Qt.NoModifier):
    event = QtGui.QMouseEvent(kind, point, edit.mapToGlobal(point), button, buttons, modifiers)
    application.sendEvent(edit, event)


def drag(dx, modifiers=QtCore.Qt.NoModifier):
    start = QtCore.QPoint(20, 10)
    send(QtCore.QEvent.MouseButtonPress, start, QtCore.Qt.LeftButton)
    for step in range(1, 11):
        point = start + QtCore.QPoint(int(dx * step / 10), 0)
        event = QtGui.QMouseEvent(QtCore.QEvent.MouseMove, point, edit.mapToGlobal(point), QtCore.Qt.NoButton, QtCore.Qt.LeftButton, modifiers)
        application.sendEvent(edit, event)
    send(QtCore.QEvent.MouseButtonRelease, start + QtCore.QPoint(dx, 0), QtCore.Qt.NoButton)
    application.processEvents()


results = {}
drag(40); results['right 40 px'] = field.value()               # 10 steps of .25
drag(-80); results['left 80 px'] = field.value()               # 20 steps back
field.setValue(0); drag(40, QtCore.Qt.ControlModifier); results['Ctrl right 40 px'] = field.value()
field.setValue(0); drag(40, QtCore.Qt.ShiftModifier); results['Shift right 40 px'] = field.value()
field.setValue(19); drag(400); results['past the top'] = field.value()
field.setValue(1); count = len(seen)
send(QtCore.QEvent.MouseButtonPress, QtCore.QPoint(20, 10), QtCore.Qt.LeftButton)
send(QtCore.QEvent.MouseButtonRelease, QtCore.QPoint(20, 10), QtCore.Qt.NoButton); application.processEvents()
results['click keeps value'] = field.value(); results['click changed nothing'] = len(seen) == count
results['click puts the cursor in it'] = edit.hasFocus()
# The arrows: dragged from, and clicked.
option = QtWidgets.QStyleOptionSpinBox(); field.initStyleOption(option)
up = field.style().subControlRect(QtWidgets.QStyle.CC_SpinBox, option, QtWidgets.QStyle.SC_SpinBoxUp, field).center()
down = field.style().subControlRect(QtWidgets.QStyle.CC_SpinBox, option, QtWidgets.QStyle.SC_SpinBoxDown, field).center()


def on_field(kind, point, buttons):
    event = QtGui.QMouseEvent(kind, point, field.mapToGlobal(point), QtCore.Qt.LeftButton, buttons, QtCore.Qt.NoModifier)
    application.sendEvent(field, event)


field.setValue(0)
on_field(QtCore.QEvent.MouseButtonPress, up, QtCore.Qt.LeftButton)
for step in range(1, 11):
    on_field(QtCore.QEvent.MouseMove, up + QtCore.QPoint(4 * step, 0), QtCore.Qt.LeftButton)
on_field(QtCore.QEvent.MouseButtonRelease, up + QtCore.QPoint(40, 0), QtCore.Qt.NoButton); application.processEvents()
results['drag from the up arrow'] = field.value()
field.setValue(0)
on_field(QtCore.QEvent.MouseButtonPress, down, QtCore.Qt.LeftButton)
for step in range(1, 11):
    on_field(QtCore.QEvent.MouseMove, down - QtCore.QPoint(0, 2 * step), QtCore.Qt.LeftButton)
on_field(QtCore.QEvent.MouseButtonRelease, down - QtCore.QPoint(0, 20), QtCore.Qt.NoButton); application.processEvents()
results['drag up from the down arrow'] = field.value()
field.setValue(0)
on_field(QtCore.QEvent.MouseButtonPress, up, QtCore.Qt.LeftButton); on_field(QtCore.QEvent.MouseButtonRelease, up, QtCore.Qt.NoButton)
results['click the up arrow'] = field.value()
on_field(QtCore.QEvent.MouseButtonPress, down, QtCore.Qt.LeftButton); on_field(QtCore.QEvent.MouseButtonRelease, down, QtCore.Qt.NoButton)
on_field(QtCore.QEvent.MouseButtonPress, down, QtCore.Qt.LeftButton); on_field(QtCore.QEvent.MouseButtonRelease, down, QtCore.Qt.NoButton)
results['then the down arrow twice'] = field.value()
expected = {'drag from the up arrow': 2.5, 'drag up from the down arrow': 1.25, 'click the up arrow': .25, 'then the down arrow twice': -.25,
            'right 40 px': 2.5, 'left 80 px': -2.5, 'Ctrl right 40 px': .25, 'Shift right 40 px': 12.5, 'past the top': 20.0,
            'click keeps value': 1.0, 'click changed nothing': True, 'click puts the cursor in it': True}
bad = {k: (results[k], v) for k, v in expected.items() if results[k] != v}
print(results)
print('OK' if not bad else 'FAILED %s' % bad)
sys.exit(1 if bad else 0)
