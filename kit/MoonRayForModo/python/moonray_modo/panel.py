"""Dockable Modo Custom View with a native Windows render process."""
import hashlib
import json
from pathlib import Path
from PySide2 import QtCore, QtGui, QtWidgets
from . import host, native, rdla, options, properties
import lx
from .render import Renderer


class Preview(QtWidgets.QLabel):
    def __init__(self, parent=None):
        super().__init__('Choose a MoonRay runtime, then start Preview.', parent)
        self.image = QtGui.QImage()
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setMinimumSize(256, 192)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.setStyleSheet('background:#191b20; color:#b9bec9; border:1px solid #363b44;')

    def load(self, path):
        image = QtGui.QImage(path)
        if image.isNull():
            raise ValueError('MoonRay output could not be decoded as an image.')
        self.image = image
        self.refresh()

    def refresh(self):
        if not self.image.isNull():
            self.setPixmap(QtGui.QPixmap.fromImage(self.image).scaled(
                self.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh()


class Panel(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QtCore.QSettings('MoonRayForModo', 'NativePreview')
        self.renderer = Renderer(self)
        self.last_digest = None
        self.disposed = False
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(1200)
        self.timer.timeout.connect(self._live_tick)
        layout = QtWidgets.QVBoxLayout(self)
        title = QtWidgets.QLabel('MoonRay Preview')
        layout.addWidget(title)
        self.tabs = QtWidgets.QTabWidget()
        self.pages = {}
        for key, label in [('render', 'Render'), ('lighting', 'Lighting'), ('object', 'Objects'),
                           ('aovs', 'AOVs'), ('system', 'System')]:
            page = QtWidgets.QWidget()
            form = QtWidgets.QFormLayout(page)
            self.pages[key] = form
            self.tabs.addTab(page, label)
        row = QtWidgets.QHBoxLayout()
        self.runtime = QtWidgets.QLineEdit(str(self.settings.value('runtime', native.default_runtime())))
        self.runtime.setPlaceholderText('Folder containing moonray.exe or blender.shared')
        browse = QtWidgets.QPushButton('Browse…')
        browse.clicked.connect(self._browse)
        row.addWidget(QtWidgets.QLabel('MoonRay'))
        row.addWidget(self.runtime, 1)
        row.addWidget(browse)
        self.pages['system'].addRow(row)
        controls = self.pages['render']
        self.size = QtWidgets.QComboBox()
        self.size.addItems(['320 px wide', '640 px wide', '960 px wide', 'Scene resolution'])
        self.size.setCurrentIndex(1)
        self.samples = QtWidgets.QSpinBox()
        self.samples.setRange(1, 64)
        self.samples.setValue(4)
        self.samples.setToolTip('MoonRay pixel sample grid side; 4 = 16 samples/pixel.')
        self.environment = QtWidgets.QDoubleSpinBox()
        self.environment.setRange(0, 100)
        self.environment.setSingleStep(.1)
        self.environment.setValue(0)
        self.environment.setToolTip('Additional uniform environment light; zero preserves scene lighting.')
        self.threads = QtWidgets.QSpinBox()
        self.threads.setRange(1, 256)
        self.threads.setValue(4)
        controls.addRow('Preview size', self.size)
        controls.addRow('Pixel sample grid', self.samples)
        self.pages['system'].addRow('CPU threads', self.threads)
        self.pages['lighting'].addRow('Uniform environment', self.environment)
        self.modo_environment = QtWidgets.QCheckBox('Use Modo environments')
        self.modo_environment.setChecked(True)
        self.pages['lighting'].addRow(self.modo_environment)
        self.environment_multiplier = QtWidgets.QDoubleSpinBox()
        self.environment_multiplier.setRange(0,10000)
        self.environment_multiplier.setValue(1)
        self.pages['lighting'].addRow('Modo environment multiplier',self.environment_multiplier)
        self.light_multiplier = QtWidgets.QDoubleSpinBox()
        self.light_multiplier.setRange(0, 10000)
        self.light_multiplier.setValue(1)
        self.pages['lighting'].addRow('Modo light multiplier', self.light_multiplier)
        self.render_controls = {}
        for key, (default, minimum, maximum, label) in options.RENDER.items():
            if key == 'shadow_terminator_fix':
                control = QtWidgets.QComboBox()
                control.addItems(['Off', 'Targeted', 'Sine', 'GGX', 'Cosine'])
                control.setCurrentIndex(default)
            else:
                control = QtWidgets.QSpinBox()
                control.setRange(minimum, maximum)
                control.setValue(default)
            self.render_controls[key] = control
            controls.addRow(label, control)
        surface = self.pages['object']
        self.surface = QtWidgets.QComboBox()
        self.surface.addItems(['As modeled', 'Smooth subdivision'])
        self.surface.setToolTip('As modeled respects Modo subdivision polygons. Smooth subdivision rounds all exported meshes; use it for curved surfaces, not sharp-edged objects.')
        self.subdivision_level = QtWidgets.QSpinBox()
        self.subdivision_level.setRange(1, 5)
        self.subdivision_level.setValue(3)
        self.subdivision_level.setToolTip('Detail for subdivision surfaces. Higher levels use more memory and take longer to render.')
        surface.addRow('Scene default surface', self.surface)
        surface.addRow('Default subdivision level', self.subdivision_level)
        self.selected_object = QtWidgets.QLabel('Select a mesh in Modo')
        self.selected_object.setWordWrap(True)
        surface.addRow(self.selected_object)
        self.object_controls = {}
        for key, (default, label) in options.OBJECT.items():
            if type(default) is bool:
                widget = QtWidgets.QCheckBox()
                widget.setChecked(default)
            else:
                widget = QtWidgets.QSpinBox()
                widget.setRange(1, 5)
                widget.setValue(default)
            self.object_controls[key] = widget
            surface.addRow(label, widget)
        self.object_apply = QtWidgets.QPushButton('Apply to selected meshes')
        self.object_apply.clicked.connect(self._save_object)
        surface.addRow(self.object_apply)
        self.aov_controls = {}
        aov_text = QtWidgets.QLabel('Beauty RGB is always written. Checked AOVs are additional channels in the same 32-bit linear EXR. Preview displays beauty.')
        aov_text.setWordWrap(True)
        self.pages['aovs'].addRow(aov_text)
        for key, (label, attributes, channel) in options.AOVS.items():
            checkbox = QtWidgets.QCheckBox(label + '  [' + channel + ']')
            checkbox.setChecked(key == 'alpha')
            self.aov_controls[key] = checkbox
            self.pages['aovs'].addRow(checkbox)
        lighting_note = QtWidgets.QLabel('Glass uses Modo Transparency Amount/Color, Refraction Index, Roughness and Transparency Roughness. Use closed meshes for solid glass. Start with IOR 1.5 and Transparency 100%; increase Glossy and Mirror/refraction bounces for multiple glass surfaces. UV images can drive transmission amount, color and roughness. Absorption distance, dispersion and thin-sheet glass are not translated; warnings appear below.')
        lighting_note.setWordWrap(True)
        self.pages['lighting'].addRow(lighting_note)
        save_settings = QtWidgets.QPushButton('Store render settings in scene')
        save_settings.clicked.connect(self._save_settings)
        controls.addRow(save_settings)
        actions = QtWidgets.QHBoxLayout()
        self.start = QtWidgets.QPushButton('Preview')
        self.start.clicked.connect(self.render_once)
        stop = QtWidgets.QPushButton('Stop')
        stop.clicked.connect(self.stop)
        self.live = QtWidgets.QCheckBox('Live updates')
        self.live.toggled.connect(self._toggle_live)
        self.final = QtWidgets.QPushButton('Render EXR…')
        self.final.clicked.connect(self.render_final)
        export = QtWidgets.QPushButton('Export scene…')
        export.clicked.connect(self.export)
        self.settings_toggle = QtWidgets.QPushButton('Settings')
        self.settings_toggle.setCheckable(True)
        self.settings_toggle.setChecked(True)
        self.settings_toggle.toggled.connect(self.tabs.setVisible)
        for widget in (self.start, stop, self.live, self.settings_toggle, self.final, export):
            actions.addWidget(widget)
        layout.addLayout(actions)
        self.preview = Preview()
        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        split.addWidget(self.tabs)
        split.addWidget(self.preview)
        split.setStretchFactor(1, 1)
        split.setSizes([420, 580])
        layout.addWidget(split, 1)
        self.status = QtWidgets.QLabel('Ready. Press Preview to render.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.warnings = QtWidgets.QLabel('Scene compatibility notices appear here after export.')
        self.warnings.setWordWrap(True)
        layout.addWidget(self.warnings)
        footer = QtWidgets.QHBoxLayout()
        save = QtWidgets.QPushButton('Save preview…')
        save.clicked.connect(self.save_preview)
        log = QtWidgets.QPushButton('Render log…')
        log.clicked.connect(self.show_log)
        footer.addWidget(save)
        footer.addWidget(log)
        footer.addStretch()
        layout.addLayout(footer)
        self.renderer.status.connect(self.status.setText)
        self.renderer.failed.connect(self._failed)
        self.renderer.image_ready.connect(self._image)
        self.renderer.finished.connect(self._finished)
        self._scene_id = None
        self._object_signature = None
        self._load_settings()
        self.selection_timer = QtCore.QTimer(self)
        self.selection_timer.setInterval(750)
        self.selection_timer.timeout.connect(self._refresh_object)
        self.selection_timer.start()
        self._refresh_object()

    def show_page(self, page):
        if page in self.pages:
            self.settings_toggle.setChecked(True)
            self.tabs.setCurrentIndex(list(self.pages).index(page))

    def _load_settings(self):
        import modo
        self._scene_id = modo.Scene().renderItem.id
        values = properties.scene_settings()
        for key, value in options.render_values(values.get('render', {})).items():
            control = self.render_controls[key]
            control.setCurrentIndex(value) if isinstance(control, QtWidgets.QComboBox) else control.setValue(value)
        for key, control in self.aov_controls.items():
            control.setChecked(key in values.get('aovs', ['alpha']))
        for key, control, default in [('samples', self.samples, 4), ('environment', self.environment, 0),
                             ('threads', self.threads, 4), ('subdivision_level', self.subdivision_level, 3),
                             ('light_multiplier', self.light_multiplier, 1)]:
            control.setValue(values.get(key, default))
        self.surface.setCurrentIndex(int(values.get('surface', 0)))
        self.modo_environment.setChecked(values.get('modo_environment',True))
        self.environment_multiplier.setValue(values.get('environment_multiplier',1))

    def _settings_values(self):
        return {'render': {key: control.currentIndex() if isinstance(control, QtWidgets.QComboBox) else control.value()
                           for key, control in self.render_controls.items()},
                'aovs': [key for key, control in self.aov_controls.items() if control.isChecked()],
                'samples': self.samples.value(), 'environment': self.environment.value(),
                'threads': self.threads.value(), 'surface': self.surface.currentIndex(),
                'subdivision_level': self.subdivision_level.value(), 'light_multiplier': self.light_multiplier.value(),
                'modo_environment':self.modo_environment.isChecked(),
                'environment_multiplier':self.environment_multiplier.value()}

    def _save_settings(self):
        try:
            lx.eval('moonray.sceneSettings ' + properties.encode(self._settings_values()))
            self.status.setText('Render settings stored in scene. Save the Modo scene to keep them on disk.')
        except Exception as exc:
            self.status.setText('Cannot store settings: ' + str(exc))

    def _refresh_object(self):
        try:
            selected = properties.selected_meshes()
            signature = [(item.id, properties.read(item)) for item in selected]
            if signature == self._object_signature:
                return
            self._object_signature = signature
            self.object_apply.setEnabled(bool(selected))
            self.selected_object.setText(', '.join(item.name for item in selected) or 'Select a mesh in Modo')
            values = options.object_values(properties.read(selected[0])) if selected else options.object_values({})
            for key, widget in self.object_controls.items():
                widget.setEnabled(bool(selected))
                widget.setChecked(values[key]) if isinstance(widget, QtWidgets.QCheckBox) else widget.setValue(values[key])
        except Exception:
            self.object_apply.setEnabled(False)

    def _save_object(self):
        try:
            values = {key: control.isChecked() if isinstance(control, QtWidgets.QCheckBox) else control.value()
                      for key, control in self.object_controls.items()}
            lx.eval('moonray.objectSettings ' + properties.encode(values))
            self._object_signature = None
            self._refresh_object()
            self.status.setText('Object properties updated. Per-object overrides take precedence over scene defaults.')
        except Exception as exc:
            self.status.setText('Cannot update object properties: ' + str(exc))

    def _browse(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, 'Choose native Windows MoonRay runtime', self.runtime.text())
        if path:
            self.runtime.setText(path)

    def _dimensions(self, scene, final=False):
        scene_w, scene_h = scene['width'], scene['height']
        width = scene_w if final or self.size.currentIndex() == 3 else (320, 640, 960)[self.size.currentIndex()]
        return width, max(16, round(width * scene_h / max(1, scene_w)))

    def _capture(self):
        import modo
        if modo.Scene().renderItem.id != self._scene_id:
            self._load_settings()
        scene = host.snapshot()
        values = self._settings_values()
        scene['render_settings'] = values['render']
        scene['aovs'] = values['aovs']
        if not self.modo_environment.isChecked():
            scene['environments']=[]
        for environment in scene.get('environments',[]):
            environment['intensity'] *= self.environment_multiplier.value()
        for light in scene['lights']:
            light['intensity'] *= self.light_multiplier.value()
        for mesh in scene['meshes']:
            if mesh.get('object_override'):
                continue
            if self.surface.currentIndex() == 1:
                mesh['subdivision'] = True
            mesh['subdivision_level'] = self.subdivision_level.value()
        if self.surface.currentIndex() == 1:
            scene['warnings'].append('Smooth subdivision rounds all exported meshes, including sharp edges.')
        self.warnings.setText('\n'.join(scene['warnings']) or 'Scene captured. Basic material translation is approximate.')
        return scene

    def _submit(self, scene, output=None):
        width, height = self._dimensions(scene, bool(output))
        self.renderer.submit(scene, self.runtime.text(), width, height, self.samples.value(),
                             self.environment.value(), self.threads.value(), output)
        self.settings.setValue('runtime', self.runtime.text())
        self.last_digest = self._digest(scene)

    def _digest(self, scene):
        values = [scene, self.runtime.text(), self.size.currentIndex(), self.samples.value(), self.environment.value(), self.threads.value()]
        return hashlib.sha256(json.dumps(values, sort_keys=True).encode('utf-8')).hexdigest()

    def render_once(self):
        try:
            self._submit(self._capture())
        except Exception as exc:
            self._failed(str(exc))

    def _toggle_live(self, on):
        if on:
            self.render_once()
            if self.live.isChecked():
                self.timer.start()
        else:
            self.timer.stop()

    def _live_tick(self):
        try:
            scene = self._capture()
            if self._digest(scene) != self.last_digest:
                self._submit(scene)
        except Exception as exc:
            self._failed(str(exc))

    def stop(self):
        self.live.setChecked(False)
        self.renderer.stop()

    def _failed(self, message):
        self.live.setChecked(False)
        self.renderer.stop()
        self.status.setText('Render unavailable: ' + message)

    def _image(self, path):
        try:
            self.preview.load(path)
        except ValueError as exc:
            self._failed(str(exc))

    def _finished(self, output):
        self.status.setText('Saved ' + output if output else 'Preview complete' + (' · Watching scene changes' if self.live.isChecked() else ''))

    def render_final(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Render OpenEXR', '', 'OpenEXR (*.exr)')
        if not path:
            return
        if not path.lower().endswith('.exr'):
            path += '.exr'
        self.live.setChecked(False)
        try:
            self._submit(self._capture(), path)
        except Exception as exc:
            self._failed(str(exc))

    def export(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Export MoonRay scene', '', 'MoonRay scene (*.rdla)')
        if not path:
            return
        try:
            scene = self._capture()
            width, height = self._dimensions(scene, True)
            text = rdla.scene_text(scene, width, height, self.samples.value(), self.environment.value(),
                                   str(Path(path).with_suffix('.exr')))
            Path(path).write_text(text, encoding='utf-8')
            self.status.setText('Exported ' + path)
        except Exception as exc:
            self._failed(str(exc))

    def save_preview(self):
        if self.preview.image.isNull():
            self.status.setText('Render a preview first.')
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Save preview', '', 'PNG image (*.png)')
        if path and not self.preview.image.save(path, 'PNG'):
            self.status.setText('Could not save the preview image.')

    def show_log(self):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle('MoonRay render log')
        dialog.resize(760, 460)
        layout = QtWidgets.QVBoxLayout(dialog)
        text = QtWidgets.QPlainTextEdit(self.renderer.log or 'No renderer output yet.')
        text.setReadOnly(True)
        layout.addWidget(text)
        dialog.exec_()

    def dispose(self):
        if not self.disposed:
            self.disposed = True
            self.timer.stop()
            self.selection_timer.stop()
            self.renderer.close()

    def closeEvent(self, event):
        self.dispose()
        super().closeEvent(event)
