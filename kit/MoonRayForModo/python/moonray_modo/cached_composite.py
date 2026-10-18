"""Make the Composite buffer of a finished render from the buffers it has kept, without touching the renderer."""
from pathlib import Path
import shutil
import tempfile
from PySide2 import QtCore
from . import compositor, native, outputs
from . import terminal


class CachedComposite(QtCore.QObject):
    """Runs the scene's compositor graph over the kept frame, one node after another, and adds what it makes to the
    frame as its composite buffer. Asked again with another graph, or of another frame, while it is at work, it
    finishes what it is at and then does what was last asked."""
    def __init__(self, cache):
        super().__init__(cache)
        self.cache = cache; self.job = None; self.requested = None; self.directory = None; self.steps = []; self.log = ''
        self.expected = None; self.result = None
        self.process = QtCore.QProcess(self)
        terminal.watch(self.process, 'Compositor')
        self.process.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.error)

    def wanted(self, frame, graph):
        """What tells this frame's composite by this graph from any other, or None where there is none to make: no
        graph, one that does nothing, or one that cannot be made yet."""
        if frame is None or frame.get('partial') or frame.get('snapshot', {}).get('_ipr') or compositor.trivial(graph):
            return None
        needed = compositor.buffers(graph)
        if 'denoised_beauty' in needed and 'denoised_beauty' not in frame['files']:
            # The denoiser has not finished, or is off: asked again when it has.
            return None
        return compositor.signature(graph) + ':' + str(frame.get('denoise_engine') if 'denoised_beauty' in needed else '')

    def request(self, graph):
        """Have the composite made by this graph, where it is not made already. Returns nothing; the cache says when
        it is ready or why it cannot be."""
        self.requested = graph
        if self.job is not None or self.cache.closed:
            return
        frame = self.cache.frame
        try:
            wanted = self.wanted(frame, graph)
        except ValueError as exc:
            self.cache.notice.emit('Compositor: ' + str(exc)); return
        if wanted is None:
            if frame is not None and frame['files'].pop('composite', None) is not None:
                # The graph has been emptied: the frame has no composite any more.
                frame.pop('composite_signature', None)
                self.cache.serial += 1; self.cache._request()
            return
        if frame.get('composite_signature') == wanted and 'composite' in frame['files']:
            return
        try:
            self.directory = tempfile.TemporaryDirectory(prefix='MoonRayComposite-')
            root = Path(self.directory.name)
            # Each Cryptomatte node is a picture of its matte, made from the render's Cryptomatte buffer.
            from . import cryptomatte_pick
            ran, files = compositor.lowered(graph, frame['files'], lambda category, matte: cryptomatte_pick.matte_file(frame, category, matte, root))
            kinds = {key: outputs.display_kind(frame['snapshot'], key) for key in files}
            # The compositor program where the runtime has it: the graph in one go, on the graphics card or the processor.
            self.steps, self.result = compositor.jobs(ran, files, kinds, root, composite=compositor.program(frame['runtime']))
            self.tool = str(Path(frame['runtime']) / 'oiiotool.exe')
            self.job = (frame, wanted)
            env = QtCore.QProcessEnvironment()
            for key, value in native.environment(frame['runtime']).items():
                env.insert(key, value)
            self.process.setProcessEnvironment(env)
            self.log = ''
            if not self.steps:
                # Nothing to run: the output is one of the frame's own buffers, as it is.
                self.finished(0, QtCore.QProcess.NormalExit)
            else:
                self.next()
        except Exception as exc:
            self.cleanup(); self.cache.notice.emit('Cannot make the composite: ' + str(exc))

    def again(self):
        """Ask once more for what was last asked for: the frame has changed, or the denoiser has finished."""
        if self.requested is not None:
            self.request(self.requested)

    def next(self):
        args, self.expected = self.steps.pop(0)
        # ['@run', program, ...]: a step for another program than the image tool (the compositor program).
        if args and args[0] == '@run':
            self.process.setProgram(args[1]); args = args[2:]
        else:
            self.process.setProgram(self.tool)
        self.process.setArguments(args); self.process.start()

    def read(self):
        self.log = (self.log + self.process.readAllStandardOutput().data().decode('utf-8', errors='replace'))[-2048:]

    def finished(self, code, status):
        if self.job is None:
            return
        if self.steps is not None and (code or status != QtCore.QProcess.NormalExit or (getattr(self, 'expected', None) is not None and not Path(self.expected).is_file())):
            self.cleanup(); self.cache.notice.emit('The composite could not be made; the other buffers are as they were. ' + self.log[-300:]); return
        if self.steps:
            self.next(); return
        frame, wanted = self.job
        if self.cache.frame is frame and not self.cache.closed:
            try:
                target = frame['folder'] / ('composite-' + wanted.split(':')[0][:16] + '.exr')
                shutil.copyfile(str(self.result), str(target))
                frame['files']['composite'] = target; frame['composite_signature'] = wanted
                self.cache.serial += 1; self.cache._request()
                self.cache.notice.emit('Composite ready')
            except OSError as exc:
                self.cache.notice.emit('Cannot keep the composite: ' + str(exc))
        asked = self.requested
        self.cleanup()
        if not self.cache.closed and asked is not None:
            # Another graph, or another frame, may have been asked for meanwhile.
            self.request(asked)

    def error(self, error):
        if error == QtCore.QProcess.FailedToStart:
            self.cleanup(); self.cache.notice.emit('Cannot start the compositor: ' + self.process.errorString())

    def cleanup(self):
        self.job = None; self.expected = None; self.steps = []
        if self.directory:
            try: self.directory.cleanup()
            except OSError: pass
            self.directory = None

    def close(self):
        self.requested = None
        self.job = None     # What a run cut short has to say is not listened to.
        if self.process.state() != QtCore.QProcess.NotRunning:
            self.process.kill(); self.process.waitForFinished(2000)
        self.cleanup()
