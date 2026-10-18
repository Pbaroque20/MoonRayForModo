"""The Camera Sequence window: keys that each make a camera the one rendered through over a range of frames
(camera_sequence.py), and a strip across the scene's frames showing which camera covers which."""
from PySide2 import QtCore, QtWidgets

from . import camera_sequence

# Colours a camera's part of the strip is drawn in, in turn; frames no key covers are the render camera's grey.
SWATCHES = ('#4f8fd0', '#d08a3c', '#5aa86b', '#b05fb8', '#c9c34a', '#4bb0b0', '#c95c5c', '#8a8fd6')
UNCOVERED = '#4a4e55'


def cameras(scene):
    """Every camera a key can name, (words, identity): Modo's cameras, then MoonRay's camera items."""
    from . import camera_choice
    found = [('Modo camera: ' + item.name, item.id) for item in sorted(scene.items('camera', superType=False), key=lambda i: i.name.casefold())]
    return found + [(camera_choice.label(item), item.id) for item in camera_choice.cameras(scene)]


class CameraSequence(QtWidgets.QDialog):
    def __init__(self, parent, sequence, scene, frames, current):
        super().__init__(parent)
        self.setWindowTitle('Camera Sequence')
        self.resize(620, 460)
        self.offered = cameras(scene)
        self.frames, self.current = frames, current
        layout = QtWidgets.QVBoxLayout(self)
        words = QtWidgets.QLabel('Each key makes a camera the one rendered through from its first frame to its last: in the '
                                 'preview at the current frame, Render to a File, Render Animation and playblasts. Frames no key '
                                 'covers are rendered through the render camera.')
        words.setWordWrap(True)
        layout.addWidget(words)
        sequence = camera_sequence.normalized(sequence)
        self.enabled = QtWidgets.QCheckBox('Render through the keyed cameras')
        self.enabled.setChecked(sequence['enabled'])
        layout.addWidget(self.enabled)
        self.table = QtWidgets.QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['Camera', 'First frame', 'Last frame'])
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        layout.addWidget(self.table, 1)
        row = QtWidgets.QHBoxLayout()
        for text, act in (('Add Key', self.add), ('Remove Key', self.remove), ('Sort by Frame', self.sort)):
            button = QtWidgets.QPushButton(text)
            button.setAutoDefault(False)
            button.clicked.connect(act)
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)
        # The strip: one part for each stretch of frames, in its camera's colour, across the scene's frames.
        strip_title = QtWidgets.QLabel('Frames %d to %d' % frames)
        layout.addWidget(strip_title)
        self.strip = QtWidgets.QWidget()
        self.strip.setFixedHeight(26)
        self.strip_row = QtWidgets.QHBoxLayout(self.strip)
        self.strip_row.setContentsMargins(0, 0, 0, 0)
        self.strip_row.setSpacing(1)
        layout.addWidget(self.strip)
        self.notes = QtWidgets.QLabel()
        self.notes.setWordWrap(True)
        layout.addWidget(self.notes)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText('Save')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        for key in sequence['keys']:
            self.add_row(key)
        self.enabled.toggled.connect(self.refresh)
        self.refresh()

    def add_row(self, key):
        row = self.table.rowCount()
        self.table.insertRow(row)
        choice = QtWidgets.QComboBox()
        for words, identity in self.offered:
            choice.addItem(words, identity)
        if choice.findData(key['camera']) < 0:
            choice.addItem('(no longer in the scene)', key['camera'])
        choice.setCurrentIndex(choice.findData(key['camera']))
        choice.currentIndexChanged.connect(self.refresh)
        self.table.setCellWidget(row, 0, choice)
        for column, value in ((1, key['first']), (2, key['last'])):
            spin = QtWidgets.QSpinBox()
            spin.setRange(-100000, 100000)
            spin.setValue(int(value))
            spin.valueChanged.connect(self.refresh)
            self.table.setCellWidget(row, column, spin)

    def keys(self):
        found = []
        for row in range(self.table.rowCount()):
            camera = self.table.cellWidget(row, 0).currentData()
            first, last = self.table.cellWidget(row, 1).value(), self.table.cellWidget(row, 2).value()
            if camera:
                found.append({'camera': camera, 'first': min(first, last), 'last': max(first, last)})
        return found

    def sequence(self):
        return camera_sequence.normalized({'enabled': self.enabled.isChecked(), 'keys': self.keys()})

    def add(self):
        """A key after the last one, to the scene's last frame; the first key starts at the current frame."""
        keys = self.keys()
        first = max(key['last'] for key in keys) + 1 if keys else self.current
        last = max(first, self.frames[1])
        used = {key['camera'] for key in keys}
        camera = next((identity for _, identity in self.offered if identity not in used), self.offered[0][1] if self.offered else '')
        if not camera:
            QtWidgets.QMessageBox.information(self, 'Camera Sequence', 'The scene has no camera to key.')
            return
        self.add_row({'camera': camera, 'first': first, 'last': last})
        self.refresh()

    def remove(self):
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()} or {self.table.currentRow()}, reverse=True)
        for row in rows:
            if row >= 0:
                self.table.removeRow(row)
        self.refresh()

    def sort(self):
        keys = self.sequence()['keys']
        self.table.setRowCount(0)
        for key in keys:
            self.add_row(key)
        self.refresh()

    def refresh(self, *args):
        """Draw the strip again and say where keys overlap and what no key covers."""
        sequence = self.sequence()
        names = {identity: words.split(': ', 1)[-1] for words, identity in self.offered}
        colours = {}
        for key in sequence['keys']:
            colours.setdefault(key['camera'], SWATCHES[len(colours) % len(SWATCHES)])
        while self.strip_row.count():
            held = self.strip_row.takeAt(0).widget()
            if held is not None:
                held.deleteLater()
        first, last = self.frames
        runs, start, held = [], first, None
        for frame in range(first, last + 2):
            camera = camera_sequence.camera_at(sequence, frame) if frame <= last else object()
            if frame == first:
                held = camera
            elif camera != held:
                runs.append((start, frame - 1, held)); start, held = frame, camera
        for start, end, camera in runs:
            part = QtWidgets.QLabel(names.get(camera, '') if camera else '')
            part.setAlignment(QtCore.Qt.AlignCenter)
            part.setStyleSheet('background-color: %s; color: #101114; padding: 0 2px;' % (colours.get(camera, UNCOVERED) if camera else UNCOVERED))
            part.setToolTip('Frames %d to %d: %s' % (start, end, names.get(camera, camera) if camera else 'the render camera'))
            part.setMinimumWidth(2)
            self.strip_row.addWidget(part, end - start + 1)
        for row in range(self.table.rowCount()):
            choice = self.table.cellWidget(row, 0)
            choice.setStyleSheet('QComboBox { border-left: 6px solid %s; }' % colours.get(choice.currentData(), UNCOVERED))
        notes = []
        if not sequence['enabled']:
            notes.append('Off: everything is rendered through the render camera.')
        clashes = camera_sequence.overlaps(sequence)
        if clashes:
            keys = sequence['keys']
            notes.append('Keys overlap (%s): where they do, the one that starts later is used.' % ', '.join(
                '%d-%d with %d-%d' % (keys[a]['first'], keys[a]['last'], keys[b]['first'], keys[b]['last']) for a, b in clashes[:3]))
        holes = camera_sequence.gaps(sequence, first, last) if sequence['keys'] else []
        if holes:
            notes.append('Frames %s use the render camera.' % ', '.join('%d-%d' % hole if hole[0] != hole[1] else '%d' % hole[0] for hole in holes[:4]))
        self.notes.setText('\n'.join(notes))
