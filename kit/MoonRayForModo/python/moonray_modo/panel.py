"""Dockable Modo Custom View with a native Windows render process."""
import hashlib
import json
from pathlib import Path
from PySide2 import QtCore, QtGui, QtWidgets
from . import host, native, rdla
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
        title = QtWidgets.QLabel('MoonRay for Modo · Native Windows · Prototype 0.1')
        layout.addWidget(title)
        row = QtWidgets.QHBoxLayout()
        self.runtime = QtWidgets.QLineEdit(str(self.settings.value('runtime', native.default_runtime())))
        self.runtime.setPlaceholderText('Folder containing moonray.exe or blender.shared')
        browse = QtWidgets.QPushButton('Browse…')
        browse.clicked.connect(self._browse)
        row.addWidget(QtWidgets.QLabel('MoonRay'))
        row.addWidget(self.runtime, 1)
        row.addWidget(browse)
        layout.addLayout(row)
        controls = QtWidgets.QHBoxLayout()
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
        for label, widget in [('Size', self.size), ('Sample grid', self.samples), ('Environment', self.environment), ('Threads', self.threads)]:
            controls.addWidget(QtWidgets.QLabel(label))
            controls.addWidget(widget)
        layout.addLayout(controls)
        surface = QtWidgets.QHBoxLayout()
        self.surface = QtWidgets.QComboBox()
        self.surface.addItems(['As modeled', 'Smooth subdivision'])
        self.surface.setToolTip('As modeled respects Modo subdivision polygons. Smooth subdivision rounds all exported meshes; use it for curved surfaces, not sharp-edged objects.')
        self.subdivision_level = QtWidgets.QSpinBox()
        self.subdivision_level.setRange(1, 5)
        self.subdivision_level.setValue(3)
        self.subdivision_level.setToolTip('Detail for subdivision surfaces. Higher levels use more memory and take longer to render.')
        surface.addWidget(QtWidgets.QLabel('Surface'))
        surface.addWidget(self.surface)
        surface.addWidget(QtWidgets.QLabel('Subdivision level'))
        surface.addWidget(self.subdivision_level)
        surface.addStretch()
        layout.addLayout(surface)
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
        for widget in (self.start, stop, self.live, self.final, export):
            actions.addWidget(widget)
        layout.addLayout(actions)
        self.preview = Preview()
        layout.addWidget(self.preview, 1)
        self.status = QtWidgets.QLabel('Ready. Requires a native MoonRay runtime compatible with your CPU.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.warnings = QtWidgets.QLabel('Basic polygon meshes, perspective camera and constant materials. See README for limits.')
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

    def _browse(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, 'Choose native Windows MoonRay runtime', self.runtime.text())
        if path:
            self.runtime.setText(path)

    def _dimensions(self, scene, final=False):
        scene_w, scene_h = scene['width'], scene['height']
        width = scene_w if final or self.size.currentIndex() == 3 else (320, 640, 960)[self.size.currentIndex()]
        return width, max(16, round(width * scene_h / max(1, scene_w)))

    def _capture(self):
        scene = host.snapshot()
        for mesh in scene['meshes']:
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
            text = rdla.scene_text(scene, width, height, self.samples.value(), self.environment.value())
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
            self.renderer.close()

    def closeEvent(self, event):
        self.dispose()
        super().closeEvent(event)
