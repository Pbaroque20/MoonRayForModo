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

    def __init__(self, panel, directory, first, last, fps, step=1, prefix='playblast', width=640, samples=SAMPLES, motion=False):
        super().__init__(panel)
        if last < first or last-first > 100000 or not math.isfinite(fps) or fps <= 0:
            raise ValueError('Invalid playblast frame range or frame rate')
        if not isinstance(step, int) or step < 1:
            raise ValueError('Frame step must be a positive integer')
        if not re.fullmatch(r'[A-Za-z0-9_-]+', prefix):
            raise ValueError('File prefix must use letters, digits, underscores or hyphens')
        self.panel, self.directory, self.prefix, self.fps = panel, Path(directory), prefix, float(fps)
        self.width, self.samples = max(16, int(width)), max(1, int(samples))
        self.motion = bool(motion)
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
        # preview: what cannot be followed through the shutter is shown still, with a notice, rather than the frame refused.
        # MoonLightIPR's: undisplaced, as it displaces the meshes itself (host.by_engine).
        from .host import by_engine
        with by_engine('moonlightipr'):
            snapshot = animation.capture_frame(self.frame/self.fps, panel._settings_values()['surface'] == 2, self.motion, self.fps, preview=True)
        snapshot['frame'] = self.frame
        snapshot['fps'] = self.fps
        # Not spread over the seconds a preview leaves room for edits in, and every sample of it gathered.
        snapshot['_flat_out'] = True
        # Each image at its full size, as a Render has them (moonlightipr_materials).
        snapshot['_full_textures'] = True
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
        # Done or stopped, realtime is left off and RT says so (render_playblast switched it off).
        panel = self.panel
        if panel.ipr_mode.isChecked():
            panel.ipr_mode.setChecked(False)
        if hasattr(panel, '_sync_rt'):
            panel._sync_rt()


class MoonLightIPRAnimation(Playblast):
    """Render Animation with MoonLightIPR (its Engine): each frame rendered as a playblast's is, at the render's own
    resolution and Render Samples a pixel (Render Settings, MoonLightIPR), and written as an EXR from MoonLightIPR's own
    numbers; where the Denoiser is on, its denoised beauty beside it as MoonRay's renders have it (denoising.sidecar,
    frame.denoised.0001.exr), denoised from the same samples, not rendered again. The picture type chosen goes beside them
    or in their place (image_formats), denoised where the render is. Frames already in the folder are kept: refused, or
    passed over with Render missing frames."""

    def __init__(self, panel, directory, first, last, fps, step=1, prefix='frame', width=640, samples=500, motion=False,
                 digits=6, export_as=None, missing=False, denoise=False):
        super().__init__(panel, directory, first, last, fps, step=step, prefix=prefix, width=width, samples=samples, motion=motion)
        from .sequence_plan import frame_name
        self.digits, self.export_as, self.denoise = int(digits), export_as, bool(denoise)
        only = bool(export_as and export_as.get('only'))

        def kept(frame):
            from .image_formats import find
            extension = find(export_as['type'])[2] if only else 'exr'
            return self.directory / frame_name(prefix, frame, self.digits, extension)
        there = [frame for frame in self.frames if kept(frame).exists()]
        if there and not missing:
            raise ValueError('Frames of a sequence named %s are already in this folder (frame %d). Choose another file prefix, '
                             'or enable Render missing frames to render only the others.' % (prefix, there[0]))
        self.frames = [frame for frame in self.frames if frame not in there]
        if not self.frames:
            raise ValueError('Every frame of this sequence is already in the folder.')
        self.total = len(self.frames)
        self.frame = self.frames[0]

    def _alpha_ticked(self):
        """Whether Alpha is ticked in Render Settings' MoonLightIPR Outputs (AOVs) (on in a new scene)."""
        try:
            from . import moonlightipr_aovs, scene_settings
            return 'alpha' in moonlightipr_aovs.listed(scene_settings.complete(self.panel._settings_values_stored()))
        except Exception:
            return True

    def _fresh(self):
        """A frame's pictures not had yet: its beauty, its denoised beauty, its alpha, its Environment background (and the
        AOV looked at before)."""
        self.beauty = self.denoised = self.alpha = self.alpha_before = self.alpha_kept = None
        self.sky = self.sky_before = None
        self.waited = 0

    def start(self):
        # Each frame is rendered looking at the beauty; its denoised picture and its alpha are asked for once it is done
        # (_settled).
        self._fresh()
        self._show('beauty')
        super().start()

    def _show(self, wanted):
        panel = self.panel
        if panel.buffer.currentData() != wanted and panel.buffer.findData(wanted) >= 0:
            panel.buffer.setCurrentIndex(panel.buffer.findData(wanted))

    def _picture(self):
        """The picture MoonLightIPR sent last (its beauty, or its denoised beauty when that is looked at), linear."""
        frame = self.panel.renderer.buffers.progressive_frames.get('beauty') or {}
        return frame.get('linear', {}).get('beauty')

    def next_frame(self):
        self._fresh()
        self._show('beauty')
        super().next_frame()

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
        if self.beauty is None:
            # The beauty is done: kept, then its denoised picture asked for where the Denoiser is on (the session
            # denoises what it has).
            self.beauty = self._picture()
            self.waited = 0
            if self.denoise:
                self.quiet = 0
                self._show('denoised_beauty')
                return
        if self.denoise and self.denoised is None:
            # Until the denoised picture has come (another picture than the beauty), a minute at most.
            if self._picture() is self.beauty:
                self.waited += 1
                if self.waited < 1500:
                    return
                self.poll.stop()
                self.failed('frame %d: MoonLightIPR sent no denoised picture' % self.frame)
                return
            self.denoised = self._picture()
            self.waited = 0
        if self.alpha is None:
            # Then its alpha, MoonLightIPR's own output gathered beside the beauty (sent at once, nothing rendered
            # again), for the EXRs' A channel as MoonRay's renders have it; the AOV looked at before is looked at again.
            from . import moonlightipr_aovs
            session = renderer.moonlightipr
            if self.alpha_kept is None and not self._alpha_ticked():
                # Alpha not ticked in Render Settings' MoonLightIPR Outputs (AOVs): the frame is written without it.
                self.alpha = False
            else:
                if self.alpha_kept is None:
                    self.alpha_kept = session.aov_now
                    self.alpha_before = self.panel._moonlightipr_linear('alpha')
                    session.aov(moonlightipr_aovs.kind('alpha'), 'alpha')
                    self.quiet = 0
                    return
                now = self.panel._moonlightipr_linear('alpha')
                if now is None or now is self.alpha_before:
                    self.waited += 1
                    if self.waited < 1500:
                        return
                    # None came in a minute: the frame is written without it, as it was before alphas were.
                    now = False
                self.alpha = now
                self.waited = 0
        if self.alpha and self.sky is None:
            # With the alpha, the Environment background (the environment seen past everything, gathered with it, sent
            # at once): written beside the beauty as MoonRay's renders have it, and taken out of the colour so that the
            # EXR is premultiplied as theirs are (image_formats.take_out_environment). Without it a soft edge over a
            # visible sky held the sky, and After Effects showed a halo there.
            from . import moonlightipr_aovs
            session = renderer.moonlightipr
            if self.sky_before is None:
                self.sky_before = self.panel._moonlightipr_linear('environment_background') or False
                session.aov(moonlightipr_aovs.kind('environment_background'), 'environment_background')
                self.quiet = 0
                return
            now = self.panel._moonlightipr_linear('environment_background')
            if now is None or now is self.sky_before:
                self.waited += 1
                if self.waited < 1500:
                    return
                # None came in a minute: the frame is written with the environment in its colour, as before.
                now = False
            self.sky = now
        if self.alpha_kept is not None:
            # The AOV looked at before, looked at again.
            renderer.moonlightipr.aov(*self.alpha_kept)
            self.alpha_kept = None
        self.poll.stop()
        alpha = self.alpha or None
        sky = self.sky or None
        try:
            if self.denoise:
                beauty = self._write(self.beauty, alpha=alpha, sky=sky)
                denoised = self._write(self.denoised, denoised=True, alpha=alpha, sky=sky)
                written = beauty if Path(beauty).is_file() else denoised
            else:
                written = self._write(self.beauty, alpha=alpha, sky=sky)
        except Exception as exc:
            self.failed('frame %d could not be written: %s' % (self.frame, exc))
            return
        self.completed.append(written)
        if len(self.completed) == self.total:
            self.stop()
            self.panel.status.setText('Animation complete with MoonLightIPR: %d frames in %s' % (self.total, self.directory))
            self.done.emit(list(self.completed))
        else:
            self.frame = self.frames[len(self.completed)]
            QtCore.QTimer.singleShot(0, self.next_frame)

    def failed(self, message):
        if not self.running:
            return
        self.stop()
        self.panel.status.setText('Animation stopped (MoonLightIPR): ' + message)

    def _write(self, linear, denoised=False, alpha=None, sky=None):
        """The frame as MoonLightIPR rendered it, from its own numbers (linear): an EXR, the denoised one under its
        sidecar name, with its alpha (linear, MoonLightIPR's alpha output) as the A channel where it came, and its
        Environment background (sky, linear) as environment_background.R, G and B, as MoonRay's renders have them; and
        the picture type asked for beside it or in its place, from the denoised picture where there is one. The EXR is
        then made premultiplied (image_formats.take_out_environment). The EXR written (the beauty's name where its
        picture type alone is kept)."""
        import subprocess
        from . import native
        from .denoising import sidecar
        from .sequence_plan import frame_name
        renderer = self.panel.renderer
        if not linear:
            raise ValueError('MoonLightIPR sent no picture for it')
        width, height, pixels = linear
        runtime = Path(renderer.active['runtime']) if getattr(renderer, 'active', None) else native.default_runtime()
        beauty = self.directory / frame_name(self.prefix, self.frame, self.digits, 'exr')
        target = sidecar(beauty) if denoised else beauty
        with tempfile.TemporaryDirectory(prefix='MoonLightIPRFrame-') as folder:
            pfm = Path(folder) / 'frame.pfm'
            with pfm.open('wb') as stream:
                stream.write(('PF\n%d %d\n-1.0\n' % (width, height)).encode('ascii'))
                stream.write(pixels)
            arguments = [str(runtime / 'oiiotool.exe'), str(pfm)]
            if alpha and alpha[:2] == (width, height):
                # Its alpha (grey, as the session sends it) appended as A: R, G, B and A, as MoonRay writes its beauty.
                coverage = Path(folder) / 'alpha.pfm'
                with coverage.open('wb') as stream:
                    stream.write(('PF\n%d %d\n-1.0\n' % (width, height)).encode('ascii'))
                    stream.write(alpha[2])
                arguments += [str(coverage), '--ch', 'R', '--chnames', 'A', '--chappend']
                if sky and sky[:2] == (width, height):
                    seen = Path(folder) / 'environment.pfm'
                    with seen.open('wb') as stream:
                        stream.write(('PF\n%d %d\n-1.0\n' % (width, height)).encode('ascii'))
                        stream.write(sky[2])
                    from .image_formats import BACKGROUND
                    arguments += [str(seen), '--ch', '0,1,2', '--chnames', ','.join(BACKGROUND), '--chappend']
            done = subprocess.run(arguments + ['-o', str(target)], env=native.environment(runtime),
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=300)
        if done.returncode or not target.is_file():
            raise ValueError(done.stdout.decode(errors='replace').strip()[-300:] or 'oiiotool wrote no EXR')
        # The picture type from the last picture of the frame: the denoised one where the Denoiser is on.
        if not self.export_as or (self.denoise and not denoised):
            _premultiplied(runtime, target)
            return str(target)
        from .image_formats import convert, find
        only = self.export_as.get('only')
        shown = beauty.with_suffix('.' + find(self.export_as['type'])[2])
        # With the EXR's alpha, which it has where Alpha is ticked in Render Settings (MoonLightIPR Outputs (AOVs)), as
        # MoonRay's frames have theirs (render.py): straight, the Environment background taken out first.
        convert(runtime, self.export_as['type'], target, shown, getattr(renderer.buffers, 'display', None), self.export_as.get('quality', 92),
                alpha=bool(alpha), background=target)
        if only:
            target.unlink()
            if denoised and beauty.is_file():
                beauty.unlink()
            return str(shown)
        _premultiplied(runtime, target)
        return str(target)



def _premultiplied(runtime, target):
    """A MoonLightIPR frame's EXR made premultiplied, as a MoonRay render's is (MoonRay Source Override "Premultiplied
    OpenEXR alpha", image_formats.take_out_environment), once the picture type beside it has been made from it as it was;
    left as written where it cannot be."""
    from .image_formats import take_out_environment
    try:
        take_out_environment(runtime, target)
    except (OSError, RuntimeError, ValueError):
        pass


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
    def __init__(self, settings, width, widest, denoised, parent=None, motion=False):
        super().__init__(parent)
        self.motion = motion
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
        self.summary.setText('%d frames · %s.%06d.png, rendered by MoonLightIPR whichever engine is chosen, %s%s. Frames already in the folder are written over.'
                             % (count, self.prefix.text(), self.first.value(), 'with motion blur, ' if self.motion else '',
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
