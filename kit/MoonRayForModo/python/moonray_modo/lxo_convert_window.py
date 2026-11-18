"""MoonRay > Convert LXO to RDL: Modo scenes on disk written as MoonRay scenes, in the background (lxo_convert.Batch).
The window stays open beside Modo, which goes on working; each scene's state is shown as it changes, and what modo_cl
said about the one selected."""
from pathlib import Path

from PySide2 import QtCore, QtWidgets

from . import lxo_convert

STATES = {'waiting': 'Waiting', 'converting': 'Converting...', 'done': 'Done', 'failed': 'Failed', 'stopped': 'Stopped'}


class Window(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent, QtCore.Qt.Window)
        self.setWindowTitle('Convert LXO to RDL')
        self.resize(760, 560)
        self.settings = QtCore.QSettings('MoonRayForModo', 'LxoConvert')
        self.batch = None
        layout = QtWidgets.QVBoxLayout(self)
        note = QtWidgets.QLabel("Modo scenes on disk are written as MoonRay scenes by Modo's command-line engine, in the "
                                'background: the scene open here is not touched, and Modo goes on working. Each scene is '
                                'written as Export as MoonRay Scene writes it, by its own MoonRay render settings.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.scenes = QtWidgets.QTreeWidget()
        self.scenes.setHeaderLabels(['Scene', 'State', 'Written'])
        self.scenes.setRootIsDecorated(False)
        self.scenes.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.scenes.header().setStretchLastSection(True)
        self.scenes.setColumnWidth(0, 330)
        self.scenes.setColumnWidth(1, 110)
        self.scenes.itemSelectionChanged.connect(self._show_log)
        layout.addWidget(self.scenes, 1)
        row = QtWidgets.QHBoxLayout()
        for label, call in (('Add Scenes...', self.add_scenes), ('Add Folder...', self.add_folder), ('Remove', self.remove), ('Clear', self.clear)):
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(call)
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)
        form = QtWidgets.QFormLayout()
        where = QtWidgets.QHBoxLayout()
        self.beside = QtWidgets.QComboBox()
        self.beside.addItem('Beside each scene', 'beside')
        self.beside.addItem('In this folder:', 'folder')
        self.beside.setCurrentIndex(max(0, self.beside.findData(self.settings.value('where', 'beside'))))
        self.folder = QtWidgets.QLineEdit(str(self.settings.value('folder', '')))
        browse = QtWidgets.QPushButton('Browse...')
        browse.clicked.connect(self.browse)
        where.addWidget(self.beside)
        where.addWidget(self.folder, 1)
        where.addWidget(browse)
        self.beside.currentIndexChanged.connect(self._where_changed)
        self._browse = browse
        form.addRow('Write', where)
        self.format = QtWidgets.QComboBox()
        for key, label in lxo_convert.FORMATS:
            self.format.addItem(label, key)
        self.format.setCurrentIndex(max(0, self.format.findData(self.settings.value('format', 'rdla'))))
        form.addRow('Format', self.format)
        self.at_once = QtWidgets.QSpinBox()
        self.at_once.setRange(1, 8)
        self.at_once.setValue(int(self.settings.value('at_once', 1)))
        self.at_once.setToolTip('How many scenes are converted at the same time, each by a Modo command-line engine of its own '
                                '(each holds its scene in memory, as Modo does).')
        form.addRow('At once', self.at_once)
        layout.addLayout(form)
        self.outputs = QtWidgets.QCheckBox('Render outputs: AOVs, Cryptomatte and deep beside the beauty')
        self.outputs.setChecked(str(self.settings.value('outputs', 'true')).lower() == 'true')
        self.collect = QtWidgets.QCheckBox('Collect textures into a folder beside each MoonRay scene')
        self.collect.setChecked(str(self.settings.value('collect', 'false')).lower() == 'true')
        self.frames = QtWidgets.QCheckBox("Every frame of each scene's frame range, one MoonRay scene each")
        self.frames.setChecked(str(self.settings.value('frames', 'false')).lower() == 'true')
        for box in (self.outputs, self.collect, self.frames):
            layout.addWidget(box)
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText('What the conversion of the selected scene said.')
        self.log.setMaximumHeight(130)
        layout.addWidget(self.log)
        foot = QtWidgets.QHBoxLayout()
        self.status = QtWidgets.QLabel()
        self.convert = QtWidgets.QPushButton('Convert')
        self.convert.clicked.connect(self.start)
        self.stop_button = QtWidgets.QPushButton('Stop')
        self.stop_button.clicked.connect(self.stop)
        self.stop_button.setEnabled(False)
        foot.addWidget(self.status, 1)
        foot.addWidget(self.convert)
        foot.addWidget(self.stop_button)
        layout.addLayout(foot)
        self._where_changed()
        self._said()

    # The list of scenes.
    def add_scenes(self):
        chosen, _ = QtWidgets.QFileDialog.getOpenFileNames(self, 'Modo scenes to convert', str(self.settings.value('scenes', '')), 'Modo scene (*.lxo)')
        if chosen:
            self.settings.setValue('scenes', str(Path(chosen[0]).parent))
            self.add(chosen)

    def add_folder(self):
        chosen = QtWidgets.QFileDialog.getExistingDirectory(self, 'A folder of Modo scenes (its subfolders too)', str(self.settings.value('scenes', '')))
        if chosen:
            self.settings.setValue('scenes', chosen)
            self.add([chosen])

    def add(self, paths):
        """Scenes put in the list: files, and the .lxo files in folders and their subfolders; each scene once."""
        if self._busy():
            return
        held = {self.scenes.topLevelItem(i).data(0, QtCore.Qt.UserRole).lower() for i in range(self.scenes.topLevelItemCount())}
        for scene in lxo_convert.lxo_files(paths):
            if str(scene).lower() in held:
                continue
            item = QtWidgets.QTreeWidgetItem([scene.name, '', ''])
            item.setData(0, QtCore.Qt.UserRole, str(scene))
            item.setToolTip(0, str(scene))
            self.scenes.addTopLevelItem(item)
        self._said()

    def remove(self):
        if self._busy():
            return
        for item in self.scenes.selectedItems():
            self.scenes.takeTopLevelItem(self.scenes.indexOfTopLevelItem(item))
        self._said()

    def clear(self):
        if self._busy():
            return
        self.scenes.clear()
        self.log.clear()
        self._said()

    def browse(self):
        chosen = QtWidgets.QFileDialog.getExistingDirectory(self, 'Where the MoonRay scenes are written', self.folder.text())
        if chosen:
            self.folder.setText(chosen)

    def _where_changed(self, *_):
        into = self.beside.currentData() == 'folder'
        self.folder.setEnabled(into)
        self._browse.setEnabled(into)

    # The conversion.
    def start(self):
        scenes = [Path(self.scenes.topLevelItem(i).data(0, QtCore.Qt.UserRole)) for i in range(self.scenes.topLevelItemCount())]
        if not scenes or self._busy():
            self.status.setText('Add Modo scenes first.' if not scenes else self.status.text())
            return
        folder = self.folder.text().strip() if self.beside.currentData() == 'folder' else None
        if self.beside.currentData() == 'folder' and not folder:
            self.status.setText('Choose the folder the MoonRay scenes are written in.')
            return
        for key, value in (('where', self.beside.currentData()), ('folder', self.folder.text().strip()), ('format', self.format.currentData()),
                           ('at_once', self.at_once.value()), ('outputs', 'true' if self.outputs.isChecked() else 'false'),
                           ('collect', 'true' if self.collect.isChecked() else 'false'), ('frames', 'true' if self.frames.isChecked() else 'false')):
            self.settings.setValue(key, value)
        self.batch = lxo_convert.Batch(scenes, self.format.currentData(), folder, self.frames.isChecked(), self.outputs.isChecked(),
                                       self.collect.isChecked(), self.at_once.value(), self)
        self.batch.changed.connect(self._changed)
        self.batch.finished.connect(self._finished)
        for index in range(len(scenes)):
            self._changed(index)
        self.convert.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.batch.start()
        self._said()

    def stop(self):
        if self.batch is not None:
            self.batch.stop()

    def _busy(self):
        return self.batch is not None and bool(self.batch.running)

    def _changed(self, index):
        if self.batch is None or index >= self.scenes.topLevelItemCount():
            return
        job = self.batch.jobs[index]
        item = self.scenes.topLevelItem(index)
        item.setText(1, STATES[job['state']])
        written = job['written']
        item.setText(2, ', '.join(Path(p).name for p in written[:3]) + (' and %d more' % (len(written) - 3) if len(written) > 3 else '')
                     if written else (str(job['target']) if job['state'] == 'waiting' else ''))
        item.setToolTip(2, '\n'.join(written) or str(job['target']))
        if item.isSelected():
            self._show_log()
        self._said()

    def _finished(self):
        self.convert.setEnabled(True)
        self.stop_button.setEnabled(False)
        self._said()

    def _show_log(self):
        items = self.scenes.selectedItems()
        if not items or self.batch is None:
            self.log.clear()
            return
        index = self.scenes.indexOfTopLevelItem(items[0])
        if index >= len(self.batch.jobs):
            return
        job = self.batch.jobs[index]
        lines = ['Wrote ' + p for p in job['written']] + ['Notice: ' + n for n in job['notices']]
        if job['state'] in ('failed', 'stopped') or not lines:
            lines.append(job['log'].strip()[-4000:])
        self.log.setPlainText('\n'.join(line for line in lines if line))

    def _said(self):
        count = self.scenes.topLevelItemCount()
        if self.batch is None:
            self.status.setText('%d scene%s' % (count, '' if count == 1 else 's') if count else 'Add Modo scenes to convert.')
            return
        held = self.batch.counts()
        words = ['%d %s' % (held[state], STATES[state].rstrip('.').lower()) for state in ('done', 'converting', 'waiting', 'failed', 'stopped') if held.get(state)]
        self.status.setText(', '.join(words))

    def closeEvent(self, event):
        # Closed while converting: the conversions under way end with it.
        self.stop()
        super().closeEvent(event)


_window = None
_quit_hooked = [False]


def _close_on_quit():
    """Modo quitting closes the window first, ending what it converts, while Qt still stands (as the Rhizome window
    does, rhizome_window._close_on_quit)."""
    if _quit_hooked[0]:
        return
    application = QtCore.QCoreApplication.instance()
    if application is None:
        return

    def closing():
        global _window
        from shiboken2 import isValid
        window, _window = _window, None
        try:
            if window is not None and isValid(window):
                window.close()
                window.deleteLater()
        except Exception:
            pass
    application.aboutToQuit.connect(closing)
    _quit_hooked[0] = True


def show(parent=None):
    global _window
    if _window is None:
        _window = Window(parent)
        _close_on_quit()
    _window.show()
    _window.raise_()
    _window.activateWindow()
    return _window
