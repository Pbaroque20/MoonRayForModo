"""What the preview window remembers on this machine, apart from any scene."""
from PySide2 import QtCore, QtWidgets
from . import native

# Of the previews (MoonRay LS and MoonLightIPR). MoonRay itself renders at the camera's resolution.
SIZES = (('320 px wide', 320), ('640 px wide', 640), ('960 px wide', 960), ('1280 px wide', 1280))
# key: (default, kind)
KEYS = {
    'runtime': ('', str), 'preview_engine': ('moonray', str), 'open_engine': ('moonray', str), 'preview_size': (640, int),
    # Whether the environment lights the scene always, as a path tracer has it ('moonray'), or only with Global
    # Illumination on in the Render item, as Modo's own renderer has it ('modo').
    'environment_lighting': ('moonray', str),
    'idle_release_minutes': (5, int),
    'persistent_preview': (True, bool), 'preview_motion': (True, bool),
    'ipr': (False, bool), 'show_buckets': (True, bool), 'worker_tiles': (True, bool), 'clay': ('materials', str),
    'display_gamma': (1.0, float),
    # Set on the MoonRay page of Modo's Preferences: what Assign Material starts with, the ink of a draft, whether a
    # preview starts as its window opens, how bright a new MoonRay light is, and whether notices open by themselves.
    'assign/shader': ('DwaBaseMaterial', str), 'assign/smooth': (True, bool), 'assign/angle': (40.0, float),
    # Toon materials lit by their smooth normals on coarse meshes, without steps along the faces (MoonRay reads it
    # as it starts; native.toon_terminator).
    'toon_terminator': (True, bool),
    # Toon materials denoise as other materials do: MoonRay's albedo output gives them their own colour
    # (native.toon_albedo).
    'toon_albedo': (True, bool),
    # Moving lights blur: MoonRay's mb switch set on a light that moves during the shutter (native.light_motion).
    'light_motion': (True, bool),
    'draft/ink': ('tan', str), 'draft/width': (640.0, float), 'render_on_open': (False, bool), 'light_intensity': (50.0, float), 'notices_open': (False, bool),
    'ipr/width': (640, int), 'ipr/samples': (16, int), 'ipr/error': (100.0, float), 'ipr/refine': (False, bool),
    # How many samples a pixel MoonLightIPR gathers before it rests, in realtime.
    'moonlightipr/samples': (256, int),
}
# The samples a pixel each realtime engine may be set to stop at.
LS_SAMPLES = (1, 4, 16, 32, 64)
# How wide MoonRay LS may render: small, to be quick, or any of the preview sizes.
LS_WIDTHS = (80, 160, 240) + tuple(size for label, size in SIZES)
MOONLIGHTIPR_SAMPLES = (32, 64, 128, 256)


class Preferences:
    def __init__(self):
        self.store = QtCore.QSettings('MoonRayForModo', native.settings_name())
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
                if key == 'preview_engine' and value == 'moonlight':
                    # The engine's name as 0.3.50.1 and 0.3.50.2 stored it.
                    return 'moonlightipr'
                return str(value) if value else (native.default_runtime() if key == 'runtime' else default)
            if key == 'preview_size' and kind(value) <= 0:
                # Scene resolution, as it could once be set to: a realtime preview is no longer made that large.
                return default
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
        form.addRow('Realtime preview size', combo('preview_size', SIZES))
        form.addRow(check('persistent_preview', 'Keep MoonRay loaded between previews',
                          'Faster updates; structural edits still reload the scene'))
        form.addRow('Release idle renderer memory', combo('idle_release_minutes',
                    [('Never', 0), ('After 1 minute', 1), ('After 5 minutes', 5), ('After 15 minutes', 15), ('After 30 minutes', 30)],
                    'Keeps cached images. The next render reloads its scene; active renders are never interrupted.'))
        form.addRow(check('preview_motion', 'Motion blur in MoonLightIPR renders',
                          'Render reads the scene at shutter open and close; IPR updates stay sharp'))
        heading = QtWidgets.QLabel('MoonLightIPR quality')
        heading.setStyleSheet('font-weight: bold; margin-top: 8px')
        form.addRow(heading)
        form.addRow('Pixel samples', combo('moonlightipr/samples', [('%d per pixel' % v, v) for v in MOONLIGHTIPR_SAMPLES],
                                            'How many samples a pixel MoonLightIPR gathers in realtime before it rests. Fewer settles sooner and is grainier.'))
        heading = QtWidgets.QLabel('MoonRay LS quality')
        heading.setStyleSheet('font-weight: bold; margin-top: 8px')
        form.addRow(heading)
        form.addRow('Width limit', combo('ipr/width', [('%d px' % v, v) for v in LS_WIDTHS],
                                          'How wide MoonRay LS renders, and never wider than the preview size above. Narrower is quicker.'))
        form.addRow('Pixel samples', combo('ipr/samples', [('%d per pixel' % v, v) for v in LS_SAMPLES],
                                            'The most samples a pixel MoonRay LS takes, and never more than the render settings of the scene give. More is cleaner and slower.'))
        self.error = QtWidgets.QDoubleSpinBox()
        self.error.setRange(.1, 1000)
        self.error.setDecimals(1)
        self.error.setSingleStep(10)
        self.error.setValue(preferences.get('ipr/error'))
        self.error.setToolTip('Higher stops sooner')
        form.addRow('Adaptive error', self.error)
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
