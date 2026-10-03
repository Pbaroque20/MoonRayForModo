"""Retain completed linear preview buffers and convert views independently of rendering."""
import hashlib
import json
import shutil
import tempfile
import uuid
from pathlib import Path
from PySide2 import QtCore
from . import native, options, outputs
from .buffers import conversion


class BufferCache(QtCore.QObject):
    image_ready=QtCore.Signal(str)
    notice=QtCore.Signal(str)

    def __init__(self,parent=None):
        super().__init__(parent)
        self.directory=tempfile.TemporaryDirectory(prefix='MoonRayBuffers-')
        self.root=Path(self.directory.name)
        self.process=QtCore.QProcess(self)
        self.process.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)
        self.process.readyReadStandardOutput.connect(self._read)
        self.frame=None;self.progressive=None;self.job=None;self.displayed=None
        self.key='beauty';self.display={};self.serial=0;self.closed=False;self.log=''

    def select(self,key,display):
        if not isinstance(key,str) or not key or not all(c.isalnum() or c=='_' for c in key):raise ValueError('Unknown preview buffer')
        self.key=key;self.display=dict(display);self.serial+=1
        self._request()

    def publish(self,files,runtime,snapshot,backend,partial=False):
        if partial and self.job and self.process.state()!=QtCore.QProcess.NotRunning:return
        folder=self.root/uuid.uuid4().hex;folder.mkdir();copied={}
        try:
            for key,source in files.items():
                if not Path(source).is_file() or Path(source).stat().st_size<16:
                    raise ValueError('Missing rendered buffer: '+key)
                copied[key]=folder/(key+Path(source).suffix)
                shutil.copyfile(str(source),str(copied[key]))
        except Exception:
            shutil.rmtree(folder);raise
        frame={'folder':folder,'files':copied,'runtime':Path(runtime),'snapshot':snapshot,'backend':backend,'partial':partial}
        if partial:self.progressive=frame
        else:self.frame=frame;self.progressive=None
        self.serial+=1;self._request();self._prune()

    def _request(self):
        if self.closed:return
        if self.process.state()!=QtCore.QProcess.NotRunning:
            # Only stop our display converter; never stop the renderer or denoiser.
            self.process.kill();return
        if self.frame is None and self.progressive is None:
            self.notice.emit('Buffers will be available after the first preview pass completes.');return
        self._start()

    def _start(self):
        frame=self.progressive if self.key=='beauty' and self.progressive else self.frame
        if frame is None or self.key not in frame['files']:
            self.notice.emit('Selected output will be available after a preview with these outputs completes.');return
        signature=hashlib.sha256(json.dumps([self.key,self.display],sort_keys=True).encode('utf-8')).hexdigest()
        destination=frame['folder']/(signature+'.png')
        self.job=dict(frame=frame,key=self.key,serial=self.serial,destination=destination)
        if destination.is_file():self._show();self.job=None;self._prune();return
        try:
            args=conversion(outputs.display_kind(frame['snapshot'],self.key),frame['files'][self.key],destination,self.display)
            env=QtCore.QProcessEnvironment()
            for key,value in native.environment(frame['runtime']).items():env.insert(key,value)
            self.process.setProcessEnvironment(env)
            self.process.setProgram(str(frame['runtime']/'oiiotool.exe'))
            self.process.setArguments(args);self.log='';self.process.start()
        except Exception as exc:
            self.job=None;self.notice.emit('Cannot display buffer: '+str(exc));self._prune()

    def _read(self):
        self.log=(self.log+bytes(self.process.readAllStandardOutput()).decode('utf-8',errors='replace'))[-4096:]

    def _show(self):
        self.displayed=dict(self.job['frame'],key=self.job['key'])
        self.image_ready.emit(str(self.job['destination']))

    def _finished(self,code,status):
        self._read()
        if self.closed:return
        job=self.job;self.job=None
        if not job:return
        if job['serial']!=self.serial:
            self._discard(job['destination'])
            self._request();self._prune();return
        if code==0 and status==QtCore.QProcess.NormalExit and job['destination'].is_file():
            self.job=job;self._show();self.job=None
        else:
            self._discard(job['destination'])
            self.notice.emit('Cannot display buffer; render continues. '+self.log[-500:])
        self._prune()

    @staticmethod
    def _discard(path):
        try:path.unlink()
        except OSError:pass

    def _error(self,error):
        if error==QtCore.QProcess.FailedToStart and not self.closed:
            self.job=None;self.notice.emit('Cannot start buffer display converter: '+self.process.errorString());self._prune()

    def _prune(self):
        keep={entry['folder'] for entry in (self.frame,self.progressive,self.job['frame'] if self.job else None) if entry}
        for folder in self.root.iterdir():
            if folder.is_dir() and folder not in keep:
                try:shutil.rmtree(folder)
                except OSError:pass
        # Bound converted views too; retain the current displayed image and in-flight file.
        if self.frame:
            keep_png={self.job['destination']} if self.job else set()
            pngs=sorted(self.frame['folder'].glob('*.png'),key=lambda path:path.stat().st_mtime,reverse=True)
            for path in pngs[24:]:
                if path not in keep_png:
                    try:path.unlink()
                    except OSError:pass

    def close(self):
        self.closed=True
        if self.process.state()!=QtCore.QProcess.NotRunning:
            self.process.kill();self.process.waitForFinished(2000)
        if self.process.state()==QtCore.QProcess.NotRunning:self.directory.cleanup()
