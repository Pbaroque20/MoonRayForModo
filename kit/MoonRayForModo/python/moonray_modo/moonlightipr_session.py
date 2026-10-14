"""A private MoonLightIPR GPU preview process, fed acknowledged and coalesced scene snapshots."""
import os
import tempfile
from pathlib import Path
from PySide2 import QtCore
from .threads import forgotten
from . import moonlightipr_scene

EXECUTABLE = 'moonlightipr_session.exe'
PROGRAM = 'MoonLightIPRKernel.ptx'


def directory(runtime):
    """MoonLightIPR ships in the runtime's moonlightipr folder; a development build can be named instead."""
    supplied = os.environ.get('MOONRAY_MODO_MOONLIGHTIPR', '')
    if supplied:
        return Path(supplied)
    # MoonLightIPR does not depend on the MoonRay build, so the copy bundled with the kit
    # serves any other runtime the user selects.
    # It does depend on the plugin, whose scenes it reads: another runtime may carry the MoonLightIPR of another
    # version, which would refuse them. So the kit's own copy is the one used wherever there is one.
    bundled = Path(__file__).resolve().parents[2] / 'runtime' / 'moonlightipr'
    selected = Path(runtime) / 'moonlightipr'
    return bundled if supported(bundled) else selected


def supported(directory):
    """MoonLightIPR needs its executable, its device program and the CUDA runtime side by side."""
    directory = Path(directory)
    return (directory / EXECUTABLE).is_file() and (directory / PROGRAM).is_file() and any(directory.glob('cudart64_*.dll'))


class Packer(QtCore.QThread):
    """A snapshot made into what the session reads, away from Modo's own thread: the snapshot is plain data, and
    making it into bytes asks Modo nothing. Modo is then free to move its view while a followed edit is on its way."""

    def __init__(self, request, known, path, parent=None):
        super().__init__(parent)
        self.request, self.known, self.path = request, set(known), path
        self.outcome = None
        # Set when the scene is no longer wanted by the time it is ready: stopped, or the process gone.
        self.abandoned = False

    @forgotten
    def run(self):
        request = self.request
        try:
            from .serialization import WRITING
            with WRITING:
                payload, keys, warnings = moonlightipr_scene.pack(request['snapshot'], request['width'], request['height'],
                    request['environment'], self.known, request['samples'], request['denoise'], request['runtime'])
            self.path.write_bytes(payload)
            self.outcome = (keys, warnings, '')
        except Exception as exc:
            self.outcome = (None, None, str(exc) or type(exc).__name__)


class Session(QtCore.QObject):
    output = QtCore.Signal(str)
    ready = QtCore.Signal(int)
    memory_image = QtCore.Signal(object)
    acknowledged = QtCore.Signal(int)
    warnings = QtCore.Signal(object)
    failed = QtCore.Signal(str)
    status = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QtCore.QProcess(self)
        self.process.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.finished.connect(self._exit)
        self.process.errorOccurred.connect(self._error)
        self.workspace = tempfile.TemporaryDirectory(prefix='MoonLightIPRSession-')
        self.root = Path(self.workspace.name)
        self.latest = None; self.sent = None; self.current = None; self.directory = None
        # Mesh keys the running process is known to hold; their data is not sent again.
        self.known = set()
        self.partial = ''; self.stopping = False; self.closed = False
        # The scene being made ready on another thread, if one is.
        self.packer = None
        self.packer_poll = QtCore.QTimer(self); self.packer_poll.setSingleShot(True); self.packer_poll.setInterval(5)
        self.packer_poll.timeout.connect(self._packed)
        # Modo ending while a scene is being made ready: the thread is let finish, not cut off under it.
        application = QtCore.QCoreApplication.instance()
        if application is not None: application.aboutToQuit.connect(self._quitting)
        from .idle_release import IdleRelease
        self.idle = IdleRelease(self, self._release_idle, lambda: self.running() and not self.stopping and self.sent is None and self.latest is None and self.packer is None)

    def running(self): return self.process.state() != QtCore.QProcess.NotRunning

    def submit(self, snapshot, directory, width, height, environment, generation, samples=256, denoise=True, runtime=None):
        """runtime is the MoonRay folder whose oiiotool converts textures."""
        self.idle.cancel()
        request = dict(snapshot=snapshot, directory=Path(directory), width=width, height=height, environment=environment,
                       id=generation, samples=samples, denoise=denoise, runtime=runtime)
        self.latest = request
        if self.running() and request['directory'] != self.directory:
            self.stopping = True; self.process.kill(); return
        if self.stopping: return
        if not self.running(): self._launch()
        elif self.sent is None: self._dispatch()

    def _launch(self):
        request = self.latest
        if not request or self.closed: return
        self.partial = ''; self.sent = None; self.known = set(); self.directory = request['directory']
        # A scene made ready for the process before this one left out what that one held.
        self._abandon()
        env = QtCore.QProcessEnvironment.systemEnvironment()
        # A child process must not load Modo's Python/Qt libraries.
        for key in ('PYTHONHOME', 'PYTHONPATH', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH'): env.remove(key)
        env.insert('PATH', str(self.directory) + ';' + env.value('PATH', ''))
        self.process.setProcessEnvironment(env); self.process.setWorkingDirectory(str(self.root))
        self.process.setProgram(str(self.directory / EXECUTABLE))
        self.process.setArguments([str(self.directory / PROGRAM)])
        self.status.emit('Starting MoonLightIPR GPU preview')
        self.process.start()
        self._dispatch()

    def _quitting(self):
        if self.packer is not None:
            self.packer.abandoned = True; self.packer.wait(5000)

    def _abandon(self):
        if self.packer is not None: self.packer.abandoned = True

    def _dispatch(self):
        """Begin making the newest scene ready. One at a time: a newer one waits in latest and takes its turn when
        this one has been sent and applied, so edits that come faster than they can be shown are run together."""
        request = self.latest
        if not request or self.sent is not None or self.packer is not None: return
        self.latest = None
        self.packer = Packer(request, self.known, self.root / ('%d.mls' % request['id']), self)
        self.packer.finished.connect(self._packed)
        self.packer.start()

    def _packed(self):
        worker = self.packer
        if worker is None: return
        # finished may arrive while the thread is still unwinding: it is kept until it has ended.
        if not worker.wait(0):
            self.packer_poll.start(); return
        self.packer_poll.stop()
        self.packer = None
        request, path = worker.request, worker.path
        keys, warnings, error = worker.outcome or (None, None, 'The scene was not made ready')
        worker.deleteLater()
        if self.closed: return
        if worker.abandoned or self.stopping or not self.running():
            try: path.unlink()
            except OSError: pass
            if not self.stopping: self._dispatch()
            return
        if error:
            self.failed.emit('MoonLightIPR cannot preview this scene: ' + error); return
        self.warnings.emit(warnings)
        self.process.write(('scene %d %s\n' % (request['id'], path)).encode('utf-8'))
        self.sent = dict(request, keys=keys, path=path)
        self.current = request['id']
        # The picture looked at is said again with every scene: a session newly started has not been told.
        self.process.write(b'view 0 denoised\n' if getattr(self, 'denoised_view', True) else b'view 0 beauty\n')

    def _read(self):
        text = self.process.readAllStandardOutput().data().decode('utf-8', errors='replace')
        self.output.emit(text)
        self.partial += text
        while '\n' in self.partial:
            line, self.partial = self.partial.split('\n', 1)
            if line.startswith('@@MODO_SHARED '):
                try:
                    from .shared_image import receive
                    packet = receive(line, self.process.processId())
                    # A frame of a scene that has since been replaced is acknowledged but not shown.
                    if not self.stopping and not self.closed and not self.latest and packet[0] == self.current: self.memory_image.emit(packet)
                except (ValueError, OSError) as exc: self.status.emit('MoonLightIPR frame skipped: ' + str(exc))
                continue
            if not line.startswith('@@MODO_SESSION '): continue
            parts = line.strip().split()
            if len(parts) != 3: continue
            try: generation = int(parts[2])
            except ValueError: continue
            if self.stopping or self.closed: continue
            if parts[1] in ('APPLIED', 'FAILED') and self.sent and generation == self.sent['id']:
                sent, self.sent = self.sent, None
                try: sent['path'].unlink()
                except OSError: pass
                if parts[1] == 'APPLIED':
                    self.known = sent['keys']; self.acknowledged.emit(generation)
                else: self.failed.emit('MoonLightIPR rejected the scene. Open Render Log for details.')
                self._dispatch()
            elif parts[1] == 'DONE' and not self.latest and generation == self.current:
                self.idle.arm()
                self.ready.emit(generation)
        self.partial = self.partial[-65536:]

    def _error(self, error):
        if error == QtCore.QProcess.FailedToStart and not self.stopping and not self.closed:
            self.sent = None
            self.failed.emit('Cannot start MoonLightIPR: ' + self.process.errorString())

    def _exit(self, code, status):
        self.idle.cancel()
        self._read()
        self.sent = None; self.known = set()
        # What was being made ready for this process is made ready again for the next, which holds nothing yet.
        if self.packer is not None and not self.packer.abandoned:
            self.packer.abandoned = True
            if self.latest is None: self.latest = self.packer.request
        if self.stopping:
            self.stopping = False
            if self.latest and not self.closed: self._launch()
        elif not self.closed:
            self.failed.emit('MoonLightIPR exited (0x%08X). Refresh to start a new session; see Render Log.' % (code & 0xffffffff))

    def view(self, denoised):
        """Say which picture of a denoised scene is looked at: the denoised one, or the beauty as it is rendered.
        The session has both all the while and sends the one asked for, at once."""
        self.denoised_view = bool(denoised)
        if self.running() and not self.stopping and not self.closed:
            self.process.write(('view %d %s\n' % (self.current or 0, 'denoised' if denoised else 'beauty')).encode('utf-8'))

    def finish(self):
        """Stop sampling and have what is rendered so far sent as the finished picture. Returns whether there is a
        render under way to finish; if there is, ready is reported as at the end of any render."""
        self.latest = None; self._abandon()
        if not self.running() or self.stopping or self.closed or self.current is None or self.sent is not None:
            return False
        self.process.write(('finish %d\n' % self.current).encode('utf-8'))
        return True

    def stop(self):
        """Stop sampling but keep the process and its loaded meshes, so the next preview starts at once."""
        self.latest = None; self.current = None; self._abandon()
        if self.running() and not self.stopping:
            self.process.write(b'pause\n')
            self.idle.arm()

    def _release_idle(self):
        self.release()
        self.status.emit("Idle MoonLightIPR released its GPU memory. Cached images are kept; the next render reloads the scene.")

    def release(self):
        """End the process and free the GPU, for when another renderer takes over."""
        self.idle.cancel()
        self.latest = None; self.sent = None; self.current = None; self._abandon()
        if self.running(): self.stopping = True; self.process.kill()

    def close(self):
        self.closed = True; self.release()
        if self.packer is not None: self.packer.wait(5000)
        if self.running(): self.process.waitForFinished(2000)
        if not self.running(): self.workspace.cleanup()
