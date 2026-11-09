"""A number changed by dragging on it, as Modo's own fields are: the preview window's EV and gamma, and the MoonShine
graph's numbers.

Qt's spin box changes only from its small arrows, held to repeat slowly, or by typing; a tester found sliding slow and
the arrows hard to hit, a few pixels apart, each going one way only. Pressed anywhere on this one, the number or its
arrows, and dragged, it steps as the pointer goes: one step for every few pixels right or up (left or down for less), a
tenth of one with Ctrl held, five with Shift. A click that does not drag is a click as before: on the number it puts the
cursor in it to type, on an arrow it steps once. An arrow held still no longer repeats: dragging is the quicker way.

While a drag goes on, scrub_in_progress() says which drag it is, so that an editor can keep all its steps as one undo.
"""
from PySide2 import QtCore, QtWidgets

_drag = {'number': 0, 'active': False}


def scrub_in_progress():
    """A number for the drag going on now, the same through all its steps, or None when no field is being dragged."""
    return _drag['number'] if _drag['active'] else None


class _Scrub:
    """The dragging, shared by the field for decimals and the one for whole numbers."""
    PIXELS = 4          # pixels of drag to a step
    THRESHOLD = 3       # pixels a press may wander and still be a click

    def _scrub_setup(self):
        # (where the press was, the value then, what was pressed: 0 the number, 1 or -1 an arrow)
        self._press = None
        self._scrubbing = False
        edit = self.lineEdit()
        edit.installEventFilter(self)
        edit.setCursor(QtCore.Qt.SizeHorCursor)
        self.setCursor(QtCore.Qt.SizeHorCursor)

    def scrub_value(self, start, pixels, modifiers=QtCore.Qt.NoModifier):
        """The value a drag of so many pixels from start comes to, kept within the field's range."""
        step = self.singleStep()
        if modifiers & QtCore.Qt.ControlModifier:
            step *= .1
        elif modifiers & QtCore.Qt.ShiftModifier:
            step *= 5
        value = start + int(pixels / self.PIXELS) * step
        decimals = self.decimals() if hasattr(self, 'decimals') else 0
        value = round(value, decimals) if decimals else int(round(value))
        return min(self.maximum(), max(self.minimum(), value))

    def _arrow(self, position):
        """1 for the up arrow at a point of the field, -1 for the down one, 0 for anything else."""
        option = QtWidgets.QStyleOptionSpinBox()
        self.initStyleOption(option)
        control = self.style().hitTestComplexControl(QtWidgets.QStyle.CC_SpinBox, option, position, self)
        return 1 if control == QtWidgets.QStyle.SC_SpinBoxUp else -1 if control == QtWidgets.QStyle.SC_SpinBoxDown else 0

    # A press, a drag and a release, on the number (through its line edit) or on the field itself (its arrows).
    def _pressed(self, event, kind):
        if event.button() != QtCore.Qt.LeftButton:
            return False
        self._press = (event.globalPos(), self.value(), kind)
        self._scrubbing = False
        return True

    def _moved(self, event):
        if self._press is None:
            return False
        moved = event.globalPos() - self._press[0]
        # Right or up for more: along whichever way the pointer went further.
        pixels = moved.x() if abs(moved.x()) >= abs(moved.y()) else -moved.y()
        if not self._scrubbing and abs(pixels) < self.THRESHOLD:
            return True
        if not self._scrubbing:
            self._scrubbing = True
            _drag['number'] += 1
            _drag['active'] = True
        value = self.scrub_value(self._press[1], pixels, event.modifiers())
        if abs(value - self.value()) > 1e-12:
            self.setValue(value)
        return True

    def _released(self, event, edit=None):
        if self._press is None or event.button() != QtCore.Qt.LeftButton:
            return False
        scrubbed, kind = self._scrubbing, self._press[2]
        self._press, self._scrubbing = None, False
        if scrubbed:
            _drag['active'] = False
            if edit is not None and edit.hasFocus():
                edit.deselect()
        elif kind:
            # A click on an arrow: one step.
            self.stepBy(kind)
        elif edit is not None:
            # A click on the number: into it, to type a value; the cursor placed where it was clicked if it was in it.
            if edit.hasFocus():
                edit.setCursorPosition(edit.cursorPositionAt(event.pos()))
            else:
                edit.setFocus(QtCore.Qt.MouseFocusReason)
                edit.selectAll()
        return True

    def eventFilter(self, watched, event):
        if watched is not self.lineEdit():
            return super().eventFilter(watched, event)
        kind = event.type()
        if kind == QtCore.QEvent.MouseButtonPress and self._pressed(event, 0):
            return True
        if kind == QtCore.QEvent.MouseMove and self._moved(event):
            return True
        if kind == QtCore.QEvent.MouseButtonRelease and self._released(event, watched):
            return True
        if kind == QtCore.QEvent.FocusOut:
            watched.setCursor(QtCore.Qt.SizeHorCursor)
        elif kind == QtCore.QEvent.FocusIn:
            watched.setCursor(QtCore.Qt.IBeamCursor)
        return super().eventFilter(watched, event)

    def hideEvent(self, event):
        # A field taken away mid-drag (another node chosen) ends its drag, so that nothing waits on its release.
        if self._scrubbing:
            self._press, self._scrubbing = None, False
            _drag['active'] = False
        super().hideEvent(event)

    def mousePressEvent(self, event):
        if not self._pressed(event, self._arrow(event.pos())):
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self._moved(event):
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if not self._released(event, self.lineEdit()):
            super().mouseReleaseEvent(event)


class ScrubSpinBox(_Scrub, QtWidgets.QDoubleSpinBox):
    def __init__(self, parent=None):
        QtWidgets.QDoubleSpinBox.__init__(self, parent)
        self._scrub_setup()


class ScrubIntBox(_Scrub, QtWidgets.QSpinBox):
    def __init__(self, parent=None):
        QtWidgets.QSpinBox.__init__(self, parent)
        self._scrub_setup()
