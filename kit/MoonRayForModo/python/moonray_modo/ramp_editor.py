"""A small editor for the ramps on MoonRay items: stops with a position, a value and how each
blends into the next. MoonRay holds a ramp as three lists; this shows them as one thing."""
from PySide2 import QtCore, QtGui, QtWidgets

from . import entities


class Preview(QtWidgets.QWidget):
    """The ramp from its first stop to its last, as colours or as a curve."""

    def __init__(self, dialog):
        super().__init__(dialog)
        self.dialog = dialog
        self.setMinimumHeight(48)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor(40, 40, 40))
        positions, values, modes = self.dialog.lists()
        if not positions:
            return
        low, high = min(positions), max(positions)
        span = (high - low) or 1.0
        width, height = max(self.width(), 2), self.height()
        last = None
        for x in range(width):
            value = entities.ramp_eval(positions, values, modes, low + span * x / (width - 1))
            if self.dialog.colour:
                # Shown as it is stored, brightened only by the display's own curve.
                painter.setPen(QtGui.QColor.fromRgbF(*[min(1.0, max(0.0, v)) ** (1 / 2.2) for v in value]))
                painter.drawLine(x, 0, x, height)
            else:
                top = max(max(values), 1e-9)
                y = height - 1 - int((height - 2) * min(1.0, max(0.0, value / top)))
                painter.setPen(QtGui.QColor(230, 230, 230))
                if last is not None:
                    painter.drawLine(x - 1, last, x, y)
                last = y


class RampDialog(QtWidgets.QDialog):
    """Edits one ramp. result() gives its three lists, sorted by position."""

    def __init__(self, title, positions, values, interpolations, colour, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(460, 420)
        self.colour = colour
        layout = QtWidgets.QVBoxLayout(self)
        self.preview = Preview(self)
        layout.addWidget(self.preview)
        self.table = QtWidgets.QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['Position', 'Colour' if colour else 'Value', 'Blend to next'])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
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
        for position, value, mode in zip(positions, values, interpolations):
            self.insert(position, value, mode)

    def insert(self, position, value, mode):
        row = self.table.rowCount()
        self.table.insertRow(row)
        where = QtWidgets.QDoubleSpinBox()
        where.setRange(-1e6, 1e6)
        where.setDecimals(4)
        where.setSingleStep(.05)
        where.setValue(float(position))
        where.valueChanged.connect(self.preview.update)
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
            amount.valueChanged.connect(self.preview.update)
            self.table.setCellWidget(row, 1, amount)
        blend = QtWidgets.QComboBox()
        blend.addItems(list(entities.INTERPOLATIONS))
        blend.setCurrentIndex(min(max(int(mode), 0), len(entities.INTERPOLATIONS) - 1))
        blend.currentIndexChanged.connect(self.preview.update)
        self.table.setCellWidget(row, 2, blend)
        self.preview.update()

    def paint(self, swatch):
        shown = [int(255 * min(1.0, max(0.0, v)) ** (1 / 2.2)) for v in swatch.rgb]
        swatch.setStyleSheet('background-color: rgb(%d, %d, %d);' % tuple(shown))
        swatch.setText('%.3g  %.3g  %.3g' % tuple(swatch.rgb))

    def pick(self, swatch):
        start = QtGui.QColor.fromRgbF(*[min(1.0, max(0.0, v)) ** (1 / 2.2) for v in swatch.rgb])
        chosen = QtWidgets.QColorDialog.getColor(start, self, 'Stop colour')
        if chosen.isValid():
            # The picker works in display values; the ramp holds linear ones.
            swatch.rgb = [chosen.redF() ** 2.2, chosen.greenF() ** 2.2, chosen.blueF() ** 2.2]
            self.paint(swatch)
            self.preview.update()

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
        self.insert(position, value, 1)

    def remove_stop(self):
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True) or [self.table.rowCount() - 1]
        for row in rows:
            if self.table.rowCount() > 1 and row >= 0:
                self.table.removeRow(row)
        self.preview.update()

    def lists(self):
        """The stops as they stand, in table order."""
        positions, values, modes = [], [], []
        for row in range(self.table.rowCount()):
            positions.append(self.table.cellWidget(row, 0).value())
            cell = self.table.cellWidget(row, 1)
            values.append(list(cell.rgb) if self.colour else cell.value())
            modes.append(self.table.cellWidget(row, 2).currentIndex())
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
