"""What the preview window remembers on this machine, apart from any scene."""
from PySide2 import QtCore, QtWidgets
from . import native

SIZES = (('320 px wide', 320), ('640 px wide', 640), ('960 px wide', 960), ('Scene resolution', 0))
# key: (default, kind)
KEYS = {
    'runtime': ('', str), 'preview_engine': ('moonray', str), 'preview_size': (640, int),
    'persistent_preview': (True, bool), 'capture_safety': (True, bool), 'preview_motion': (False, bool),
    'ipr': (False, bool), 'show_buckets': (True, bool), 'worker_tiles': (True, bool), 'clay': ('materials', str),
    'ipr/width': (160, int), 'ipr/samples': (1, int), 'ipr/error': (100.0, float), 'ipr/refine': (False, bool),
}


class Preferences:
    def __init__(self):
        self.store = QtCore.QSettings('MoonRayForModo', 'NativePreview')
        installation = native.installation_id()
        if installation and self.store.value('runtime_installation') != installation:
            # A newly installed kit brings its own runtime; the earlier choice is kept aside.
            self.store.setValue('previous_runtime', self.store.value('runtime', ''))
            self.store.setValue('runtime', native.default_runtime())
            self.store.setValue('runtime_installation', installation)

    def get(self, key):
        default, kind = KEYS[key]
        value = self.store.value(key, default)
        try:
            if kind is bool:
                return str(value).lower() in ('true', '1')
            if kind is str:
                return str(value) if value else (native.default_runtime() if key == 'runtime' else default)
            return kind(value)
        except (TypeError, ValueError):
            return default

    def set(self, key, value):
        self.store.setValue(key, ('true' if value else 'false') if KEYS[key][1] is bool else value)


class Dialog(QtWidgets.QDialog):
    """The few choices about previewing that do not belong to a scene."""
    def __init__(self, preferences, parent=None):
        super().__init__(parent)
        self.preferences = preferences
        self.setWindowTitle('MoonRay Preview Preferences')
        form = QtWidgets.QFormLayout(self)
        self.widgets = {}

        def combo(key, entries, tip=''):
            widget = QtWidgets.QComboBox()
            for label, value in entries:
                widget.addItem(label, value)
            widget.setCurrentIndex(max(0, widget.findData(preferences.get(key))))
            widget.setToolTip(tip)
            self.widgets[key] = widget
            return widget

        def check(key, label, tip=''):
            widget = QtWidgets.QCheckBox(label)
            widget.setChecked(preferences.get(key))
            widget.setToolTip(tip)
            self.widgets[key] = widget
            return widget

        self.runtime = QtWidgets.QLineEdit(preferences.get('runtime'))
        self.runtime.setMinimumWidth(320)
        browse = QtWidgets.QPushButton('Browse...')
        browse.clicked.connect(self._browse)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.runtime, 1)
        row.addWidget(browse)
        form.addRow('MoonRay folder', row)
        form.addRow('Preview size', combo('preview_size', SIZES))
        form.addRow(check('persistent_preview', 'Keep MoonRay loaded between previews',
                          'Faster updates; structural edits still reload the scene'))
        form.addRow(check('preview_motion', 'Motion blur in MoonLight renders',
                          'Render reads the scene at shutter open and close; IPR updates stay sharp'))
        form.addRow(check('capture_safety', 'Re-read the scene every 15 seconds while IPR runs',
                          'Catches edits from procedural items that do not announce their changes'))
        heading = QtWidgets.QLabel('MoonRay IPR quality')
        heading.setStyleSheet('font-weight: bold; margin-top: 8px')
        form.addRow(heading)
        form.addRow('Width limit', combo('ipr/width', [('%d px' % v, v) for v in (80, 160, 240)]))
        form.addRow('Sample limit', combo('ipr/samples', [('%d per pixel' % v, v) for v in (1, 4, 16)]))
        self.error = QtWidgets.QDoubleSpinBox()
        self.error.setRange(.1, 1000)
        self.error.setDecimals(1)
        self.error.setSingleStep(10)
        self.error.setValue(preferences.get('ipr/error'))
        self.error.setToolTip('Higher stops sooner')
        form.addRow('Adaptive error', self.error)
        form.addRow(check('ipr/refine', 'Refine to 16 samples when idle'))
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _browse(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, 'Choose the MoonRay folder', self.runtime.text())
        if path:
            self.runtime.setText(path)

    def accept(self):
        self.preferences.set('runtime', self.runtime.text().strip())
        self.preferences.set('ipr/error', self.error.value())
        for key, widget in self.widgets.items():
            self.preferences.set(key, widget.currentData() if isinstance(widget, QtWidgets.QComboBox) else widget.isChecked())
        super().accept()
