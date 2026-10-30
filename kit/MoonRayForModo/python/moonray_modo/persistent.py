"""A private persistent MoonRay process, with acknowledged/coalesced scene edits."""
import json
import hashlib
import mmap,os,uuid
import tempfile
from pathlib import Path
from PySide2 import QtCore
from . import terminal
from . import native
from .scene_delta import difference


def supported(runtime):
    try:
        metadata=json.loads((Path(runtime)/'modo-session.json').read_text(encoding='utf-8'))
        return metadata.get('protocol')==1 and metadata.get('executable_sha256')==hashlib.sha256((Path(runtime)/'moonray.exe').read_bytes()).hexdigest()
    except (OSError,ValueError,TypeError):return False


# The most MoonRay takes of a scene through shared memory: the loaded renderer refuses more.
SHARED_LIMIT=256*1024*1024
class _Rediff(QtCore.QThread):
    """A delta made again off Modo's thread (_dispatch): a request's text against the scene the session has applied,
    where the writer made it against an earlier one and the text is too large to compare on Modo's thread. delta: the
    difference, or None where there is none to make (the structure changed: a reload), and why there is none.
    report: made only for why (the Render Log's line when the whole scene goes)."""
    def __init__(self,applied,request,parent=None,report=False):
        super().__init__(parent)
        self.applied,self.request,self.delta,self.why,self.report=applied,request,None,[],report
    def run(self):
        heavy=(self.request.get('prepared') or {}).get('heavy')
        try:self.delta=difference(self.applied['text'],self.request['text'],heavy,why=self.why)
        except Exception as error:self.delta=None;self.why.append(str(error) or type(error).__name__)


# The most scene text a delta is made from on Modo's own thread (_dispatch), where the one the writer made is against
# a scene since replaced: a few thousandths of a second where the meshes are in the binary file.
DIFF_HERE=4*1024*1024
# For trying the other way with a small scene: MOONRAY_MODO_SHARED_LIMIT, in bytes, lowers it.
try:SHARED_LIMIT=max(0,min(SHARED_LIMIT,int(os.environ.get('MOONRAY_MODO_SHARED_LIMIT',SHARED_LIMIT))))
except ValueError:pass

def saves(runtime):
    """Whether this runtime's MoonRay, kept loaded, can save its picture as it renders and take a render up from a
    save: what Safe Denoising and Continue need, with the picture still shown as it comes on."""
    try:return bool(json.loads((Path(runtime)/'modo-session.json').read_text(encoding='utf-8')).get('saves'))
    except (OSError,ValueError,TypeError,AttributeError):return False


def important(runtime):
    """Whether this runtime's MoonRay can take the tiles with the most in them first."""
    try:return bool(json.loads((Path(runtime)/'modo-session.json').read_text(encoding='utf-8')).get('important'))
    except (OSError,ValueError):return False


def drains(runtime):
    """Whether this runtime's MoonRay can be asked to finish with what it has in hand: the tiles its workers are on
    rendered to the end and the frame ended there as a finished one."""
    try:return bool(json.loads((Path(runtime)/'modo-session.json').read_text(encoding='utf-8')).get('drains'))
    except (OSError,ValueError):return False

def holds(runtime):
    """Whether this runtime's MoonRay, kept loaded, can hand over several views of a render at one asking: what
    lets a stop keep its picture without asking for each view in turn."""
    try:return bool(json.loads((Path(runtime)/'modo-session.json').read_text(encoding='utf-8')).get('holds'))
    except (OSError,ValueError,TypeError,AttributeError):return False


class Session(QtCore.QObject):
    output=QtCore.Signal(str)
    ready=QtCore.Signal(int)
    image=QtCore.Signal(int,str,str)
    memory_image=QtCore.Signal(object)
    acknowledged=QtCore.Signal(int)
    failed=QtCore.Signal(str)
    status=QtCore.Signal(str)

    def __init__(self,parent=None):
        super().__init__(parent)
        self.process=QtCore.QProcess(self)
        self.process.started.connect(lambda:native.lower_priority(self.process.processId()))
        # Named in the MoonRay Terminal by the mode it starts in (native.engine_name), as each start may be another.
        terminal.watch(self.process,self.engine_name,resident=True)
        self.process.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.finished.connect(self._exit)
        self.process.errorOccurred.connect(self._error)
        self.workspace=tempfile.TemporaryDirectory(prefix='MoonRaySession-')
        self.root=Path(self.workspace.name)
        self.latest=None;self.sent=None;self.applied=None;self.signature=None
        self.scene_memory=False;self.mappings={};self.command_channel=None
        self.partial='';self.stopping=False;self.closed=False;self.view='beauty'
        from .idle_release import IdleRelease
        self.idle=IdleRelease(self,self._release_idle,lambda:self.running() and not self.stopping and self.sent is None)

    def engine_name(self):
        """What the Terminal calls this MoonRay: MoonRay XPU2 where XPU2 renders, else by the execution mode it starts in."""
        if getattr(self,'xpu2_active',False):return 'MoonRay XPU2'
        return native.engine_name((self.sent or self.latest or {}).get('mode'))

    def select_view(self,key):
        if not key or not key.isascii() or len(key)>64 or not all(c.isalnum() or c=='_' for c in key):return
        self.view=key
        # XPU2's realtime denoises its pictures where Denoised Beauty is chosen; MoonRay kept loaded hands over its beauty.
        if key=='denoised_beauty' and not getattr(self,'xpu2_active',False):key='beauty'
        staged=self.root/'view.tmp';staged.write_text(key,encoding='ascii');staged.replace(self.root/'view.txt')

    def drain(self):
        """Have the render now going finish with what it has in hand and end as a finished one."""
        if not self.latest or not self.running():return False
        staged=self.root/'drain.tmp';staged.write_text(str(self.latest['id']),encoding='ascii');staged.replace(self.root/'drain.txt')
        return True

    def hold(self,keys):
        """Have these views of the render now going handed over, one after another, in the order given."""
        if not self.latest:return False
        staged=self.root/'hold.tmp';staged.write_text('%d %s'%(self.latest['id'],' '.join(keys)),encoding='ascii');staged.replace(self.root/'hold.txt')
        return True

    def running(self):return self.process.state()!=QtCore.QProcess.NotRunning

    def submit(self,text,runtime,threads,mode,generation,bucket_size=0,prepared=None,important=False):
        self.idle.cancel()
        # Whether the render takes the tiles with the most in them first: read by MoonRay as each render begins.
        try:
            staged=self.root/'important.tmp';staged.write_text('1' if important else '0',encoding='ascii');staged.replace(self.root/'important.txt')
        except (OSError,AttributeError):pass
        request=dict(text=text,runtime=Path(runtime),threads=threads,mode=mode,id=generation,bucket_size=bucket_size,prepared=prepared)
        # A change of the toon preference is read by MoonRay only as it starts: it starts again.
        signature=(str(runtime),threads,mode,bucket_size)+native.source_switches()
        self.latest=request
        if self.running() and signature!=self.signature:
            # A preference changed (XPU2's among them): XPU2 may try again.
            self.xpu2_refused=None
            self.stopping=True;self.process.kill();return
        if self.stopping:return
        if not self.running():self._launch()
        elif self.sent is None:self._dispatch()

    def _write_scene(self,request,suffix,text,payload=None):
        if self.scene_memory:
            if payload is None:payload=text.encode('utf-8')
            if not payload:raise ValueError('The scene to hand to MoonRay is empty')
        if self.scene_memory and len(payload)<=SHARED_LIMIT:
            name='Local\\MoonRayForModoScene_%d_%s'%(os.getpid(),uuid.uuid4().hex)
            mapping=mmap.mmap(-1,len(payload),tagname=name,access=mmap.ACCESS_WRITE)
            mapping.write(payload)
            self.mappings.setdefault(request['id'],[]).append(mapping)
            return 'modo-memory:%d:%s'%(len(payload),name)
        # A scene too large to hand over in memory (MoonRay takes at most SHARED_LIMIT that way) is handed over as a
        # file, as every scene is where the runtime has no shared memory: slower, and no scene is refused for its size.
        path=self.root/('%d.%s.rdla'%(request['id'],suffix))
        if payload is None:path.write_text(text,encoding='utf-8')
        else:path.write_bytes(payload)
        if self.scene_memory:return path.as_posix()
        return path

    def _write_binary(self,request,payload,memory):
        """The geometry's binary scene (rdlb.py): in shared memory where XPU2 is to read it (modo-memory-rdlb), else a
        file beside the text."""
        if memory and payload:
            name='Local\\MoonRayForModoScene_%d_%s'%(os.getpid(),uuid.uuid4().hex)
            mapping=mmap.mmap(-1,len(payload),tagname=name,access=mmap.ACCESS_WRITE)
            mapping.write(payload)
            self.mappings.setdefault(request['id'],[]).append(mapping)
            return 'modo-memory-rdlb:%d:%s'%(len(payload),name)
        binary=self.root/('%d.full.rdlb'%request['id']);binary.write_bytes(payload)
        return binary

    def _release_mappings(self):
        for mappings in self.mappings.values():
            for mapping in mappings:mapping.close()
        self.mappings.clear()
        if self.command_channel:self.command_channel.close();self.command_channel=None

    def _launch(self):
        request=self.latest
        if not request or self.closed:return
        self._release_mappings()
        for path in self.root.iterdir():
            if path.is_file():path.unlink()
        self.select_view(self.view)
        self.partial='';self.applied=None;self.sent=request
        self.signature=(str(request['runtime']),request['threads'],request['mode'],request['bucket_size'])+native.source_switches()
        metadata=json.loads((request['runtime']/'modo-session.json').read_text(encoding='utf-8'))
        self.scene_memory=metadata.get('scene_memory',False)
        prepared=request.get('prepared') or {}
        split=prepared.get('split') or ((prepared['full_bytes'],prepared['binary']) if prepared.get('binary') else None)
        if split:
            # Its first scene with the geometry as binary (rdlb.py): the text, then the binary file it sets.
            scene=self._write_scene(request,'full',None,split[0])
            # Whether XPU2 takes it (as below), which reads the binary scene from shared memory.
            xpu2=bool(native.xpu2() and request['mode'] in ('xpu','auto') and not getattr(self,'xpu2_refused',None))
            binary=self._write_binary(request,split[1],xpu2)
        else:
            scene=self._write_scene(request,'full',request['text'],(request.get('prepared') or {}).get('full_bytes'));binary=None
        env=QtCore.QProcessEnvironment()
        for key,value in native.environment(request['runtime']).items():env.insert(key,value)
        env.insert('MOONRAY_MODO_BUCKETS','1')
        env.insert('MOONRAY_MODO_BUCKET_SIZE',str(request['bucket_size']))
        env.insert('MOONRAY_MODO_SHARED','1')
        if metadata.get('command_memory'):
            from .session_channel import Channel
            self.command_channel=Channel()
            env.insert('MOONRAY_MODO_COMMAND',self.command_channel.name)
        env.insert('MOONRAY_MODO_SESSION',str(self.root))
        # So that the renderer ends itself should this process end without telling it to.
        env.insert('MOONRAY_MODO_HOST',str(os.getpid()))
        env.insert('MOONRAY_MODO_GENERATION',str(request['id']))
        # XPU2 renders in MoonRay's place where it is chosen, the render's execution mode is
        # XPU or Auto, and XPU2 has not left this scene to MoonRay (@@MODO_XPU2 FALLBACK).
        program=request['runtime']/'moonray.exe'
        self.xpu2_active=bool(native.xpu2() and request['mode'] in ('xpu','auto') and not getattr(self,'xpu2_refused',None))
        if self.xpu2_active and native.xpu2_devices()!='cpu' and not native.xpu2_shaders_compiled():
            # XPU2 chosen, its shaders not compiled: nothing is rendered (MoonRay XPU in its place hid that it was not XPU2),
            # and the preview says where to compile them.
            self.sent=None;self.failed.emit(native.XPU2_NOT_COMPILED);return
        # The view again, now that it is known whose: Denoised Beauty is XPU2's own (realtime), the beauty MoonRay's.
        self.select_view(self.view)
        if self.xpu2_active:
            program=native.xpu2_runtime()/'moonray_xpu2.exe'
            for key,value in native.xpu2_environment(request['runtime']).items():env.insert(key,value)
        self.process.setProcessEnvironment(env);self.process.setWorkingDirectory(str(self.root))
        self.process.setProgram(str(program))
        args=native.arguments(self.root/'bootstrap.rdla',self.root/'main.exr',request['threads'],request['mode'])
        args[args.index('-in')+1]=str(scene)
        if binary:args[2:2]=['-in',str(binary)]
        self.process.setArguments(args)
        self.status.emit('Starting persistent MoonRay session')
        self.process.start()

    def _dispatch(self):
        request=self.latest
        if not request or (self.applied and request['id']==self.applied['id']):return
        prepared=request.get('prepared')
        delta_bytes=(prepared or {}).get('delta_bytes')
        if prepared is not None and prepared['base'] is self.applied:delta=prepared['delta']
        else:
            # APPLIED may advance while the writer runs, as it does through a drag of the camera: a delta made against
            # another scene is unsafe. It is made again against the one applied: here where the scene's text is small
            # (its meshes in the binary file), else on a thread of its own (_Rediff), the request sent once it is made
            # (a fast drag of the camera on a car reloaded the whole scene every few turns, its text too large to
            # compare here). Where no delta can be made (the structure changed), the full scene goes (a reload).
            small=self.applied and len(request['text'])<=DIFF_HERE and len(self.applied['text'])<=DIFF_HERE
            if self.applied and not small:
                rediff=getattr(self,'_rediff',None)
                if rediff is not None and rediff.isRunning():return  # its end dispatches the latest request
                if rediff is None or rediff.request is not request or rediff.applied is not self.applied:
                    rediff=self._rediff=_Rediff(self.applied,request,self)
                    rediff.finished.connect(lambda:None if self.closed else self._dispatch())
                    rediff.start()
                    return
                delta=rediff.delta
            else:delta=difference(self.applied['text'],request['text'],(prepared or {}).get('heavy')) if small else None
            delta_bytes=None
        if delta is None and self.applied:
            # The whole scene goes: why, in the Render Log, found on a thread of its own (a drag of the camera should
            # only ever update the scene; one that reloads says what changed besides).
            told=_Rediff(self.applied,request,self,report=True)
            told.finished.connect(lambda told=told:None if self.closed else self.output.emit(
                'MoonRay session: the whole scene is loaded again: %s\n'%(told.why[0] if told.why else 'its text is the one loaded')))
            self._told=told;told.start()
        full=self._write_scene(request,'full',request['text'],(prepared or {}).get('full_bytes'))
        if (prepared or {}).get('binary'):
            # Its geometry's binary file, read after the text when MoonRay reloads (rdlb.py).
            binary=self._write_binary(request,prepared['binary'],getattr(self,'xpu2_active',False))
            full='%s|%s'%(full,binary)
        path=self._write_scene(request,'delta',delta,delta_bytes) if delta is not None else full
        mode='delta' if delta is not None else 'full'
        staged=self.root/'command.tmp'
        command='%d\n%s\n%s\n%s\n'%(request['id'],mode,str(path).replace('\\','/') if not self.scene_memory else str(path),str(full).replace('\\','/') if not self.scene_memory else str(full))
        if self.command_channel:self.command_channel.send(command)
        else:
            staged.write_text(command,encoding='utf-8');staged.replace(self.root/'command.txt')
        self.sent=request
        self.status.emit('Updating loaded scene' if mode=='delta' else 'Reloading scene structure in persistent session')

    def _read(self):
        text=self.process.readAllStandardOutput().data().decode('utf-8',errors='replace')
        self.output.emit(text)
        self.partial+=text
        while '\n' in self.partial:
            line,self.partial=self.partial.split('\n',1)
            if line.startswith('@@MODO_SHARED '):
                try:
                    from .shared_image import receive
                    packet=receive(line,self.process.processId())
                    if not self.stopping and not self.closed and self.latest and packet[0]==self.latest['id']:self.memory_image.emit(packet)
                except (ValueError,OSError) as exc:
                    # A frame already taken back (shared_image.Withdrawn) is passed over without a word: newer ones follow.
                    from .shared_image import Withdrawn
                    if not isinstance(exc,Withdrawn):self.status.emit('Progressive image skipped: '+str(exc))
                continue
            if line.startswith('@@MODO_XPU2 FALLBACK'):
                # XPU2 does not render this scene: MoonRay is started in its place with the scene, as after a restart.
                self.xpu2_refused=line[len('@@MODO_XPU2 FALLBACK'):].strip() or 'it does not render this scene'
                self.status.emit('MoonRay XPU2: %s. MoonRay XPU renders this preview instead.'%self.xpu2_refused)
                if not self.closed:self.stopping=True
                continue
            if not line.startswith('@@MODO_SESSION '):continue
            parts=line.strip().split()
            if len(parts)!=3:continue
            try:generation=int(parts[2])
            except ValueError:continue
            if self.stopping or self.closed:continue
            if parts[1]=='APPLIED' and self.sent and generation==self.sent['id']:
                self.applied=self.sent;self.sent=None
                self.applied.pop('prepared',None)
                for identity in list(self.mappings):
                    if identity<=generation:
                        for mapping in self.mappings.pop(identity):mapping.close()
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
                    if self.latest and generation==self.latest['id'] and path.is_file():
                        # Too large to hand over in memory, the picture comes as a file with its rows top first.
                        from .pfm import upright
                        upright(path)
                        self.image.emit(generation,key,str(path))
                except (OSError,ValueError) as exc:self.status.emit('Progressive image skipped: '+str(exc))
                finally:
                    try:path.unlink()
                    except OSError:pass
            elif parts[1]=='DONE' and self.latest and generation==self.latest['id']:
                self.idle.arm()
                self.ready.emit(generation)
        self.partial=self.partial[-65536:]

    def _error(self,error):
        if error==QtCore.QProcess.FailedToStart and not self.stopping and not self.closed:
            self._release_mappings()
            self.failed.emit('Cannot start persistent MoonRay: '+self.process.errorString())

    def _exit(self,code,status):
        self.idle.cancel()
        self._read()
        if getattr(self,'xpu2_active',False) and not self.stopping and not self.closed:
            # XPU2 ended without saying why: MoonRay takes the preview over.
            self.xpu2_refused='ended unexpectedly (0x%08X; see Render Log)'%(code&0xffffffff)
            self.status.emit('MoonRay XPU2 %s. MoonRay XPU renders this preview instead.'%self.xpu2_refused)
            self.stopping=True
        self.sent=None;self.applied=None
        self._release_mappings()
        if self.stopping:
            self.stopping=False
            if self.latest and not self.closed:self._launch()
        elif not self.closed:
            self.failed.emit('Persistent MoonRay exited (0x%08X). Refresh to start a new session; see Render Log.'%(code & 0xffffffff))

    def _release_idle(self):
        self.stop()
        self.status.emit("Idle MoonRay released its memory. Cached images are kept; the next render reloads the scene.")

    def stop(self):
        self.idle.cancel()
        self.xpu2_refused=None
        self.latest=None;self.sent=None;self.applied=None
        if self.running():self.stopping=True;self.process.kill()

    def close(self):
        self.closed=True;self.stop()
        if self.running():self.process.waitForFinished(2000)
        if not self.running():self._release_mappings();self.workspace.cleanup()
