"""What the preview window remembers on this machine, apart from any scene."""
from PySide2 import QtCore, QtWidgets
from . import native

# Of the previews (MoonRay LS and MoonLightIPR). MoonRay itself renders at the camera's resolution.
SIZES = (('320 px wide', 320), ('640 px wide', 640), ('960 px wide', 960), ('1280 px wide', 1280))
# key: (default, kind)
KEYS = {
    'runtime': ('', str), 'cache_folder': ('', str), 'scene_cache': (True, bool), 'preview_engine': ('moonray', str), 'open_engine': ('moonray', str), 'preview_size': (640, int),
    # Whether the environment lights the scene always, as a path tracer has it ('moonray'), or only with Global
    # Illumination on in the Render item, as Modo's own renderer has it ('modo').
    'environment_lighting': ('moonray', str),
    'idle_release_minutes': (5, int),
    'persistent_preview': (True, bool), 'preview_motion': (False, bool), 'memory_hud': (True, bool),
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
    # Open Image Denoise cleans the albedo and normal guides first and trusts them (native.denoise_clean_guides).
    'denoise_clean_guides': (True, bool),
    # Presence shadows on where a material is cut out by a map, and off where none is (presence_shadows).
    'presence_shadows_auto': (False, bool),
    # Moving lights blur: MoonRay's mb switch set on a light that moves during the shutter (native.light_motion).
    'light_motion': (True, bool),
    # Fog in Cryptomatte, with mattes of its own (native.crypto_volumes).
    'crypto_volumes': (True, bool),
    # Fog in front of a see-through surface in alpha (native.fog_alpha), and each Cryptomatte sample counted once
    # (native.crypto_once).
    'fog_alpha': (True, bool), 'toon_lines_apart': (True, bool), 'toon_close_gaps': (True, bool), 'filter_inputs': (True, bool),
    'crypto_once': (True, bool),
    # A render stopped by hand or by Smart Render finishes the tiles in hand (native.drain_tiles).
    'drain_tiles': (True, bool),
    # Geometry handed to MoonRay as binary beside the scene text (native.binary_geometry).
    'binary_geometry': (True, bool),
    # Renders below Modo's priority, with a processor thread left over (native.low_latency).
    'low_latency': (True, bool),
    # The four of tools/port_source_switches.py (native.usd_specular and the rest).
    'usd_specular': (True, bool),
    'opaque_alpha': (True, bool),
    'transmission_roughness': (True, bool),
    # N-gons ear-clipped whatever their size and winding (native.ngon_ears).
    'ngon_ears': (True, bool),
    'auto_xpu': (True, bool),
    # XPU2: what renders on the graphics card, and where its adaptive passes are made.
    'xpu2/renderer': ('xpu2', str), 'xpu2/adaptive_chain': (False, bool), 'xpu2/devices': ('both', str), 'xpu2/rt_cap': ('none', str),
    'draft/ink': ('tan', str), 'draft/width': (640.0, float), 'render_on_open': (False, bool), 'light_intensity': (10.0, float), 'working_space': ('rec709', str), 'notices_open': (False, bool),
    'ipr/width': (640, int), 'ipr/sampling': ('adaptive', str), 'ipr/samples': (32, int), 'ipr/error': (100.0, float), 'ipr/refine': (False, bool),
    # How many samples a pixel MoonLightIPR gathers before it rests, in realtime.
    'moonlightipr/samples': (256, int),
}
# The samples a pixel each realtime engine may be set to stop at.
LS_SAMPLES = (32, 64, 128)
# How wide MoonRay LS may render: small, to be quick, or any of the preview sizes.
LS_WIDTHS = (80, 160, 240) + tuple(size for label, size in SIZES)
MOONLIGHTIPR_SAMPLES = (128, 256, 512, 1024)
# How wide Draft renders while the scene is moved, for a quick picture.
DRAFT_WIDTHS = (320, 640, 1280)


class Preferences:
    def __init__(self):
        self.store = QtCore.QSettings('MoonRayForModo', native.settings_name())
        installation = native.installation_id()
        if installation and self.store.value('runtime_installation') != installation:
            # A newly installed kit brings its own runtime; the earlier choice is kept aside.
            self.store.setValue('previous_runtime', self.store.value('runtime', ''))
            self.store.setValue('runtime', native.default_runtime())
            self.store.setValue('runtime_installation', installation)
        # Motion blur in MoonLightIPR is off by default since 2026-10-27 (it adds to each update's wait): a choice stored
        # before then is let go once, and one made since is kept.
        if self.store.value('preview_motion_default') != 'off':
            self.store.remove('preview_motion')
            self.store.setValue('preview_motion_default', 'off')

    def get(self, key):
        default, kind = KEYS[key]
        value = self.store.value(key, default)
        try:
            if kind is bool:
                return str(value).lower() in ('true', '1')
            if kind is str:
                if key == 'ipr/sampling' and value not in ('adaptive', 'uniform'):
                    return default
                if key == 'preview_engine' and value == 'moonlight':
                    # The engine's name as 0.3.50.1 and 0.3.50.2 stored it.
                    return 'moonlightipr'
                return str(value) if value else (native.default_runtime() if key == 'runtime' else default)
            if key in ('moonlightipr/samples', 'ipr/samples'):
                # Fewer than can be chosen now (32 and 64 for MoonLightIPR, 1 to 16 for MoonRay LS, which could once
                # be chosen) are taken up to the fewest that can.
                levels = MOONLIGHTIPR_SAMPLES if key == 'moonlightipr/samples' else LS_SAMPLES
                return next((v for v in levels if v >= int(value)), levels[-1])
            if key == 'draft/width':
                # A width that could once be typed is taken to the nearest of those that can be chosen now.
                return float(min(DRAFT_WIDTHS, key=lambda width: abs(width - float(value))))
            if key == 'preview_size' and kind(value) <= 0:
                # Scene resolution, as it could once be set to: a realtime preview is no longer made that large.
                return default
            return kind(value)
        except (TypeError, ValueError):
            return default

    def set(self, key, value):
        self.store.setValue(key, ('true' if value else 'false') if KEYS[key][1] is bool else value)


def realtime_share():
    """Realtime Sample %, the open scene's (XPU2 Sampling in its render settings); None with no scene to read it from."""
    try:
        from . import properties, scene_settings
        return int(scene_settings.complete(properties.scene_settings())['xpu2_generations']['realtime'])
    except Exception:
        return None


class Dialog(QtWidgets.QDialog):
    """The few choices about previewing that do not belong to a scene, and Realtime Sample %, which does, kept to hand."""
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
        # Where the kit and its renderers keep what they make once and use again (cache_folder).
        self.cache = QtWidgets.QLineEdit(preferences.get('cache_folder'))
        self.cache.setPlaceholderText('In your profile (%LOCALAPPDATA%\\MoonRayForModo)')
        self.cache.setToolTip("Where converted textures and environments, MoonLightIPR's images, the renderers' tessellations and other "
                              'things made once and used again are kept. Empty: in your profile. What the old folder holds is left '
                              'there; the new one fills as things are made again. Applies to renders started after saving')
        browse_cache = QtWidgets.QPushButton('Browse...')
        browse_cache.clicked.connect(self._browse_cache)
        clear_cache = QtWidgets.QPushButton('Clear Cache')
        clear_cache.setToolTip('Removes what the kit keeps in the cache folder: kept scenes and meshes, converted textures and '
                               "environments, MoonLightIPR's images and baked patterns. Each is made again when next needed, so the "
                               "next render of a scene takes longer. Nothing else in the folder is touched, nor MoonLightIPR's "
                               'compiled programs.')
        clear_cache.clicked.connect(self._clear_cache)
        cache_row = QtWidgets.QHBoxLayout()
        cache_row.addWidget(self.cache, 1)
        cache_row.addWidget(browse_cache)
        cache_row.addWidget(clear_cache)
        form.addRow('Cache folder', cache_row)
        form.addRow(check('scene_cache', 'Scene cache',
                          "Keeps a scene's prepared meshes in the cache folder (simplified and packed for the realtime previews, "
                          'tessellated), so that a scene opened again, or the same meshes in another, is ready sooner. At most '
                          '10 GB, the least lately used let go. The status says Caching scene... while it keeps what it makes, and Loading scene '
                          'from cache... while it reads back what it kept.'))
        form.addRow('Realtime preview size', combo('preview_size', SIZES))
        self.realtime_held = realtime_share()
        self.realtime_share = QtWidgets.QSpinBox()
        self.realtime_share.setRange(1, 100)
        self.realtime_share.setValue(100 if self.realtime_held is None else self.realtime_held)
        self.realtime_share.setEnabled(self.realtime_held is not None and native.xpu2())
        self.realtime_share.setToolTip('MoonRay XPU2 only. While realtime follows the scene (RT), the share of Generation Samples XPU2 takes, in '
                                       "percent: lower settles sooner and noisier. The open scene's own, the same as in its render settings")
        form.addRow('Realtime Sample %', self.realtime_share)
        form.addRow(check('persistent_preview', 'Keep MoonRay loaded between previews',
                          'Faster updates; structural edits still reload the scene'))
        form.addRow('Release idle renderer memory', combo('idle_release_minutes',
                    [('Never', 0), ('After 1 minute', 1), ('After 5 minutes', 5), ('After 15 minutes', 15), ('After 30 minutes', 30)],
                    'Keeps cached images. The next render reloads its scene; active renders are never interrupted.'))
        form.addRow(check('preview_motion', 'Motion blur in MoonLightIPR renders',
                          'Off by default: each update then also reads the scene at shutter open and close, which adds to its wait. '
                          'While dragging, updates stay sharp. Said as Motion Blur at the foot of the picture while on'))
        form.addRow(check('memory_hud', 'Memory in the picture',
                          "What the renderer holds, the machine's free RAM and the graphics card's memory, read once a second "
                          'and shown at the bottom right of the picture, in colour when it runs short. Off, it is hidden and nothing is read'))
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
        sampling = combo('ipr/sampling', [('Adaptive', 'adaptive'), ('Uniform', 'uniform')],
                         'Adaptive takes more samples where a pixel is still noisy and stops where it is clean enough, by the '
                         'Adaptive error below. Uniform gives every pixel the same samples, for an even grain.')
        form.addRow('Sampling', sampling)
        form.addRow('Most samples a pixel', combo('ipr/samples', [('%d per pixel' % v, v) for v in LS_SAMPLES],
                                                   'The most samples a pixel MoonRay LS takes, never more than the render settings of the scene give. '
                                                   "Uniform takes MoonRay's square grid of no more than this: 25 for 32, 64, 121 for 128. More is cleaner and slower."))
        self.error = QtWidgets.QDoubleSpinBox()
        self.error.setRange(.1, 1000)
        self.error.setDecimals(1)
        self.error.setSingleStep(10)
        self.error.setValue(preferences.get('ipr/error'))
        self.error.setToolTip('Adaptive sampling: higher stops sooner')
        form.addRow('Adaptive error', self.error)
        # Adaptive sampling's own: greyed under uniform sampling.
        self.error.setEnabled(sampling.currentData() == 'adaptive')
        sampling.currentIndexChanged.connect(lambda _: self.error.setEnabled(sampling.currentData() == 'adaptive'))
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _browse(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, 'Choose the MoonRay folder', self.runtime.text())
        if path:
            self.runtime.setText(path)

    def _clear_cache(self):
        """Clear Cache: asked first, then what the kit keeps in the folder removed (cache_folder.clear) and said."""
        from . import cache_folder
        where = cache_folder.root()
        asked = QtWidgets.QMessageBox.question(self, 'Clear Cache',
            'Remove what the kit keeps in %s?\n\nKept scenes and meshes, converted textures and environments are made again '
            'when next needed, so the next render of each scene takes longer.' % where,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No)
        if asked != QtWidgets.QMessageBox.Yes:
            return
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            removed, freed, left = cache_folder.clear()
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        said = ('%d files removed, %.1f GB freed.' % (removed, freed / 1024 ** 3) if freed >= 1024 ** 3
                else '%d files removed, %.0f MB freed.' % (removed, freed / 1024 ** 2))
        if left:
            said += '\n%d files in use by a render were left; clear again once it is done.' % left
        QtWidgets.QMessageBox.information(self, 'Clear Cache', said)

    def _browse_cache(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, 'Choose the cache folder', self.cache.text())
        if path:
            self.cache.setText(path)

    def accept(self):
        self.preferences.set('runtime', self.runtime.text().strip())
        self.preferences.set('cache_folder', self.cache.text().strip())
        from .cache_folder import forget
        forget()
        self.preferences.set('ipr/error', self.error.value())
        if self.realtime_share.isEnabled() and self.realtime_share.value() != self.realtime_held:
            # Through its command, as in the render settings: undone with the scene, and the form follows.
            import lx
            lx.eval('moonray.render.xpu2_realtime %d' % self.realtime_share.value())
        for key, widget in self.widgets.items():
            self.preferences.set(key, widget.currentData() if isinstance(widget, QtWidgets.QComboBox) else widget.isChecked())
        super().accept()
