"""A small editor for the ramps on MoonRay items: stops with a position, a value and how each
blends into the next. MoonRay holds a ramp as three lists; this shows them as one thing.

The ramp is drawn across the top with a handle for each stop, and is edited there with the mouse: a handle is dragged
to move its stop (and, on a ramp of numbers, up and down to change its value), a click on the ramp adds a stop, a
double click on a handle chooses its colour, and a right click or Delete removes it. The table below holds the same
stops as numbers. Where the editor is given a way to show the ramp as it stands, every change is shown at once; OK
keeps the changes and Cancel drops them."""
from PySide2 import QtCore, QtGui, QtWidgets

from . import entities

# The room left around the ramp for its handles, and how near a click must be to a handle to mean it.
EDGE, HANDLE, NEAR = 10, 7, 9


class Preview(QtWidgets.QWidget):
    """The ramp from 0 to 1 (further where a stop lies outside), as colours or as a curve, with a handle for each stop."""

    def __init__(self, dialog):
        super().__init__(dialog)
        self.dialog = dialog
        self.setMinimumHeight(96)
        self.setMouseTracking(True)
        self.setFocusPolicy(QtCore.Qt.ClickFocus)
        self.held = None        # the row whose handle is being dragged
        self.setToolTip('Drag a handle to move its stop. Click the ramp to add one. Double-click a handle for its colour.\n'
                        'Right-click a handle, or press Delete, to remove it.' if dialog.colour else
                        'Drag a handle to move its stop and change its value. Click the ramp to add one.\n'
                        'Right-click a handle, or press Delete, to remove it.')

    # ---- Where things are ----
    def span(self):
        positions = self.dialog.lists()[0]
        low, high = min([0.0] + positions), max([1.0] + positions)
        return low, (high - low) or 1.0

    def bar(self):
        """The rectangle the ramp is drawn in: a strip of colour with the handles beneath, or the whole for a curve."""
        height = self.height() - (2 * HANDLE + 6 if self.dialog.colour else 2 * EDGE)
        return QtCore.QRect(EDGE, 2 if self.dialog.colour else EDGE, max(2, self.width() - 2 * EDGE), max(8, height))

    def top(self):
        values = self.dialog.lists()[1]
        return max([1.0] + [float(v) for v in values]) if not self.dialog.colour else 1.0

    def across(self, position):
        low, span = self.span()
        bar = self.bar()
        return bar.left() + (position - low) / span * (bar.width() - 1)

    def position_at(self, x):
        low, span = self.span()
        bar = self.bar()
        return low + span * min(1.0, max(0.0, (x - bar.left()) / float(max(1, bar.width() - 1))))

    def value_at(self, y):
        bar = self.bar()
        return self.top() * min(1.0, max(0.0, (bar.bottom() - y) / float(max(1, bar.height() - 1))))

    def handle(self, row):
        positions, values, _ = self.dialog.lists()
        bar = self.bar()
        x = self.across(positions[row])
        if self.dialog.colour:
            return QtCore.QPointF(x, bar.bottom() + HANDLE + 3)
        return QtCore.QPointF(x, bar.bottom() - (bar.height() - 1) * min(1.0, max(0.0, float(values[row]) / self.top())))

    def row_at(self, point):
        best, found = NEAR * NEAR + 1, None
        for row in range(self.dialog.table.rowCount()):
            at = self.handle(row)
            distance = (at.x() - point.x()) ** 2 + ((at.y() - point.y()) ** 2 if not self.dialog.colour else 0 if point.y() > self.bar().bottom() else 4 * NEAR * NEAR)
            if distance < best:
                best, found = distance, row
        return found

    # ---- Drawing ----
    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor(40, 40, 40))
        positions, values, modes = self.dialog.lists()
        if not positions:
            return
        bar = self.bar()
        low, span = self.span()
        top = self.top()
        last = None
        for x in range(bar.width()):
            value = entities.ramp_eval(positions, values, modes, low + span * x / float(max(1, bar.width() - 1)))
            if self.dialog.colour:
                # Shown as it is stored, brightened only by the display's own curve.
                painter.setPen(QtGui.QColor.fromRgbF(*[min(1.0, max(0.0, v)) ** (1 / 2.2) for v in value]))
                painter.drawLine(bar.left() + x, bar.top(), bar.left() + x, bar.bottom())
            else:
                y = bar.bottom() - (bar.height() - 1) * min(1.0, max(0.0, value / top))
                painter.setPen(QtGui.QColor(230, 230, 230))
                if last is not None:
                    painter.drawLine(QtCore.QPointF(bar.left() + x - 1, last), QtCore.QPointF(bar.left() + x, y))
                last = y
        painter.setPen(QtGui.QColor(90, 90, 90))
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRect(bar.adjusted(0, 0, -1, -1))
        chosen = self.dialog.current_row()
        for row in range(len(positions)):
            at = self.handle(row)
            painter.setPen(QtGui.QPen(QtGui.QColor(255, 190, 60) if row == chosen else QtGui.QColor(20, 20, 20), 2 if row == chosen else 1))
            if self.dialog.colour:
                painter.setBrush(QtGui.QColor.fromRgbF(*[min(1.0, max(0.0, v)) ** (1 / 2.2) for v in values[row]]))
                painter.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(at.x(), at.y() - HANDLE - 2), QtCore.QPointF(at.x() - HANDLE, at.y() + HANDLE - 2),
                                                     QtCore.QPointF(at.x() + HANDLE, at.y() + HANDLE - 2)]))
            else:
                painter.setBrush(QtGui.QColor(230, 230, 230))
                painter.drawEllipse(at, HANDLE - 2, HANDLE - 2)

    # ---- The mouse ----
    def mousePressEvent(self, event):
        row = self.row_at(event.pos())
        if event.button() == QtCore.Qt.RightButton:
            if row is not None:
                self.dialog.remove_row(row)
            return
        if event.button() != QtCore.Qt.LeftButton:
            return
        if row is None and self.bar().adjusted(-EDGE, 0, EDGE, 0).contains(event.pos()):
            # A stop where the ramp was clicked, with what the ramp is there (or, for a curve, as high as the click).
            positions, values, modes = self.dialog.lists()
            position = self.position_at(event.x())
            value = entities.ramp_eval(positions, values, modes, position) if positions else ([1.0, 1.0, 1.0] if self.dialog.colour else 1.0)
            if not self.dialog.colour:
                value = self.value_at(event.y())
            left = max([i for i in range(len(positions)) if positions[i] <= position], key=lambda i: positions[i], default=None)
            row = self.dialog.insert(position, value, modes[left] if left is not None else 1)
        if row is not None:
            self.held = row
            self.dialog.table.selectRow(row)
            self.update()

    def mouseMoveEvent(self, event):
        if self.held is None or self.held >= self.dialog.table.rowCount():
            self.setCursor(QtCore.Qt.PointingHandCursor if self.row_at(event.pos()) is not None else QtCore.Qt.ArrowCursor)
            return
        self.dialog.table.cellWidget(self.held, 0).setValue(round(self.position_at(event.x()), 4))
        if not self.dialog.colour:
            self.dialog.table.cellWidget(self.held, 1).setValue(round(self.value_at(event.y()), 4))

    def mouseReleaseEvent(self, event):
        self.held = None

    def mouseDoubleClickEvent(self, event):
        row = self.row_at(event.pos())
        if row is not None and self.dialog.colour:
            self.held = None
            self.dialog.pick(self.dialog.table.cellWidget(row, 1))

    def keyPressEvent(self, event):
        if event.key() in (QtCore.Qt.Key_Delete, QtCore.Qt.Key_Backspace):
            self.dialog.remove_stop()
        else:
            super().keyPressEvent(event)


class RampDialog(QtWidgets.QDialog):
    """Edits one ramp. result() gives its three lists, sorted by position. live, where given, is called with those
    lists a moment after every change, to show the ramp as it stands while it is being edited."""

    def __init__(self, title, positions, values, interpolations, colour, parent=None, live=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(480, 470)
        self.colour = colour
        self.live = live
        # Changes that come one on another's heels, as a drag's do, are shown as one.
        self.soon = QtCore.QTimer(self)
        self.soon.setSingleShot(True)
        self.soon.setInterval(30)
        self.soon.timeout.connect(self.show_live)
        layout = QtWidgets.QVBoxLayout(self)
        self.table = QtWidgets.QTableWidget(0, 3)
        self.preview = Preview(self)
        layout.addWidget(self.preview)
        self.table.setHorizontalHeaderLabels(['Position', 'Colour' if colour else 'Value', 'Blend to next'])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.itemSelectionChanged.connect(self.preview.update)
        layout.addWidget(self.table)
        row = QtWidgets.QHBoxLayout()
        add, remove = QtWidgets.QPushButton('Add stop'), QtWidgets.QPushButton('Remove stop')
        add.clicked.connect(self.add_stop)
        remove.clicked.connect(self.remove_stop)
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch(1)
        layout.addLayout(row)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if not positions:
            # A ramp that has never been set starts as a plain fade.
            positions, interpolations = [0.0, 1.0], [1, 1]
            values = [[1.0, 1.0, 1.0], [0.0, 0.0, 0.0]] if colour else [1.0, 0.0]
        self.quiet = True
        for position, value, mode in zip(positions, values, interpolations):
            self.insert(position, value, mode)
        self.quiet = False

    def touched(self, *args):
        """Something of the ramp changed: it is drawn again, and shown where it is used."""
        self.preview.update()
        if self.live is not None and not getattr(self, 'quiet', False):
            self.soon.start()

    def show_live(self):
        try:
            self.live(self.result())
        except Exception:
            pass

    def current_row(self):
        rows = {index.row() for index in self.table.selectedIndexes()}
        return min(rows) if rows else None

    def insert(self, position, value, mode):
        row = self.table.rowCount()
        self.table.insertRow(row)
        where = QtWidgets.QDoubleSpinBox()
        where.setRange(-1e6, 1e6)
        where.setDecimals(4)
        where.setSingleStep(.05)
        where.setValue(float(position))
        where.valueChanged.connect(self.touched)
        self.table.setCellWidget(row, 0, where)
        if self.colour:
            swatch = QtWidgets.QPushButton()
            swatch.rgb = [float(v) for v in value]
            swatch.clicked.connect(lambda checked=False, button=swatch: self.pick(button))
            self.paint(swatch)
            self.table.setCellWidget(row, 1, swatch)
        else:
            amount = QtWidgets.QDoubleSpinBox()
            amount.setRange(-1e6, 1e6)
            amount.setDecimals(4)
            amount.setSingleStep(.05)
            amount.setValue(float(value))
            amount.valueChanged.connect(self.touched)
            self.table.setCellWidget(row, 1, amount)
        blend = QtWidgets.QComboBox()
        blend.addItems(list(entities.INTERPOLATIONS))
        blend.setCurrentIndex(min(max(int(mode), 0), len(entities.INTERPOLATIONS) - 1))
        blend.currentIndexChanged.connect(self.touched)
        self.table.setCellWidget(row, 2, blend)
        self.touched()
        return row

    def paint(self, swatch):
        shown = [int(255 * min(1.0, max(0.0, v)) ** (1 / 2.2)) for v in swatch.rgb]
        swatch.setStyleSheet('background-color: rgb(%d, %d, %d);' % tuple(shown))
        swatch.setText('%.3g  %.3g  %.3g' % tuple(swatch.rgb))

    def pick(self, swatch):
        start = QtGui.QColor.fromRgbF(*[min(1.0, max(0.0, v)) ** (1 / 2.2) for v in swatch.rgb])
        before = list(swatch.rgb)
        chooser = QtWidgets.QColorDialog(start, self)
        chooser.setWindowTitle('Stop colour')

        def show(colour):
            # The picker works in display values; the ramp holds linear ones.
            swatch.rgb = [colour.redF() ** 2.2, colour.greenF() ** 2.2, colour.blueF() ** 2.2]
            self.paint(swatch)
            self.touched()
        # Shown as it is chosen, and put back if the choosing is given up.
        chooser.currentColorChanged.connect(show)
        if chooser.exec_() != QtWidgets.QDialog.Accepted:
            swatch.rgb = before
            self.paint(swatch)
            self.touched()

    def add_stop(self):
        positions, values, modes = self.lists()
        if len(positions) >= 2:
            # Half way along the widest gap, with the ramp's own value there.
            order = sorted(positions)
            gap = max(range(len(order) - 1), key=lambda i: order[i + 1] - order[i])
            position = (order[gap] + order[gap + 1]) / 2
            value = entities.ramp_eval(positions, values, modes, position)
        else:
            position, value = (positions[0] + 1 if positions else 0.0), ([1.0, 1.0, 1.0] if self.colour else 1.0)
        self.table.selectRow(self.insert(position, value, 1))

    def remove_row(self, row):
        if self.table.rowCount() > 1 and 0 <= row < self.table.rowCount():
            self.table.removeRow(row)
        self.touched()

    def remove_stop(self):
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True) or [self.table.rowCount() - 1]
        for row in rows:
            if self.table.rowCount() > 1 and row >= 0:
                self.table.removeRow(row)
        self.touched()

    def lists(self):
        """The stops as they stand, in table order."""
        positions, values, modes = [], [], []
        for row in range(self.table.rowCount()):
            cells = [self.table.cellWidget(row, column) for column in range(3)]
            if any(cell is None for cell in cells):
                continue    # a row being made
            positions.append(cells[0].value())
            values.append(list(cells[1].rgb) if self.colour else cells[1].value())
            modes.append(cells[2].currentIndex())
        return positions, values, modes

    def result(self):
        positions, values, modes = self.lists()
        order = sorted(range(len(positions)), key=lambda i: positions[i])
        return [positions[i] for i in order], [values[i] for i in order], [modes[i] for i in order]


def text(values):
    """A list as the item's text channel holds it, and entities.parse_list reads it back."""
    if values and isinstance(values[0], (list, tuple)):
        return '; '.join(' '.join('%.6g' % v for v in entry) for entry in values)
    return ' '.join('%.6g' % v for v in values)


def edit(title, kinds, texts, parent=None):
    """Open the editor on a ramp held as three text channels; return their new texts, or None
    if cancelled. kinds are the three attributes' types."""
    lists = []
    for kind, held in zip(kinds, texts):
        try:
            lists.append(entities.parse_list(held, kind) if held.strip() else [])
        except ValueError:
            lists.append([])
    if len({len(v) for v in lists}) != 1:
        lists = [[], [], []]
    dialog = RampDialog(title, lists[0], lists[1], lists[2], kinds[1] == 'RgbVector', parent)
    if dialog.exec_() != QtWidgets.QDialog.Accepted:
        return None
    return [text(values) for values in dialog.result()]
