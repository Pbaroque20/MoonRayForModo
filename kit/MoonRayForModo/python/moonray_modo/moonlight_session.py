"""A private MoonLight GPU preview process, fed acknowledged and coalesced scene snapshots."""
import os
import tempfile
from pathlib import Path
from PySide2 import QtCore
from . import moonlight_scene

EXECUTABLE = 'moonlight_session.exe'
PROGRAM = 'MoonLightKernel.ptx'


def directory(runtime):
    """MoonLight ships in the runtime's moonlight folder; a development build can be named instead."""
    supplied = os.environ.get('MOONRAY_MODO_MOONLIGHT', '')
    if supplied:
        return Path(supplied)
    # MoonLight does not depend on the MoonRay build, so the copy bundled with the kit
    # serves any other runtime the user selects.
    bundled = Path(__file__).resolve().parents[2] / 'runtime' / 'moonlight'
    selected = Path(runtime) / 'moonlight'
    return bundled if not supported(selected) and supported(bundled) else selected


def supported(directory):
    """MoonLight needs its executable, its device program and the CUDA runtime side by side."""
    directory = Path(directory)
    return (directory / EXECUTABLE).is_file() and (directory / PROGRAM).is_file() and any(directory.glob('cudart64_*.dll'))


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
        self.workspace = tempfile.TemporaryDirectory(prefix='MoonLightSession-')
        self.root = Path(self.workspace.name)
        self.latest = None; self.sent = None; self.current = None; self.directory = None
        # Mesh keys the running process is known to hold; their data is not sent again.
        self.known = set()
        self.partial = ''; self.stopping = False; self.closed = False

    def running(self): return self.process.state() != QtCore.QProcess.NotRunning

    def submit(self, snapshot, directory, width, height, environment, generation, samples=256, denoise=True, runtime=None):
        """runtime is the MoonRay folder whose oiiotool converts textures."""
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
        env = QtCore.QProcessEnvironment.systemEnvironment()
        # A child process must not load Modo's Python/Qt libraries.
        for key in ('PYTHONHOME', 'PYTHONPATH', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH'): env.remove(key)
        env.insert('PATH', str(self.directory) + ';' + env.value('PATH', ''))
        self.process.setProcessEnvironment(env); self.process.setWorkingDirectory(str(self.root))
        self.process.setProgram(str(self.directory / EXECUTABLE))
        self.process.setArguments([str(self.directory / PROGRAM)])
        self.status.emit('Starting MoonLight GPU preview')
        self.process.start()
        self._dispatch()

    def _dispatch(self):
        request = self.latest
        if not request or self.sent is not None: return
        try:
            payload, keys, warnings = moonlight_scene.pack(request['snapshot'], request['width'], request['height'],
                request['environment'], self.known, request['samples'], request['denoise'], request['runtime'])
            path = self.root / ('%d.mls' % request['id'])
            path.write_bytes(payload)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.latest = None
            self.failed.emit('MoonLight cannot preview this scene: ' + str(exc)); return
        self.warnings.emit(warnings)
        self.process.write(('scene %d %s\n' % (request['id'], path)).encode('utf-8'))
        self.sent = dict(request, keys=keys, path=path)
        self.latest = None
        self.current = request['id']

    def _read(self):
        text = bytes(self.process.readAllStandardOutput()).decode('utf-8', errors='replace')
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
                except (ValueError, OSError) as exc: self.status.emit('MoonLight frame skipped: ' + str(exc))
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
                else: self.failed.emit('MoonLight rejected the scene. Open Render Log for details.')
                self._dispatch()
            elif parts[1] == 'DONE' and not self.latest and generation == self.current:
                self.ready.emit(generation)
        self.partial = self.partial[-65536:]

    def _error(self, error):
        if error == QtCore.QProcess.FailedToStart and not self.stopping and not self.closed:
            self.sent = None
            self.failed.emit('Cannot start MoonLight: ' + self.process.errorString())

    def _exit(self, code, status):
        self._read()
        self.sent = None; self.known = set()
        if self.stopping:
            self.stopping = False
            if self.latest and not self.closed: self._launch()
        elif not self.closed:
            self.failed.emit('MoonLight exited (0x%08X). Refresh to start a new session; see Render Log.' % (code & 0xffffffff))

    def stop(self):
        """Stop sampling but keep the process and its loaded meshes, so the next preview starts at once."""
        self.latest = None; self.current = None
        if self.running() and not self.stopping: self.process.write(b'pause\n')

    def release(self):
        """End the process and free the GPU, for when another renderer takes over."""
        self.latest = None; self.sent = None; self.current = None
        if self.running(): self.stopping = True; self.process.kill()

    def close(self):
        self.closed = True; self.release()
        if self.running(): self.process.waitForFinished(2000)
        if not self.running(): self.workspace.cleanup()
