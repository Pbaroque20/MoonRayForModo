"""A private persistent MoonRay process, with acknowledged/coalesced scene edits."""
import json
import hashlib
import tempfile
from pathlib import Path
from PySide2 import QtCore
from . import native
from .scene_delta import difference


def supported(runtime):
    try:
        metadata=json.loads((Path(runtime)/'modo-session.json').read_text(encoding='utf-8'))
        return metadata.get('protocol')==1 and metadata.get('executable_sha256')==hashlib.sha256((Path(runtime)/'moonray.exe').read_bytes()).hexdigest()
    except (OSError,ValueError,TypeError):return False


class Session(QtCore.QObject):
    output=QtCore.Signal(str)
    ready=QtCore.Signal(int)
    image=QtCore.Signal(int,str,str)
    acknowledged=QtCore.Signal(int)
    failed=QtCore.Signal(str)
    status=QtCore.Signal(str)

    def __init__(self,parent=None):
        super().__init__(parent)
        self.process=QtCore.QProcess(self)
        self.process.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.finished.connect(self._exit)
        self.process.errorOccurred.connect(self._error)
        self.workspace=tempfile.TemporaryDirectory(prefix='MoonRaySession-')
        self.root=Path(self.workspace.name)
        self.latest=None;self.sent=None;self.applied=None;self.signature=None
        self.partial='';self.stopping=False;self.closed=False;self.view='beauty'

    def select_view(self,key):
        if not key or not key.isascii() or len(key)>64 or not all(c.isalnum() or c=='_' for c in key):return
        self.view=key
        staged=self.root/'view.tmp';staged.write_text(key,encoding='ascii');staged.replace(self.root/'view.txt')

    def running(self):return self.process.state()!=QtCore.QProcess.NotRunning

    def submit(self,text,runtime,threads,mode,generation):
        request=dict(text=text,runtime=Path(runtime),threads=threads,mode=mode,id=generation)
        signature=(str(runtime),threads,mode)
        self.latest=request
        if self.running() and signature!=self.signature:
            self.stopping=True;self.process.kill();return
        if self.stopping:return
        if not self.running():self._launch()
        elif self.sent is None:self._dispatch()

    def _write_scene(self,request,suffix,text):
        path=self.root/('%d.%s.rdla'%(request['id'],suffix))
        path.write_text(text,encoding='utf-8')
        return path

    def _launch(self):
        request=self.latest
        if not request or self.closed:return
        for path in self.root.iterdir():
            if path.is_file():path.unlink()
        self.select_view(self.view)
        self.partial='';self.applied=None;self.sent=request
        self.signature=(str(request['runtime']),request['threads'],request['mode'])
        scene=self._write_scene(request,'full',request['text'])
        env=QtCore.QProcessEnvironment()
        for key,value in native.environment(request['runtime']).items():env.insert(key,value)
        env.insert('MOONRAY_MODO_SESSION',str(self.root))
        env.insert('MOONRAY_MODO_GENERATION',str(request['id']))
        self.process.setProcessEnvironment(env);self.process.setWorkingDirectory(str(self.root))
        self.process.setProgram(str(request['runtime']/'moonray.exe'))
        self.process.setArguments(native.arguments(scene,self.root/'main.exr',request['threads'],request['mode']))
        self.status.emit('Starting persistent MoonRay session')
        self.process.start()

    def _dispatch(self):
        request=self.latest
        if not request or (self.applied and request['id']==self.applied['id']):return
        delta=difference(self.applied['text'],request['text']) if self.applied else None
        full=self._write_scene(request,'full',request['text'])
        path=self._write_scene(request,'delta',delta) if delta is not None else full
        mode='delta' if delta is not None else 'full'
        staged=self.root/'command.tmp'
        staged.write_text('%d\n%s\n%s\n%s\n'%(request['id'],mode,path.as_posix(),full.as_posix()),encoding='utf-8')
        staged.replace(self.root/'command.txt')
        self.sent=request
        self.status.emit('Updating loaded scene' if mode=='delta' else 'Reloading scene structure in persistent session')

    def _read(self):
        text=bytes(self.process.readAllStandardOutput()).decode('utf-8',errors='replace')
        self.output.emit(text)
        self.partial+=text
        while '\n' in self.partial:
            line,self.partial=self.partial.split('\n',1)
            if not line.startswith('@@MODO_SESSION '):continue
            parts=line.strip().split()
            if len(parts)!=3:continue
            try:generation=int(parts[2])
            except ValueError:continue
            if self.stopping or self.closed:continue
            if parts[1]=='APPLIED' and self.sent and generation==self.sent['id']:
                self.applied=self.sent;self.sent=None
                self.acknowledged.emit(generation)
                try:self._dispatch()
                except (OSError,ValueError) as exc:
                    self.failed.emit('Cannot send scene update: '+str(exc));return
                # Keep current/queued source files only; the native loader has closed older ones.
                keep={str(v['id']) for v in (self.applied,self.sent,self.latest) if v}
                for path in self.root.glob('*.rdla'):
                    if path.name.split('.')[0] not in keep:
                        try:path.unlink()
                        except OSError:pass
            elif parts[1]=='FRAME' or parts[1].startswith('FRAME_'):
                key=parts[1][6:] if parts[1].startswith('FRAME_') else 'beauty'
                if not key or not all(c.isalnum() or c=='_' for c in key):continue
                path=self.root/('preview_%d_%s.pfm'%(generation,key) if parts[1]!='FRAME' else 'preview_%d.pfm'%generation)
                try:
                    if self.latest and generation==self.latest['id'] and path.is_file():self.image.emit(generation,key,str(path))
                finally:
                    try:path.unlink()
                    except OSError:pass
            elif parts[1]=='DONE' and self.latest and generation==self.latest['id']:
                self.ready.emit(generation)
        self.partial=self.partial[-65536:]

    def _error(self,error):
        if error==QtCore.QProcess.FailedToStart and not self.stopping and not self.closed:
            self.failed.emit('Cannot start persistent MoonRay: '+self.process.errorString())

    def _exit(self,code,status):
        self._read()
        self.sent=None;self.applied=None
        if self.stopping:
            self.stopping=False
            if self.latest and not self.closed:self._launch()
        elif not self.closed:
            self.failed.emit('Persistent MoonRay exited (0x%08X). Refresh to start a new session; see Render Log.'%(code & 0xffffffff))

    def stop(self):
        self.latest=None;self.sent=None;self.applied=None
        if self.running():self.stopping=True;self.process.kill()

    def close(self):
        self.closed=True;self.stop()
        if self.running():self.process.waitForFinished(2000)
        if not self.running():self.workspace.cleanup()
