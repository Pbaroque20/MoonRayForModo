"""MoonLightIPR Playblast: an animation rendered on the graphics card, a PNG a frame, to look at how it moves.

Each frame is read from the scene inside a Modo command, as an animation's frames are, rendered by MoonLightIPR into
the preview window, and saved from there as it is shown. It is a quick look, not an output: a frame already there is
written over."""
from pathlib import Path
import math
import re
import tempfile
from PySide2 import QtCore, QtGui, QtWidgets
import lx
from . import animation

SAMPLES = 32


class Playblast(QtCore.QObject):
    done = QtCore.Signal(list)

    def __init__(self, panel, directory, first, last, fps, step=1, prefix='playblast', width=640, samples=SAMPLES):
        super().__init__(panel)
        if last < first or last-first > 100000 or not math.isfinite(fps) or fps <= 0:
            raise ValueError('Invalid playblast frame range or frame rate')
        if not isinstance(step, int) or step < 1:
            raise ValueError('Frame step must be a positive integer')
        if not re.fullmatch(r'[A-Za-z0-9_-]+', prefix):
            raise ValueError('File prefix must use letters, digits, underscores or hyphens')
        self.panel, self.directory, self.prefix, self.fps = panel, Path(directory), prefix, float(fps)
        self.width, self.samples = max(16, int(width)), max(1, int(samples))
        self.frames = list(range(first, last+1, step))
        self.total = len(self.frames)
        self.frame = first
        # What the window reads of a sequence that is running: the frame it is on and those it has done.
        self.completed = []
        self.running = self.waiting = False
        self.quiet = 0
        # A frame is finished a moment before its last picture is on screen: that is waited for.
        self.poll = QtCore.QTimer(self)
        self.poll.setInterval(40)
        self.poll.timeout.connect(self._settled)

    def start(self):
        if animation.active is not None and animation.active.running:
            raise ValueError('An animation render is already running')
        self.directory.mkdir(parents=True, exist_ok=True)
        animation.active = self
        self.running = True
        renderer = self.panel.renderer
        renderer.moonlightipr_samples = self.samples
        renderer.finished.connect(self.finished)
        renderer.failed.connect(self.failed)
        self.next_frame()

    def next_frame(self):
        if self.running:
            try:
                lx.eval('moonray.animationFrame')
            except Exception as exc:
                self.failed(str(exc))

    def capture(self):
        """Called from within the Modo command: the scene at this frame, handed to MoonLightIPR as a preview."""
        if not self.running:
            return
        panel = self.panel
        snapshot = animation.capture_frame(self.frame/self.fps, panel._settings_values()['surface'] == 2, False, self.fps)
        snapshot['frame'] = self.frame
        snapshot['fps'] = self.fps
        self.waiting = True
        panel._submit(panel._configure_snapshot(snapshot))

    def finished(self, output):
        if not self.running or output or not self.waiting:
            return
        self.waiting = False
        self.quiet = 0
        self.poll.start()

    def _settled(self):
        if not self.running:
            self.poll.stop()
            return
        renderer = self.panel.renderer
        if getattr(renderer, 'moonlightipr_frame', None) is not None or renderer.buffers.busy():
            self.quiet = 0
            return
        self.quiet += 1
        if self.quiet < 2:
            return
        self.poll.stop()
        path = self.directory/('%s.%06d.png' % (self.prefix, self.frame))
        image = self.panel.preview.image
        if image.isNull() or not image.save(str(path)):
            self.failed('Cannot write '+str(path))
            return
        self.completed.append(str(path))
        if len(self.completed) == self.total:
            self.stop()
            self.panel.status.setText('Playblast done: %d frames in %s' % (self.total, self.directory))
            self.done.emit(list(self.completed))
        else:
            self.frame = self.frames[len(self.completed)]
            QtCore.QTimer.singleShot(0, self.next_frame)

    def failed(self, message):
        if not self.running:
            return
        self.stop()
        self.panel.status.setText('Playblast stopped: '+message)

    def stop(self, status='canceled'):
        if not self.running:
            return
        self.running = self.waiting = False
        self.poll.stop()
        if animation.active is self:
            animation.active = None
        renderer = self.panel.renderer
        renderer.finished.disconnect(self.finished)
        renderer.failed.disconnect(self.failed)
        renderer.moonlightipr_samples = None
        renderer.stop()


def scene_range():
    """The frames and rate of the scene: what a playblast is offered at first."""
    try:
        import modo
        scene = modo.Scene()
        first, last = scene.currentRange
        return int(first), int(last), float(scene.fps)
    except Exception:
        return 1, 1, 24.0


class PlayblastDialog(QtWidgets.QDialog):
    def __init__(self, settings, width, widest, denoised, parent=None):
        super().__init__(parent)
        self.setWindowTitle('MoonLightIPR Playblast')
        self.resize(520, 300)
        form = QtWidgets.QFormLayout(self)
        row = QtWidgets.QHBoxLayout()
        self.folder = QtWidgets.QLineEdit(str(settings.value('output/playblast', '') or Path(tempfile.gettempdir()).resolve()/'MoonLightIPR-Playblast'))
        browse = QtWidgets.QPushButton('Browse…')
        browse.clicked.connect(self.browse)
        row.addWidget(self.folder, 1)
        row.addWidget(browse)
        form.addRow('Output folder', row)
        self.prefix = QtWidgets.QLineEdit('playblast')
        form.addRow('File prefix', self.prefix)
        first, last, fps = scene_range()
        self.first = QtWidgets.QSpinBox(); self.first.setRange(-100000, 100000); self.first.setValue(first)
        self.last = QtWidgets.QSpinBox(); self.last.setRange(-100000, 100000); self.last.setValue(last)
        self.step = QtWidgets.QSpinBox(); self.step.setRange(1, 100000); self.step.setValue(1)
        self.fps = QtWidgets.QDoubleSpinBox(); self.fps.setRange(.001, 1000); self.fps.setDecimals(3); self.fps.setValue(fps)
        self.width = QtWidgets.QSpinBox(); self.width.setRange(16, max(16, int(widest))); self.width.setValue(min(int(widest), int(width)))
        self.width.setToolTip("How wide each frame is rendered, in pixels, up to the camera's own width. Its height follows the camera's shape.")
        self.samples = QtWidgets.QSpinBox(); self.samples.setRange(1, 4096); self.samples.setValue(int(settings.value('output/playblast_samples', SAMPLES) or SAMPLES))
        self.samples.setToolTip('How many times MoonLightIPR samples each pixel of a frame. Fewer is quicker and grainier.')
        form.addRow('First frame', self.first)
        form.addRow('Last frame', self.last)
        form.addRow('Frame step', self.step)
        form.addRow('Frames per second', self.fps)
        form.addRow('Width', self.width)
        form.addRow('Samples a frame', self.samples)
        self.play = QtWidgets.QCheckBox('Play it when it is done')
        self.play.setChecked(True)
        form.addRow(self.play)
        self.denoised = denoised
        self.summary = QtWidgets.QLabel()
        self.summary.setWordWrap(True)
        form.addRow(self.summary)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText('Playblast')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        for control in (self.first, self.last, self.step):
            control.valueChanged.connect(self.update_summary)
        self.prefix.textChanged.connect(self.update_summary)
        self.update_summary()

    def browse(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, 'Playblast folder', self.folder.text())
        if folder:
            self.folder.setText(folder)

    def update_summary(self, *args):
        count = max(0, (self.last.value()-self.first.value())//self.step.value()+1)
        self.summary.setText('%d frames · %s.%06d.png, rendered by MoonLightIPR whichever engine is chosen, %s. Frames already in the folder are written over.'
                             % (count, self.prefix.text(), self.first.value(),
                                'denoised, as Denoised Beauty is the buffer chosen' if self.denoised else 'not denoised: choose Denoised Beauty in the window first to have them denoised'))

    def accept(self):
        if not self.folder.text().strip() or not Path(self.folder.text().strip()).is_absolute():
            QtWidgets.QMessageBox.warning(self, 'Output folder', 'Choose an absolute output folder.'); return
        if self.last.value() < self.first.value() or self.last.value()-self.first.value() > 100000:
            QtWidgets.QMessageBox.warning(self, 'Frame range', 'Last frame must follow first frame, with at most 100001 frame positions.'); return
        if not re.fullmatch(r'[A-Za-z0-9_-]+', self.prefix.text()):
            QtWidgets.QMessageBox.warning(self, 'File prefix', 'Use letters, digits, underscores or hyphens.'); return
        super().accept()


class Player(QtWidgets.QDialog):
    """The frames of a playblast, played at its rate, round and round."""

    def __init__(self, files, fps, parent=None):
        super().__init__(parent)
        self.setWindowTitle('MoonLightIPR Playblast')
        self.files = list(files)
        self.frames = {}
        self.picture = QtWidgets.QLabel()
        self.picture.setAlignment(QtCore.Qt.AlignCenter)
        self.picture.setMinimumSize(320, 180)
        self.picture.setStyleSheet('background:#101010')
        self.toggle = QtWidgets.QPushButton('Pause')
        self.toggle.clicked.connect(self.switch)
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.setRange(0, max(0, len(self.files)-1))
        self.slider.valueChanged.connect(self.show_frame)
        self.name = QtWidgets.QLabel()
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.toggle)
        row.addWidget(self.slider, 1)
        row.addWidget(self.name)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.picture, 1)
        layout.addLayout(row)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(max(1, round(1000/max(.001, float(fps)))))
        self.timer.timeout.connect(self.advance)
        self.show_frame(0)
        first = self.frames.get(0)
        if first is not None and not first.isNull():
            self.resize(min(1280, first.width())+24, min(800, first.height())+70)
        if len(self.files) > 1:
            self.timer.start()
        else:
            self.toggle.setEnabled(False)

    def switch(self):
        if self.timer.isActive():
            self.timer.stop()
        else:
            self.timer.start()
        self.toggle.setText('Pause' if self.timer.isActive() else 'Play')

    def advance(self):
        self.slider.setValue((self.slider.value()+1) % max(1, len(self.files)))

    def show_frame(self, index):
        if not self.files:
            return
        if index not in self.frames:
            self.frames[index] = QtGui.QPixmap(self.files[index])
        frame = self.frames[index]
        self.name.setText(Path(self.files[index]).name)
        if not frame.isNull():
            self.picture.setPixmap(frame.scaled(self.picture.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.show_frame(self.slider.value())

    def closeEvent(self, event):
        self.timer.stop()
        super().closeEvent(event)
