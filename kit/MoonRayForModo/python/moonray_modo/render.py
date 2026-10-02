"""Asynchronous native renderer lifecycle; no Modo API calls here."""
from pathlib import Path
import shutil
import tempfile
import uuid
from PySide2 import QtCore
from . import native, rdla


class Renderer(QtCore.QObject):
    image_ready = QtCore.Signal(str)
    status = QtCore.Signal(str)
    failed = QtCore.Signal(str)
    finished = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QtCore.QProcess(self)
        self.process.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.finished.connect(self._exited)
        self.process.errorOccurred.connect(self._error)
        self.directory = tempfile.TemporaryDirectory(prefix='MoonRayForModo-')
        self.pending = None
        self.active = None
        self.canceled = False
        self.closed = False
        self.log = ''
        self.backend_status = 'CPU'
        self.backend_log = ''
        self.phase = 'render'
        self.generation = 0
        self.timeout_seconds = 0
        self.watchdog = QtCore.QTimer(self)
        self.watchdog.setSingleShot(True)
        self.watchdog.timeout.connect(self._timed_out)
        self.process.started.connect(self._started)

    def _started(self):
        if self.timeout_seconds>0:
            self.watchdog.start(min(2147483647,int(self.timeout_seconds*1000)))

    def _timed_out(self):
        if self.closed or self.canceled:
            return
        self.stop()
        self.failed.emit('Render exceeded the configured time limit; it was stopped. Completed outputs were preserved.')

    def submit(self, snapshot, runtime, width, height, samples, environment, threads, output=None, linear_preview=False):
        if self.closed:
            raise ValueError('Renderer is closed')
        runtime = native.find_runtime(runtime)
        self.generation += 1
        request = dict(snapshot=snapshot, runtime=runtime, width=width, height=height, generation=self.generation,
                       samples=samples, environment=environment, threads=threads, output=output,
                       linear_preview=linear_preview)
        # New edits replace queued work; stale images never reach the panel.
        self.pending = request
        if self.process.state() != QtCore.QProcess.NotRunning:
            self.canceled = True
            self.process.kill()
        else:
            self._begin_pending()

    def stop(self):
        self.watchdog.stop()
        self.pending = None
        self.canceled = True
        if self.process.state() != QtCore.QProcess.NotRunning:
            self.process.kill()
        self.status.emit('Stopped')

    def _begin_pending(self):
        if self.closed or not self.pending:
            return
        self.active, self.pending = self.pending, None
        for path in Path(self.directory.name).iterdir():
            if path.is_file():
                path.unlink()
        self.canceled = False
        target = int(self.active['samples'])
        self.passes = [target] if self.active['output'] else sorted(set([1, min(2, target), target]))
        self.log = ''
        self._begin_pass(self.active['generation'])

    def _begin_pass(self, generation):
        if self.closed or self.canceled or self.active['generation'] != generation:
            return
        request = self.active
        self.sample_grid = self.passes.pop(0)
        self.current_base = Path(self.directory.name) / uuid.uuid4().hex
        scene = self.current_base.with_suffix('.rdla')
        self.image_path = self.current_base.with_suffix('.exr')
        self.phase = 'render'
        self.backend_log = ''
        self.gpu_error = False
        mode=request['snapshot'].get('execution_mode','vectorized')
        self.backend_status='XPU requested' if mode=='xpu' else 'CPU '+mode
        self.buffer_key = request['snapshot'].get('preview_buffer','beauty') if not request['output'] and not request.get('linear_preview') else 'beauty'
        self.buffer_path = self.current_base.with_suffix('.buffer.exr')
        snapshot = dict(request['snapshot'],preview_buffer=self.buffer_key)
        if not request['output'] and not request.get('linear_preview'):
            snapshot['preview_buffer_file']=str(self.buffer_path)
        else:
            snapshot.pop('preview_buffer_file',None)
        try:
            if mode=='xpu' and not native.supports_xpu(request['runtime']):
                raise ValueError('The selected runtime has no XPU GPU program/CUDA runtime. Choose the XPU runtime or CPU mode.')
            text = rdla.scene_text(snapshot, request['width'], request['height'],
                                   self.sample_grid, request['environment'],
                                   str(self.image_path) if request['output'] else None)
            scene.write_text(text, encoding='utf-8')
            env = QtCore.QProcessEnvironment()
            for key, value in native.environment(request['runtime']).items():
                env.insert(key, value)
            self.process.setProcessEnvironment(env)
            self.process.setWorkingDirectory(self.directory.name)
            self.process.setProgram(str(request['runtime'] / 'moonray.exe'))
            self.process.setArguments(native.arguments(scene, self.image_path, request['threads'],mode))
            self.status.emit('Rendering %d samples/pixel · %s…' % (self.sample_grid ** 2,self.backend_status))
            self.process.start()
        except Exception as exc:
            self.failed.emit(str(exc))

    def _read(self):
        text = bytes(self.process.readAllStandardOutput()).decode('utf-8', errors='replace')
        self.log = (self.log + text)[-65536:]
        if self.phase=='render':
            self.backend_log=(self.backend_log+text)[-16384:]
            if any(term in self.backend_log for term in ('optixLaunch() failure','cudaStreamSynchronize() error')):
                self.gpu_error=True
            if 'falling back to CPU' in self.backend_log:
                self.backend_status='CPU fallback — see Render Log'
            elif 'GPU: Setup complete' in self.backend_log:
                self.backend_status='XPU active (NVIDIA GPU + CPU)'
            if any(word in text for word in ('GPU:', 'falling back')):
                self.status.emit('Rendering · '+self.backend_status)

    def _error(self, error):
        if self.closed or self.canceled:
            return
        if error == QtCore.QProcess.FailedToStart:
            self.failed.emit('Cannot start MoonRay: ' + self.process.errorString())

    def _exited(self, code, exit_status):
        self.watchdog.stop()
        self._read()
        if self.closed:
            return
        if self.canceled:
            self._begin_pending()
            return
        if code != 0 or exit_status != QtCore.QProcess.NormalExit:
            status = code & 0xffffffff
            message = ('Buffer conversion' if self.phase=='convert' else 'MoonRay') + ' failed (0x%08X). Open Render Log for details.' % status
            if status == 0xC000001D:
                message = ('MoonRay used an unsupported CPU instruction. This Windows runtime needs '
                           'a CPU-compatible rebuild. No render was produced.')
            self.failed.emit(message)
            return
        if self.phase=='render' and self.gpu_error:
            self.failed.emit('GPU execution failed. Open Render Log for details or select CPU (AVX).')
            return
        if self.phase=='render' and not self.active['output'] and not self.active.get('linear_preview'):
            if not self.buffer_path.is_file() or self.buffer_path.stat().st_size<16:
                self.failed.emit('MoonRay did not produce the selected render buffer.')
                return
            from .buffers import conversion
            converter=self.active['runtime']/'oiiotool.exe'
            if not converter.is_file():
                self.failed.emit('Render-buffer preview requires oiiotool.exe in the selected runtime.')
                return
            self.phase='convert'
            self.image_path=self.current_base.with_suffix('.buffer.png')
            self.process.setProgram(str(converter))
            try:
                arguments=conversion(self.buffer_key,self.buffer_path,self.image_path,self.active['snapshot'].get('display',{}))
            except ValueError as exc:
                self.failed.emit(str(exc))
                return
            self.process.setArguments(arguments)
            self.status.emit('Updating render-buffer preview...')
            self.process.start()
            return
        if not self.image_path.is_file() or self.image_path.stat().st_size < 16:
            self.failed.emit('MoonRay exited without a valid output image. Open Render Log for details.')
            return
        if self.active['output']:
            destination = Path(self.active['output'])
            # Never truncate an existing user render if the renderer crashes.
            staged = destination.with_name(destination.name + '.' + uuid.uuid4().hex + '.tmp')
            try:
                shutil.copyfile(str(self.image_path), str(staged))
                staged.replace(destination)
            except OSError as exc:
                if staged.exists():
                    staged.unlink()
                self.failed.emit('Cannot save render: ' + str(exc))
                return
            self.finished.emit(str(destination))
            return
        self.image_ready.emit(str(self.image_path))
        if self.passes:
            generation = self.active['generation']
            QtCore.QTimer.singleShot(0, lambda: self._begin_pass(generation))
        else:
            self.finished.emit('')

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.stop()
        if self.process.state() != QtCore.QProcess.NotRunning:
            self.process.waitForFinished(2000)
        if self.process.state() == QtCore.QProcess.NotRunning:
            self.directory.cleanup()
