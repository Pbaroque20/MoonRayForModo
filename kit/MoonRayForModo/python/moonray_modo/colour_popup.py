"""The kit's own colour picker: a small popup beside the swatch clicked, in place of Windows' colour dialog.

A square of saturation and brightness for the hue chosen on the strip beside it, the colour's numbers as red, green and
blue and as hue, saturation and value (each dragged as the graph's numbers are, scrub_field, or typed), its hex code,
and the colour it had beside the colour it has: a click on the old one puts it back. The colour follows each move, so
the graph and the preview show it as it is chosen, and all of it is one step to undo. OK (or Enter, or a click outside)
keeps it; Cancel (or Esc) puts back the colour it had.

Colours here are as they are shown (0 to 1 each, as the swatches and the graph's numbers are): the caller turns them
into what it keeps."""
import colorsys
from PySide2 import QtCore, QtGui, QtWidgets
from .scrub_field import ScrubSpinBox, _drag

SQUARE = 168
STRIP = 18


def _clamp(value):
    return min(1.0, max(0.0, float(value)))


class _Square(QtWidgets.QWidget):
    """Saturation across, value up, for one hue."""
    moved = QtCore.Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(SQUARE, SQUARE)
        self.setCursor(QtCore.Qt.CrossCursor)
        self.hue, self.saturation, self.value = 0.0, 0.0, 0.0
        self._image = None
        self._image_hue = None

    def set_hsv(self, hue, saturation, value):
        self.hue, self.saturation, self.value = hue, saturation, value
        self.update()

    def _picture(self):
        if self._image is None or self._image_hue != self.hue:
            size = self.width()
            image = QtGui.QImage(size, size, QtGui.QImage.Format_RGB32)
            for y in range(size):
                v = 1.0 - y / (size - 1.0)
                for x in range(size):
                    r, g, b = colorsys.hsv_to_rgb(self.hue, x / (size - 1.0), v)
                    image.setPixel(x, y, QtGui.qRgb(int(r * 255 + .5), int(g * 255 + .5), int(b * 255 + .5)))
            self._image, self._image_hue = image, self.hue
        return self._image

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.drawImage(0, 0, self._picture())
        x = self.saturation * (self.width() - 1)
        y = (1.0 - self.value) * (self.height() - 1)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0), 3))
        painter.drawEllipse(QtCore.QPointF(x, y), 5, 5)
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255), 1.5))
        painter.drawEllipse(QtCore.QPointF(x, y), 5, 5)

    def _at(self, event):
        self.moved.emit(_clamp(event.pos().x() / (self.width() - 1.0)), _clamp(1.0 - event.pos().y() / (self.height() - 1.0)))

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._at(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & QtCore.Qt.LeftButton:
            self._at(event)


class _Strip(QtWidgets.QWidget):
    """The hues, red at the top round to red at the bottom."""
    moved = QtCore.Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(STRIP, SQUARE)
        self.setCursor(QtCore.Qt.SizeVerCursor)
        self.hue = 0.0

    def set_hue(self, hue):
        self.hue = hue
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        gradient = QtGui.QLinearGradient(0, 0, 0, self.height())
        for step in range(7):
            r, g, b = colorsys.hsv_to_rgb(step / 6.0 % 1.0, 1, 1)
            gradient.setColorAt(step / 6.0, QtGui.QColor.fromRgbF(r, g, b))
        painter.fillRect(self.rect(), gradient)
        y = self.hue * (self.height() - 1)
        painter.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0), 3))
        painter.drawLine(0, int(y), self.width(), int(y))
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255), 1))
        painter.drawLine(0, int(y), self.width(), int(y))

    def _at(self, event):
        self.moved.emit(_clamp(event.pos().y() / (self.height() - 1.0)))

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._at(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & QtCore.Qt.LeftButton:
            self._at(event)


class _Lightness(_Strip):
    """The colour's lightness: white at the top, the colour itself halfway, black at the bottom (as Windows' colour
    dialog has it). moved gives the lightness, 0 at the bottom to 1 at the top."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lightness = 0.5
        self.middle = (0.5, 0.5, 0.5)

    def set_colour(self, hue, saturation, lightness):
        self.middle = colorsys.hls_to_rgb(hue, 0.5, saturation)
        self.lightness = lightness
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        gradient = QtGui.QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0.0, QtGui.QColor(255, 255, 255))
        gradient.setColorAt(0.5, QtGui.QColor.fromRgbF(*self.middle))
        gradient.setColorAt(1.0, QtGui.QColor(0, 0, 0))
        painter.fillRect(self.rect(), gradient)
        y = (1.0 - self.lightness) * (self.height() - 1)
        painter.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0), 3))
        painter.drawLine(0, int(y), self.width(), int(y))
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255), 1))
        painter.drawLine(0, int(y), self.width(), int(y))

    def _at(self, event):
        self.moved.emit(1.0 - _clamp(event.pos().y() / (self.height() - 1.0)))


class _Swatch(QtWidgets.QWidget):
    clicked = QtCore.Signal()

    def __init__(self, tip, parent=None):
        super().__init__(parent)
        self.setFixedHeight(22)
        self.setToolTip(tip)
        self.colour = QtGui.QColor(0, 0, 0)

    def set_colour(self, rgb):
        self.colour = QtGui.QColor.fromRgbF(*[_clamp(v) for v in rgb])
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), self.colour)
        painter.setPen(QtGui.QColor('#15171a'))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()


class ColourPopup(QtWidgets.QDialog):
    """The picker. changed: the colour at each move (shown, 0 to 1). chosen(): the colour kept, or None after Esc."""
    changed = QtCore.Signal(tuple)

    def __init__(self, rgb, parent=None, title=''):
        super().__init__(parent, QtCore.Qt.Popup | QtCore.Qt.FramelessWindowHint)
        self.setObjectName('MoonRayColourPopup')
        self.setStyleSheet('#MoonRayColourPopup { border: 1px solid #15171a; }')
        self.original = tuple(_clamp(v) for v in rgb[:3])
        self.rgb = self.original
        self.escaped = False
        self._busy = False
        self.hue, self.saturation, self.value = colorsys.rgb_to_hsv(*self.rgb)
        # The lightness bar's saturation (HLS), kept through white and black, where the colour has none to give.
        _l, l_s = colorsys.rgb_to_hls(*self.rgb)[1:]
        self.hls_saturation = l_s if 1e-6 < _l < 1 - 1e-6 else 1.0
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSizeConstraint(QtWidgets.QLayout.SetFixedSize)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        if title:
            label = QtWidgets.QLabel(title)
            label.setStyleSheet('font-weight: bold;')
            layout.addWidget(label)
        top = QtWidgets.QHBoxLayout()
        top.setSpacing(6)
        self.square = _Square()
        self.strip = _Strip()
        self.strip.setToolTip('Hue')
        self.lightness = _Lightness()
        self.lightness.setToolTip('Lightness: white at the top, the colour halfway, black at the bottom')
        top.addWidget(self.square)
        top.addWidget(self.strip)
        top.addWidget(self.lightness)
        top.addStretch(1)
        layout.addLayout(top)
        swatches = QtWidgets.QHBoxLayout()
        swatches.setSpacing(0)
        self.old = _Swatch('The colour it had: click to put it back')
        self.new = _Swatch('The colour it has')
        swatches.addWidget(self.old)
        swatches.addWidget(self.new)
        layout.addLayout(swatches)
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(3)
        self.fields = {}
        for row, names in enumerate((('R', 'G', 'B'), ('H', 'S', 'V'))):
            for column, name in enumerate(names):
                spin = ScrubSpinBox()
                spin.setRange(0.0, 360.0 if name == 'H' else 1.0)
                spin.setDecimals(1 if name == 'H' else 3)
                spin.setSingleStep(1.0 if name == 'H' else .01)
                spin.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
                spin.setKeyboardTracking(False)
                spin.setFixedWidth(56)
                spin.setToolTip({'R': 'Red', 'G': 'Green', 'B': 'Blue', 'H': 'Hue, in degrees', 'S': 'Saturation',
                                 'V': 'Value (brightness)'}[name] + ': drag to change, Ctrl finer, Shift coarser')
                caption = QtWidgets.QLabel(name)
                caption.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                grid.addWidget(caption, row, 2 * column)
                grid.addWidget(spin, row, 2 * column + 1)
                spin.valueChanged.connect(lambda _value, kind=row: self._typed(kind))
                self.fields[name] = spin
        layout.addLayout(grid)
        hex_row = QtWidgets.QHBoxLayout()
        hex_row.addWidget(QtWidgets.QLabel('Hex'))
        self.hex = QtWidgets.QLineEdit()
        self.hex.setMaxLength(7)
        self.hex.setToolTip('The colour as a hex code, #rrggbb')
        self.hex.editingFinished.connect(self._hex_typed)
        hex_row.addWidget(self.hex, 1)
        layout.addLayout(hex_row)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        self.ok = QtWidgets.QPushButton('OK')
        self.ok.setToolTip('Keep this colour (Enter)')
        self.ok.setAutoDefault(False)
        self.ok.clicked.connect(self.accept)
        self.cancel = QtWidgets.QPushButton('Cancel')
        self.cancel.setToolTip('Put back the colour it had (Esc)')
        self.cancel.setAutoDefault(False)
        self.cancel.clicked.connect(self.put_back)
        buttons.addWidget(self.ok)
        buttons.addWidget(self.cancel)
        layout.addLayout(buttons)
        self.square.moved.connect(self._square_moved)
        self.strip.moved.connect(self._strip_moved)
        self.lightness.moved.connect(self._lightness_moved)
        self.old.clicked.connect(lambda: self._set_rgb(self.original))
        self.old.set_colour(self.original)
        self._show()

    # What was moved or typed, and everything else brought to it.
    def _set_rgb(self, rgb, hsv=None):
        rgb = tuple(_clamp(v) for v in rgb)
        if hsv is None:
            hue, saturation, value = colorsys.rgb_to_hsv(*rgb)
            # A grey or black keeps the hue (and a black the saturation) it had, as the square is left where it was.
            if saturation <= 1e-6 or value <= 1e-6:
                hue = self.hue
            if value <= 1e-6:
                saturation = self.saturation
            hsv = (hue, saturation, value)
        self.hue, self.saturation, self.value = hsv
        changed = rgb != self.rgb
        self.rgb = rgb
        self._show()
        if changed:
            self.changed.emit(self.rgb)

    def _square_moved(self, saturation, value):
        self._set_rgb(colorsys.hsv_to_rgb(self.hue, saturation, value), (self.hue, saturation, value))

    def _strip_moved(self, hue):
        self._set_rgb(colorsys.hsv_to_rgb(hue, self.saturation, self.value), (hue, self.saturation, self.value))

    def _lightness_moved(self, lightness):
        self._set_rgb(colorsys.hls_to_rgb(self.hue, lightness, self.hls_saturation))

    def _typed(self, kind):
        if self._busy:
            return
        if kind == 0:
            self._set_rgb(tuple(self.fields[n].value() for n in 'RGB'))
        else:
            hsv = (self.fields['H'].value() / 360.0 % 1.0 if self.fields['H'].value() < 360.0 else 1.0 - 1e-9,
                   self.fields['S'].value(), self.fields['V'].value())
            self._set_rgb(colorsys.hsv_to_rgb(*hsv), hsv)

    def _hex_typed(self):
        text = self.hex.text().strip().lstrip('#')
        if len(text) == 3:
            text = ''.join(c * 2 for c in text)
        try:
            if len(text) != 6:
                raise ValueError(text)
            self._set_rgb(tuple(int(text[i:i + 2], 16) / 255.0 for i in (0, 2, 4)))
        except ValueError:
            self._show()

    def _show(self):
        self._busy = True
        try:
            for name, part in zip('RGB', self.rgb):
                if abs(self.fields[name].value() - part) > 5e-4:
                    self.fields[name].setValue(part)
            for name, part in zip('HSV', (self.hue * 360.0, self.saturation, self.value)):
                if abs(self.fields[name].value() - part) > 5e-4:
                    self.fields[name].setValue(part)
            self.hex.setText(QtGui.QColor.fromRgbF(*self.rgb).name())
        finally:
            self._busy = False
        self.square.set_hsv(self.hue, self.saturation, self.value)
        self.strip.set_hue(self.hue)
        lightness, saturation = colorsys.rgb_to_hls(*self.rgb)[1:]
        if 1e-6 < lightness < 1 - 1e-6:
            self.hls_saturation = saturation
        self.lightness.set_colour(self.hue, self.hls_saturation, lightness)
        self.new.set_colour(self.rgb)

    def put_back(self):
        """Cancel (or Esc): the colour it had, said to the caller, and the popup closed."""
        self.escaped = True
        if self.rgb != self.original:
            self.rgb = self.original
            self.changed.emit(self.original)
        self.reject()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.put_back()
            return
        if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            # Enter in a field takes its number; in the hex line its code; a second Enter keeps the colour.
            focus = self.focusWidget()
            if isinstance(focus, QtWidgets.QLineEdit) and focus is not self.hex and focus.isModified():
                focus.setModified(False)
                return super().keyPressEvent(event)
            self.accept()
            return
        super().keyPressEvent(event)

    def chosen(self):
        return None if self.escaped else self.rgb

    def place(self, anchor):
        """Beside the widget clicked (below it, or above where the screen ends), on the screen it is on."""
        self.adjustSize()
        if anchor is None:
            point = QtGui.QCursor.pos()
            below, above = point, point
        else:
            below = anchor.mapToGlobal(QtCore.QPoint(0, anchor.height() + 2))
            above = anchor.mapToGlobal(QtCore.QPoint(0, -2))
        screen = QtWidgets.QApplication.desktop().availableGeometry(below)
        size = self.sizeHint()
        x = min(max(screen.left(), below.x()), screen.right() - size.width())
        y = below.y() if below.y() + size.height() <= screen.bottom() else max(screen.top(), above.y() - size.height())
        self.move(x, y)


def pick(rgb, parent=None, anchor=None, live=None, title=''):
    """The colour chosen, starting from rgb (shown, 0 to 1): a tuple, or None where Esc put it back (or nothing
    changed). live, if given, is called with each colour as it is chosen (and with rgb again after Esc); its calls are
    one drag (scrub_field), so that an editor keeps them as one step to undo."""
    popup = ColourPopup(rgb, parent, title)
    if live is not None:
        popup.changed.connect(lambda value: live(value))
    popup.place(anchor)
    _drag['number'] += 1
    _drag['active'] = _drag['held'] = True
    try:
        popup.exec_()
    finally:
        _drag['active'] = _drag['held'] = False
    chosen = popup.chosen()
    if chosen is None or chosen == popup.original:
        return None
    return chosen
