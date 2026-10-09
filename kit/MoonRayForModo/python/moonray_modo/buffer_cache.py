"""Retain completed linear preview buffers and convert views independently of rendering."""
import hashlib
import json
import shutil
import tempfile
import uuid
from pathlib import Path
from PySide2 import QtCore,QtGui
_retired_workers=set()

class _WorkerRetirement(QtCore.QObject):
    """Own worker and input files until the native thread has fully exited."""
    def __init__(self,worker,directory):
        super().__init__()
        self.worker=worker;self.directory=directory
        worker.setParent(None)
        self.timer=QtCore.QTimer(self);self.timer.setInterval(100)
        self.timer.timeout.connect(self.reap)
        _retired_workers.add(self);self.timer.start()

    @QtCore.Slot()
    def reap(self):
        if not self.worker.wait(0):return
        self.timer.stop();self.worker.deleteLater()
        try:self.directory.cleanup()
        except OSError:pass
        _retired_workers.discard(self);self.deleteLater()

from . import native, options, outputs
from .buffers import conversion


class BufferCache(QtCore.QObject):
    image_ready=QtCore.Signal(str)
    image_object=QtCore.Signal(object)
    selected=QtCore.Signal(str)
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
        self.frame=None;self.progressive=None;self.progressive_frames={};self.progressive_scene=None;self.job=None;self.displayed=None
        self.worker=None
        self.worker_poll=QtCore.QTimer(self);self.worker_poll.setSingleShot(True)
        self.worker_poll.setInterval(10);self.worker_poll.timeout.connect(self._memory_finished)
        from .cached_denoise import CachedDenoise
        self.denoiser=CachedDenoise(self)
        self.key='beauty';self.display={};self.serial=0;self.closed=False;self.log=''

    def select(self,key,display):
        if not isinstance(key,str) or not key or not all(c.isalnum() or c=='_' for c in key):raise ValueError('Unknown preview buffer')
        self.key=key;self.display=dict(display);self.serial+=1
        self.selected.emit(key)
        self._request()

    def busy(self):
        """True while a display conversion is running; publish_memory drops frames meanwhile."""
        return self.worker is not None or self.process.state()!=QtCore.QProcess.NotRunning

    def publish_memory(self,key,width,height,pixels,runtime,snapshot,backend):
        if self.closed or self.worker is not None or self.process.state()!=QtCore.QProcess.NotRunning:return
        if not 0<len(pixels)<=64*1024*1024 or len(pixels)!=width*height*12:raise ValueError('Invalid shared image size')
        folder=self.root/uuid.uuid4().hex;folder.mkdir()
        frame={'folder':folder,'files':{},'linear':{key:(width,height,pixels)},'runtime':Path(runtime),'snapshot':snapshot,'backend':backend,'partial':True}
        if self.progressive_scene is not snapshot:self.progressive_frames.clear()
        self.progressive_scene=snapshot;self.progressive=frame
        self.progressive_frames.pop(key,None);self.progressive_frames[key]=frame
        # Bound float AOV storage. Re-selecting an evicted AOV requests another snapshot.
        while sum(sum(len(v[2]) for v in f.get('linear',{}).values()) for f in self.progressive_frames.values())>128*1024*1024:
            self.progressive_frames.pop(next(iter(self.progressive_frames)))
        self.serial+=1;self._request();self._prune()

    def publish(self,files,runtime,snapshot,backend,partial=False):
        if partial and (self.worker is not None or (self.job and self.process.state()!=QtCore.QProcess.NotRunning)):return
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
        if partial:
            if self.progressive_scene is not snapshot:self.progressive_frames.clear()
            self.progressive_scene=snapshot;self.progressive=frame
            for key in copied:self.progressive_frames[key]=frame
        else:
            self.frame=frame;self.progressive=None;self.progressive_frames.clear();self.progressive_scene=None
        self.serial+=1;self._request();self._prune()

    def _request(self):
        if self.closed:return
        if self.worker is not None:return
        if self.process.state()!=QtCore.QProcess.NotRunning:
            # Only stop our display converter; never stop the renderer or denoiser.
            self.process.kill();return
        if self.frame is None and self.progressive is None:
            self.notice.emit('Buffers will be available after the first preview pass completes.');return
        self._start()

    def _start(self):
        frame=self.progressive_frames.get(self.key,self.frame)
        if frame is None or (self.key not in frame['files'] and self.key not in frame.get('linear',{})):
            self.notice.emit('Enable a Beauty denoiser and Denoise beauty preview to process the completed pass.' if self.key=='denoised_beauty' else 'Selected output will be available after a preview with these outputs completes.');return
        signature=hashlib.sha256(json.dumps([self.key,self.display,frame.get('denoise_engine') if self.key=='denoised_beauty' else None],sort_keys=True).encode('utf-8')).hexdigest()
        destination=frame['folder']/(signature+'.png')
        self.job=dict(frame=frame,key=self.key,serial=self.serial,destination=destination)
        if destination.is_file():self._show();self.job=None;self._prune();return
        try:
            display=dict(self.display,working_space=frame['snapshot'].get('asset_settings',{}).get('working_space','rec709'))
            if display['working_space']=='acescg' and display.get('view')=='ocio' and display.get('source')=='Linear Rec.709 (sRGB)':display['source']='ACEScg'
            kind=outputs.display_kind(frame['snapshot'],self.key)
            from .display_stream import available
            if kind=='cryptomatte' and not available(frame['runtime']):
                raise ValueError('Cryptomatte ID display requires the updated native display processor')
            if available(frame['runtime']):
                from .memory_display import Worker
                width,height,pixels=frame.get('linear',{}).get(self.key,(0,0,None))
                self.worker=Worker(pixels,width,height,kind,display,frame['runtime'],self,source=frame['files'].get(self.key) if pixels is None else None)
                self.worker.finished.connect(self._memory_finished);self.worker.start();return
            if self.key in frame.get('linear',{}):
                from .memory_display import supported,Worker
                width,height,pixels=frame['linear'][self.key]
                if not frame.get('memory_display_failed') and supported(kind,display,frame['runtime']):
                    self.worker=Worker(pixels,width,height,kind,display,frame['runtime'],self)
                    self.worker.finished.connect(self._memory_finished);self.worker.start();return
                if self.key not in frame['files']:
                    path=frame['folder']/(self.key+'.pfm')
                    with path.open('wb') as stream:stream.write(('PF\n%d %d\n-1.0\n'%(width,height)).encode('ascii'));stream.write(pixels)
                    frame['files'][self.key]=path
            args=conversion(kind,frame['files'][self.key],destination,display)
            env=QtCore.QProcessEnvironment()
            for key,value in native.environment(frame['runtime']).items():env.insert(key,value)
            self.process.setProcessEnvironment(env)
            self.process.setProgram(str(frame['runtime']/'oiiotool.exe'))
            self.process.setArguments(args);self.log='';self.process.start()
        except Exception as exc:
            self.job=None;self.notice.emit('Cannot display buffer: '+str(exc));self._prune()

    @QtCore.Slot()
    def _memory_finished(self):
        worker=self.worker
        if worker is None:return
        # finished may arrive while QThread is still unwinding native cleanup.
        # Keep its Python/Qt wrapper and buffers alive until wait confirms exit.
        if not worker.wait(0):
            self.worker_poll.start();return
        self.worker_poll.stop()
        self.worker=None;job=self.job;self.job=None
        data,width,height,error=getattr(worker,'outcome',(None,0,0,'Display worker produced no image'))
        worker.deleteLater()
        if self.closed:return
        if job and job['serial']==self.serial:
            if error:
                from .display_stream import available
                if available(job['frame']['runtime']):
                    self.notice.emit('Cannot display buffer; render continues: '+error)
                    self._prune();return
                job['frame']['memory_display_failed']=True
                self.notice.emit('Using file display fallback: '+error);self._request()
            else:
                self.displayed=dict(job['frame'],key=job['key'])
                image=QtGui.QImage(data,width,height,width*4,QtGui.QImage.Format_RGBA8888).copy()
                self.image_object.emit(image)
        else:self._request()
        self._prune()

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
        keep={entry['folder'] for entry in list(self.progressive_frames.values())+[self.frame,self.job['frame'] if self.job else None] if entry}
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
        if self.closed:return
        self.closed=True;self.worker_poll.stop();self.denoiser.close()
        retired=False
        if self.worker is not None:
            worker=self.worker;self.worker=None
            worker.finished.disconnect(self._memory_finished)
            if not worker.wait(2000):
                _WorkerRetirement(worker,self.directory);retired=True
            else:worker.deleteLater()
        if self.process.state()!=QtCore.QProcess.NotRunning:
            self.process.kill();self.process.waitForFinished(2000)
        if not retired and self.process.state()==QtCore.QProcess.NotRunning:self.directory.cleanup()
