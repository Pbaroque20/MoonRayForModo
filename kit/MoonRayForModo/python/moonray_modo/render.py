"""Asynchronous native renderer lifecycle; no Modo API calls here."""
from pathlib import Path
import shutil
import tempfile
import time
import uuid
from PySide2 import QtCore
from . import native, rdla, options, denoising, outputs
from .progress import Progress, duration
from .buffer_cache import BufferCache
from .persistent import Session, supported as persistent_supported, saves as persistent_saves
from .moonlightipr_session import Session as MoonLightIPRSession, supported as moonlightipr_supported, directory as moonlightipr_directory

MOONLIGHTIPR_STATUS = 'MoonLightIPR (GPU preview, approximate)'
MOONLIGHTIPR_SAMPLES = 256


def scalar_only(snapshot):
    """What in a scene this build of MoonRay draws rightly only in its scalar mode, in words, or None. A VDB volume
    that gives off light stops its vector and GPU modes; a cookie filter leaves pixels that are not numbers in them."""
    if any(entry.get('kind')=='vdb' and entry.get('emission_grid') and float(entry.get('emission',1))>0 for entry in snapshot.get('extra_geometry',[])):
        return 'A VDB volume with an emission grid'
    lights=(snapshot.get('production') or {}).get('lights',{})
    if any(isinstance(held,dict) and held.get('cookie_file') for held in lights.values())             or any(str(entity.get('class','')).startswith('CookieLightFilter') for entity in snapshot.get('entities',[])):
        return 'A light with a cookie filter'
    return None


def deep_beside(path):
    """Where the deep EXR of a render goes: beside it, under its name."""
    path=Path(path);return path.with_name(path.stem+'.deep.exr')


class SceneWriter(QtCore.QThread):
    """A snapshot written as MoonRay's scene text away from Modo's own thread, for a scene that is being followed.
    The snapshot is plain data and writing it asks Modo nothing, so Modo is free to move its view meanwhile."""

    def __init__(self, arguments, path, context, generation, parent=None, applied=None):
        super().__init__(parent)
        self.arguments, self.path, self.context, self.generation = arguments, path, context, generation
        self.outcome = None
        self.applied, self.prepared = applied, None
        # Set when something newer was asked for before this was written.
        self.abandoned = False

    def run(self):
        try:
            text = rdla.scene_text(*self.arguments)
            from .scene_delta import difference
            delta = difference(self.applied['text'], text) if self.applied else None
            self.prepared = dict(base=self.applied, delta=delta, full_bytes=text.encode('utf-8'),
                                 delta_bytes=delta.encode('utf-8') if delta is not None else None)
            self.path.write_bytes(self.prepared['full_bytes'])
            self.outcome = (text, '')
        except Exception as exc:
            self.outcome = (None, str(exc) or type(exc).__name__)


class Renderer(QtCore.QObject):
    notices = QtCore.Signal(object)
    buckets = QtCore.Signal(object)
    workers = QtCore.Signal(object)
    image_ready = QtCore.Signal(str)
    image_object = QtCore.Signal(object)
    status = QtCore.Signal(str)
    failed = QtCore.Signal(str)
    finished = QtCore.Signal(str)
    # A render stopped by hand that had nothing saved to finish with.
    stopped = QtCore.Signal()
    kept = QtCore.Signal(bool)
    # Smart Render: the picture has become clean enough for the denoiser. With how noisy it read.
    settled_clean = QtCore.Signal(float)
    progress = QtCore.Signal(int,str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.buffers=BufferCache(self)
        self.buffers.image_ready.connect(self.image_ready.emit)
        self.buffers.image_object.connect(self.image_object.emit)
        self.buffers.notice.connect(self.status.emit)
        self.session=Session(self)
        # Set once MoonRay's GPU mode has run out of room on a scene: renders then go to the CPU, where it has not
        # been seen to, until the user chooses an execution mode again.
        self.cpu_fallback=False;self.pool_warnings=0;self.fallback_mode=None
        self.buffers.selected.connect(self._select_view)
        self.session.output.connect(self._consume_log)
        self.session.ready.connect(self._persistent_ready)
        self.session.image.connect(self._persistent_image)
        self.session.memory_image.connect(self._persistent_memory)
        self.session.acknowledged.connect(self._persistent_applied)
        self.session_files={}
        # Modo ending while a scene is being written: the thread is let finish, not cut off under it.
        application=QtCore.QCoreApplication.instance()
        if application is not None:application.aboutToQuit.connect(self._quitting)
        self.session.failed.connect(self.failed.emit)
        self.session.status.connect(self.status.emit)
        self.session_serial=0;self.gather=None
        self.using_session=False
        # Approximate GPU preview; final frames never use it.
        self.moonlightipr=MoonLightIPRSession(self)
        self.moonlightipr.output.connect(self._consume_log)
        self.moonlightipr.ready.connect(self._moonlightipr_ready)
        self.moonlightipr.memory_image.connect(self._moonlightipr_memory)
        self.moonlightipr.warnings.connect(self.notices.emit)
        self.moonlightipr.failed.connect(self.failed.emit)
        self.moonlightipr.status.connect(self.status.emit)
        self.moonlightipr_serial=0
        self.using_moonlightipr=False
        self.moonlightipr_frame=None
        for signal in (self.buffers.image_ready,self.buffers.image_object,self.buffers.notice):
            signal.connect(self._moonlightipr_flush)
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
        self.bucket_partial = ''
        self.backend_status = 'CPU'
        self.backend_log = ''
        self.phase = 'render'
        self.generation = 0
        self.timeout_seconds = 0
        self.watchdog = QtCore.QTimer(self)
        self.watchdog.setSingleShot(True)
        self.watchdog.timeout.connect(self._timed_out)
        self.process.started.connect(self._started)
        self.progress_state=None
        self.progress_timer=QtCore.QTimer(self)
        self.progress_timer.setInterval(500)
        self.progress_timer.timeout.connect(self._progress_tick)
        self.finished.connect(lambda output:self._progress_end(True))
        self.failed.connect(lambda message:self._progress_end(False))

    def _progress_tick(self):
        if self.progress_state:
            value,label=self.progress_state.display(self.phase)
            self.progress.emit(value,label)

    def _progress_end(self,success):
        self.buckets.emit(None)
        self.progress_timer.stop()
        if self.progress_state:
            elapsed=self.progress_state.clock()-self.progress_state.started
            self.progress.emit(100 if success else 0,('Complete' if success else 'Stopped')+' · Elapsed '+duration(elapsed))

    def _started(self):
        self.watchdog.stop()
        if self.timeout_seconds>0:
            self.watchdog.start(min(2147483647,int(self.timeout_seconds*1000)))

    def _timed_out(self):
        if self.closed or self.canceled:
            return
        self.stop()
        self.failed.emit('Render exceeded the configured time limit; it was stopped. Completed outputs were preserved.')

    def submit(self, snapshot, runtime, width, height, samples, environment, threads, output=None, linear_preview=False, persistent_preview=True, engine='moonray', resume=False):
        # resume: take up the preview that was last stopped under Safe Denoising where it stood, in place of starting
        # anew. It is the caller's to know that the scene is the same one.
        if not output and not (resume and getattr(self,'resumable',None)):
            self.resumable=None;resume=False
        if self.closed:
            raise ValueError('Renderer is closed')
        if engine not in ('moonray','moonlightipr'):
            raise ValueError('Unknown preview engine')
        runtime = native.find_runtime(runtime)
        moonlightipr = engine=='moonlightipr' and not output and not linear_preview
        # MoonLightIPR denoises when its denoised beauty is the buffer chosen in the window, with its own denoiser.
        # (The window says so before it hands the scene over: a scene read earlier and used again says what was
        # chosen when it was read.)
        # MoonLightIPR produces beauty only.
        if moonlightipr:snapshot=dict(snapshot,preview_buffer='beauty')
        if not output and not linear_preview:
            chosen,shown=snapshot.get('preview_buffer','beauty'),snapshot.get('display',{})
            # A draft redrawn with the same buffer shown the same way has nothing to choose: choosing converts the
            # picture already up once more, and the new one then waits behind that.
            if not (snapshot.get('_draft') and chosen==self.buffers.key and dict(shown)==self.buffers.display):
                self.buffers.select(chosen,shown)
        self.buckets.emit(None)
        self.bucket_partial = ''
        self.generation += 1
        request = dict(snapshot=snapshot, runtime=runtime, width=width, height=height, generation=self.generation,
                       samples=samples, environment=environment, threads=threads, output=output,
                       linear_preview=linear_preview, moonlightipr=moonlightipr, resume=bool(resume),
                       # A safe render is rendered by the MoonRay kept loaded where that one can save as it renders,
                       # and so is shown as it comes on; else by a MoonRay of its own, shown at each save.
                       persistent=bool(persistent_preview and not moonlightipr and not output and not linear_preview and persistent_supported(runtime)
                                       and (not denoising.settings(snapshot.get('denoising',{}))['safe'] or persistent_saves(runtime))))
        # New edits replace queued work; stale images never reach the panel.
        self.pending = request
        # A stop that was still waiting for MoonRay to save is over: this render is not one being stopped.
        self.settling=False;self.settle_wanted=None;self.gather=None
        if not request['persistent']:self.session.stop()
        # One renderer at a time holds the GPU and the scene.
        if not moonlightipr:self.moonlightipr.release()
        if self.process.state() != QtCore.QProcess.NotRunning:
            self.canceled = True
            self.process.kill()
        else:
            self._begin_pending()

    def resume_denoise(self,output,runtime,settings):
        from .postprocess import recover
        runtime=native.find_runtime(runtime);engine=denoising.settings(settings)['engine'];guides=recover(output,engine)
        self.generation+=1;self.canceled=False;self.pending=None;self.using_session=False
        self.active={'output':str(output),'runtime':runtime,'snapshot':{'denoising':settings},'generation':self.generation}
        self.image_path=Path(output);self.original_published=True;self.current_base=Path(self.directory.name)/uuid.uuid4().hex
        self.post_jobs=denoising.jobs(runtime,self.image_path,self.current_base,engine,guides);self.denoise_result=self.post_jobs[-1][2]
        self.progress_state=Progress();self.progress_timer.start()
        env=QtCore.QProcessEnvironment()
        for key,value in native.environment(runtime).items():env.insert(key,value)
        self.process.setProcessEnvironment(env);self._next_post()

    def settle(self):
        """Stop a preview as though it had come to its end: what is rendered so far is the finished picture, sent
        whole and reported as finished, so that what follows a render (the denoiser among it) follows this too.
        Returns whether that could be asked for; where it could not, stop() is what there is."""
        if self.closed or self.canceled or not self.active or self.active.get('output') or not getattr(self,'using_moonlightipr',False):
            return False
        if not self.moonlightipr.finish():
            return False
        self.pending = None
        return True

    def keep_progress(self):
        """Before a MoonRay preview is stopped: have MoonRay, kept loaded, hand over the beauty and the denoiser's
        two guides as they stand, so that a render stopped part way is kept and can be denoised. Returns whether
        that is under way; `kept` then tells how it went, with the render stopped."""
        if (self.closed or self.canceled or not self.active or self.active.get('output') or getattr(self,'using_moonlightipr',False)
                or not getattr(self,'using_session',False) or self.active['snapshot'].get('_ipr') or getattr(self,'phase','')!='render'
                or not getattr(self,'denoise_guides',None) or getattr(self,'gather',None) is not None or self.buffers.progressive is None):
            return False
        # Each is taken five times over, and the middle value of the last three used for each pixel. A pixel MoonRay
        # is adding to as its picture is taken is caught part way, too dark, and the denoiser would smear it into a
        # mark. MoonRay holds such a pixel at what it last showed, but the first picture of a buffer has nothing
        # earlier to hold it at, and the second may hold it at the first: so those two are let go by. The beauty is
        # asked for last, so as to be the newest.
        from .persistent import holds,drains
        if drains(self.active['runtime']) and self.session.drain():
            # A MoonRay that can finish with what it has in hand does so: the tiles its workers are on are rendered
            # to the end, with the light of their samples, and the frame ends as a finished one, every buffer of
            # it written. Nothing is left dark or coarse, and what follows is what follows any finished render.
            self.pending=None;self.passes=[];self.draining=True
            return True
        self.gather=gather={'want':['denoise_albedo']*5+['denoise_normal']*5+['beauty']*5,'got':{}}
        self.pending=None
        if holds(self.active['runtime']):
            # A MoonRay that can hand over several views at one asking hands each over once, with no waiting on the
            # host between them. Three rounds of them, for the middle to be taken, took twice as long and left the
            # denoised picture no cleaner.
            gather['want']=['denoise_albedo','denoise_normal','beauty'];gather['held']=True
            if self.session.hold(gather['want']):
                QtCore.QTimer.singleShot(12000,lambda:self._gathered(gather,False))
                return True
            gather['want']=['denoise_albedo']*5+['denoise_normal']*5+['beauty']*5;gather['held']=False
        self.session.select_view(gather['want'][0])
        QtCore.QTimer.singleShot(12000,lambda:self._gathered(gather,False))
        return True

    def _gathered(self,gather,whole):
        if getattr(self,'gather',None) is not gather:return
        self.gather=None
        done=False
        if whole and not self.closed and not self.canceled and self.active:
            done=self.buffers.keep({key:taken[-3:] for key,taken in gather['got'].items()},self.active['runtime'],self.active['snapshot'],self.backend_status)
        self.session.select_view('beauty')
        if not self.closed:
            self.stop();self.kept.emit(done)

    def settle_moonray(self):
        """Stop MoonRay where it stands and finish with the picture it last saved, where safe denoising had it save
        one. Returns whether that is under way: the render then ends as any other does, or reports stopped if
        nothing had been saved yet."""
        loaded=getattr(self,'using_session',False)
        if (self.closed or self.canceled or not self.active or getattr(self,'using_moonlightipr',False)
                or not getattr(self,'safe_files',None) or getattr(self,'phase','')!='render'
                or not (self.session.running() if loaded else self.process.state()!=QtCore.QProcess.NotRunning)):
            return False
        # The MoonRay kept loaded can hand over its picture as it stands: before its first save, that is what is
        # kept, in place of nothing.
        if loaded and not getattr(self,'safe_whole',False) and not getattr(self,'safe_written',None):return False
        self.stopped_at=time.monotonic()
        self.settling=True;self.pending=None;self.watchdog.stop()
        # MoonRay may be part way through saving, and a file cut short is no picture. Between saves, with a whole
        # save made, it is ended at once and that save is the render. Part way through one, or before the first,
        # it is ended the moment the save is whole; or after a wait, should that not come.
        self.settle_wanted=set()
        # The wait is for this stop alone: a later one is not cut short by it.
        self.settle_serial=serial=getattr(self,'settle_serial',0)+1
        between=getattr(self,'safe_whole',False) and not getattr(self,'safe_written',None)
        QtCore.QTimer.singleShot(0 if between else 20000,lambda:self._settle_now() if self.settle_serial==serial else None)
        return True

    def _settle_now(self):
        if getattr(self,'settling',False) and getattr(self,'settle_wanted',None) is not None:
            self.settle_wanted=None
            if getattr(self,'using_session',False):
                # The MoonRay kept loaded is ended, and what it last saved is finished with as its render.
                # Not from within the reading of its own output, which is where the last save is heard of.
                def ended():
                    if self.closed or not getattr(self,'settling',False):return
                    self.session.stop()
                    self.session.process.waitForFinished(3000)
                    self._exited(1,QtCore.QProcess.CrashExit)
                QtCore.QTimer.singleShot(0,ended)
            elif self.process.state()!=QtCore.QProcess.NotRunning:self.process.kill()

    def _safe_key(self,path):
        """What a file of a render is, apart from which render it is of: the end of its name."""
        name=Path(path).name;base=self.current_base.name
        return name[len(base):] if name.startswith(base) else name

    def _promote_safe(self):
        """Put the pictures MoonRay last saved where its finished files would be, and keep them aside for the
        render to be taken up again from. False if any is missing."""
        import os
        from .sequence_plan import valid_exr
        pairs=[(path,Path(denoising.safe_name(path))) for path in self.safe_files]
        if not pairs or not all(valid_exr(saved) for _,saved in pairs):return False
        try:
            kept={}
            if not self.active.get('output'):
                if getattr(self,'resume_directory',None) is None:self.resume_directory=tempfile.TemporaryDirectory(prefix='MoonRayResume-')
                stamp=uuid.uuid4().hex[:8]
                for path,saved in pairs:
                    aside=Path(self.resume_directory.name)/(stamp+self._safe_key(path))
                    shutil.copyfile(str(saved),str(aside));kept[self._safe_key(path)]=str(aside)
            for path,saved in pairs:os.replace(str(saved),str(path))
        except OSError:return False
        # What was kept before is let go of, now that there is something newer.
        for old in (getattr(self,'resumable',None) or {}).values():
            try:Path(old).unlink()
            except OSError:pass
        self.resumable=kept or None
        return True

    def stop(self):
        self.settling=False;self.settle_wanted=None;self.gather=None
        self._progress_end(False)
        self.watchdog.stop()
        self.pending = None
        self.session.stop()
        self.moonlightipr.stop()
        self.canceled = True
        if self.process.state() != QtCore.QProcess.NotRunning:
            self.process.kill()
        self.status.emit('Stopped')

    def _begin_pending(self):
        if self.closed or not self.pending:
            return
        if getattr(self, 'writer', None) is not None:
            # A scene is being written for the render this one replaces: this one begins when that is done with.
            self.writer.abandoned = True
            return
        self.active, self.pending = self.pending, None
        if not self.session.running():
            for path in Path(self.directory.name).iterdir():
                if path.is_file():path.unlink()
        self.canceled = False
        self.draining = False
        self.progress_state=Progress()
        self.progress_timer.start()
        # Smart Render watches a MoonRay preview's picture as it comes on (not one that follows the scene, nor an
        # output, nor MoonLightIPR's).
        self.smart=None
        try:
            level=denoising.settings(self.active['snapshot'].get('denoising',{}))['smart']
            if level!='off' and not self.active['output'] and not self.active['moonlightipr'] and not self.active.get('linear_preview') and not self.active['snapshot'].get('_ipr'):
                from .smart_render import Watch
                self.smart=Watch(level,time.monotonic)
        except (ValueError,KeyError):pass
        self.using_moonlightipr=self.active['moonlightipr']
        if self.using_moonlightipr:
            self._begin_moonlightipr();return
        target = int(self.active['samples'])
        adaptive=options.render_values(self.active['snapshot'].get('render_settings',{}))['sampling_mode']==2
        # A render taken up again goes straight on with its long pass. So does one by the MoonRay kept loaded, which
        # shows its picture as it comes on: two quick passes before the long one, each begun from nothing, were a
        # first look that such a render gives anyway, and on a heavy scene took a third of the whole time. Only a
        # MoonRay of its own, whose picture is seen when a pass ends, is still given them.
        self.passes = [target] if self.active['output'] or self.active.get('resume') or adaptive or self.active['snapshot'].get('_ipr_refined') or self.active.get('persistent') else sorted(set([1, min(2, target), target]))
        # The estimate of the time left is of the whole render: it is told what passes there are, by their samples.
        self.progress_state.plan([side*side for side in self.passes],adaptive)
        self.log = ''
        self.bucket_partial = ''
        self._begin_pass(self.active['generation'])

    def _begin_moonlightipr(self):
        """Hand the snapshot to the GPU preview; it accumulates and publishes frames itself."""
        request=self.active
        self.passes=[];self.log='';self.bucket_partial='';self.backend_log=''
        self.phase='render';self.using_session=False;self.gpu_error=False
        self.original_published=False;self.post_jobs=[];self.denoise_result=None
        self.backend_status=MOONLIGHTIPR_STATUS;self.moonlightipr_frame=None
        self._progress_tick()
        directory=moonlightipr_directory(request['runtime'])
        if not moonlightipr_supported(directory):
            self.failed.emit('This runtime has no MoonLightIPR GPU preview (expected in '+str(directory)+'). Choose MoonRay as the preview engine.');return
        self.status.emit('Rendering · '+self.backend_status)
        self.moonlightipr_serial+=1
        # MoonLightIPR denoises when its denoised beauty was the buffer chosen as the render was asked for, and then
        # has both pictures: the denoised one and the beauty as it is rendered. Which is shown is the buffer chosen.
        self.moonlightipr_denoises=bool(getattr(self,'moonlightipr_wanted',False))
        self.moonlightipr.submit(request['snapshot'],directory,request['width'],request['height'],request['environment'],self.moonlightipr_serial,getattr(self,'moonlightipr_samples',None) or getattr(self,'moonlightipr_preview_samples',None) or MOONLIGHTIPR_SAMPLES,
                                 denoise=self.moonlightipr_denoises,runtime=request['runtime'])
        self.moonlightipr.view(self.moonlightipr_denoises or self.buffers.key!='beauty')

    def _moonlightipr_memory(self,packet):
        if self.closed or self.canceled or not self.using_moonlightipr or packet[0]!=self.moonlightipr_serial:return
        self.moonlightipr_frame=packet
        self._moonlightipr_flush()

    def _moonlightipr_flush(self,*args):
        """Show the newest frame once the display is free, so the final one is never dropped."""
        packet=self.moonlightipr_frame
        if packet is None or self.closed or self.canceled or not self.using_moonlightipr or packet[0]!=self.moonlightipr_serial:return
        if self.buffers.busy():return # retried when the conversion in flight reports back
        self.moonlightipr_frame=None
        serial,key,width,height,pixels=packet
        try:self.buffers.publish_memory(key,width,height,pixels,self.active['runtime'],self.active['snapshot'],self.backend_status)
        except (ValueError,OSError) as exc:self.status.emit('Progressive display skipped: '+str(exc))

    def _moonlightipr_ready(self,serial):
        if self.closed or self.canceled or not self.using_moonlightipr or serial!=self.moonlightipr_serial:return
        self.finished.emit('')

    def _begin_pass(self, generation):
        if self.closed or self.canceled or self.active['generation'] != generation:
            return
        request = self.active
        self.sample_grid = self.passes.pop(0)
        self.current_base = Path(self.directory.name) / uuid.uuid4().hex
        scene = self.current_base.with_suffix('.rdla')
        self.image_path = self.current_base.with_suffix('.exr')
        self.phase = 'render'
        self.using_session=request['persistent']
        self.progress_state.reset_pass()
        self._progress_tick()
        self.original_published=False
        self.post_jobs=[]
        self.denoise_result=None
        self.backend_log = ''
        self.gpu_error = False
        mode=request['snapshot'].get('execution_mode','auto')
        self.pool_warnings=0
        if self.cpu_fallback and mode!=self.fallback_mode:
            # The user has chosen a mode since: theirs is tried again.
            self.cpu_fallback=False
        if self.cpu_fallback and mode in ('auto','xpu'):
            mode='vectorized'
        # Two things this build of MoonRay draws rightly in its scalar mode only.
        slow=scalar_only(request['snapshot'])
        if mode!='scalar' and slow:
            mode='scalar'
            request['snapshot'].setdefault('warnings',[]).append(slow+" is rendered in MoonRay's scalar mode, which is slower: its vector and GPU modes do not draw it rightly in this build.")
        self.backend_status={'auto':'Auto requested (XPU → Vector → Scalar)','xpu':'XPU requested','vectorized':'Vector requested','vector':'Vector requested','scalar':'Scalar requested'}[mode]
        self.buffer_key = 'beauty'
        self.buffer_path = self.current_base.with_suffix('.buffer.exr')
        snapshot = dict(request['snapshot'],preview_buffer=self.buffer_key)
        if getattr(self,'smart',None) is not None:
            # Smart Render judges the picture as a whole, so the picture is rendered all over at once: the tiles
            # are taken in no order, in place of one part of it being finished long before another.
            snapshot['render_settings']=dict(snapshot.get('render_settings') or {},batch_tile_order=5)
        snapshot['_crypto_categories']=native.supports_crypto_categories(request['runtime'])
        snapshot['_paired_instance_motion']=native.supports_paired_instance_motion(request['runtime'])
        if not request['output'] and not request.get('linear_preview'):
            self.preview_files={key:self.current_base.with_suffix('.'+key+'.exr') for key in outputs.preview(snapshot)}
            self.buffer_path=self.preview_files['beauty']
            snapshot['preview_buffer_files']={key:str(path) for key,path in self.preview_files.items()}
            snapshot.pop('preview_buffer_file',None)
        else:
            snapshot.pop('preview_buffer_file',None)
            snapshot.pop('preview_buffer_files',None)
        self.denoise_guides={}
        snapshot.pop('_denoise_guides',None)
        try:
            use_denoise=denoising.enabled(snapshot,bool(request['output']),request.get('linear_preview',False))
            if denoising.guides_required(snapshot,bool(request['output']),request.get('linear_preview',False)):
                snapshot['_denoise_guides']={key:str(self.current_base.with_suffix('.denoise-'+key+'.exr')) for key in ('albedo','normal')}
                self.denoise_guides=snapshot['_denoise_guides']
            if use_denoise:
                if request['output'] and denoising.sidecar(request['output']).exists(): raise ValueError('Denoised output already exists: '+str(denoising.sidecar(request['output'])))
                self.post_jobs=denoising.jobs(request['runtime'],self.image_path if request['output'] else self.buffer_path,self.current_base,denoising.settings(snapshot['denoising'])['engine'],snapshot['_denoise_guides'])
                self.denoise_result=self.post_jobs[-1][2]
            if mode=='xpu' and not native.supports_xpu(request['runtime']):
                raise ValueError('The selected runtime has no XPU GPU program/CUDA runtime. Choose the XPU runtime or CPU mode.')
            snapshot.pop('_deep_file',None);self.deep_path=None
            if request['output'] and (snapshot.get('deep') or {}).get('enabled'):
                if snapshot.get('_recovery') or (snapshot.get('recovery') or {}).get('enabled'):
                    snapshot.setdefault('warnings',[]).append('A deep EXR is not written while checkpoints are being saved; turn one of the two off.')
                else:
                    self.deep_path=self.current_base.with_suffix('.deep.exr');snapshot['_deep_file']=self.deep_path.as_posix()
            if request['output']:
                from .recovery import prepare as prepare_recovery
                snapshot['_recovery']=prepare_recovery(snapshot,request['output'],request['width'],request['height'],self.sample_grid,request['environment'],request['runtime'])
            # Safe denoising: MoonRay saves each file it is writing every few seconds, to be finished with on Stop.
            self.safe_files=[];snapshot.pop('_safe',None)
            if denoising.settings(snapshot.get('denoising',{}))['safe'] and not snapshot.get('_ipr') and not snapshot.get('_recovery') and not request.get('linear_preview'):
                data=self.current_base.with_suffix('.resume-data.exr')
                snapshot['_safe']={'data':str(data)}
                self.safe_written=set();self.safe_whole=False;self.safe_tail='';self.saved_at=None;self.kept_behind=None
                self.safe_files=([Path(self.image_path)] if request['output'] else [Path(path) for path in self.preview_files.values()])+[Path(path) for path in self.denoise_guides.values()]+[data]
                snapshot['_safe']['minutes']=self.safe_minutes=denoising.safe_minutes(len(self.safe_files),request['width'],request['height'])
                if request.get('resume') and getattr(self,'resumable',None):
                    # Each file is taken up from what was saved of it, known by the end of its name.
                    held={path:self.resumable.get(self._safe_key(path)) for path in self.safe_files}
                    if all(saved and Path(saved).is_file() for saved in held.values()):
                        snapshot['_safe']['resume']={str(path):str(saved) for path,saved in held.items()}
                # What was kept is spent on this render: there is something to continue again only if this one is
                # stopped in its turn. It is held on to in case this one is stopped before it has saved anything.
                self.resumable_before,self.resumable=getattr(self,'resumable',None),None
            arguments = (snapshot, request['width'], request['height'], self.sample_grid, request['environment'],
                         str(self.image_path) if request['output'] else None)
            if self.using_session and not request['output']:
                # A preview by the MoonRay kept loaded, which is what follows a scene: its text is written on a
                # thread of its own, and the pass goes on from _written when that is done.
                self.writer = SceneWriter(arguments, scene, (request, snapshot, scene, mode), generation, self, applied=self.session.applied)
                self.writer.finished.connect(self._written)
                self.writer.start()
                return
            text = rdla.scene_text(*arguments)
            scene.write_text(text, encoding='utf-8')
        except Exception as exc:
            self.failed.emit(str(exc));return
        self._pass_ready(request, snapshot, scene, mode, text)

    def _quitting(self):
        worker = getattr(self, 'writer', None)
        if worker is not None:
            worker.abandoned = True
            worker.wait(5000)

    def _written(self):
        worker = getattr(self, 'writer', None)
        if worker is None:
            return
        # finished may arrive while the thread is still unwinding: it is kept until it has ended.
        if not worker.wait(0):
            QtCore.QTimer.singleShot(5, self._written);return
        self.writer = None
        text, error = worker.outcome or (None, 'The scene was not written')
        worker.deleteLater()
        if self.closed:
            return
        if worker.abandoned or self.canceled or not self.active or self.active.get('generation') != worker.generation:
            # Something newer was asked for meanwhile, or the render was stopped: what was asked for takes its turn.
            if self.pending and self.process.state() == QtCore.QProcess.NotRunning:
                self._begin_pending()
            return
        if error:
            self.failed.emit(error);return
        self._pass_ready(*worker.context, text, prepared=worker.prepared)

    def _pass_ready(self, request, snapshot, scene, mode, text, prepared=None):
        """The pass's scene is written: MoonRay is given it."""
        try:
            env = QtCore.QProcessEnvironment()
            for key, value in native.environment(request['runtime']).items():
                env.insert(key, value)
            env.insert('MOONRAY_MODO_BUCKETS','1')
            bucket_size=options.render_values(snapshot.get('render_settings',{}))['bucket_size']
            env.insert('MOONRAY_MODO_BUCKET_SIZE',str(bucket_size))
            self.process.setProcessEnvironment(env)
            self.process.setWorkingDirectory(self.directory.name)
            self.process.setProgram(str(request['runtime'] / 'moonray.exe'))
            args=native.arguments(scene, self.image_path, request['threads'],mode)
            sampling=options.render_values(snapshot.get('render_settings',{}))
            if sampling['sampling_mode']==2 and '-info' not in args: args.append('-info')
            self.process.setArguments(args)
            label=('Adaptive rendering, %d–%d SPP, error %g' % (sampling['min_adaptive_samples'],sampling['max_adaptive_samples'],sampling['target_adaptive_error'])) if sampling['sampling_mode']==2 else ('Rendering %d samples/pixel' % (self.sample_grid**2))
            if snapshot.get('_ipr'):label='LS · '+label
            self.status.emit(label+' · '+self.backend_status)
            if self.using_session:
                self.session_serial+=1
                # Only this render's own progress lines count towards its estimate.
                if self.progress_state:self.progress_state.generation=self.session_serial
                self.session_files[self.session_serial]=self.current_base
                self._started()
                self.session.submit(text,request['runtime'],request['threads'],mode,self.session_serial,bucket_size,prepared=prepared)
            else:
                self.process.start()
        except Exception as exc:
            self.failed.emit(str(exc))

    def _fall_back_to_cpu(self):
        if self.closed or self.canceled or not getattr(self,'active',None):
            self.cpu_fallback=False;return
        self.fallback_mode=self.active['snapshot'].get('execution_mode','auto')
        self.status.emit('The GPU ran out of room for this scene with all its buffers; rendering it on the CPU instead')
        self.generation+=1
        self.pending=dict(self.active,generation=self.generation)
        if self.using_session:
            # Asked for in another mode, the session ends its process and starts one anew.
            self._begin_pending()
        elif self.process.state()!=QtCore.QProcess.NotRunning:
            self.canceled=True
            self.process.kill()
        else:
            self._begin_pending()

    def _read(self):
        text = bytes(self.process.readAllStandardOutput()).decode('utf-8', errors='replace')
        self._consume_log(text)

    def _consume_log(self,text):
        from .buckets import parse
        self.bucket_partial += text
        while '\n' in self.bucket_partial:
            line,self.bucket_partial=self.bucket_partial.split('\n',1)
            packet=parse(line)
            if packet and not self.closed and not self.canceled and self.phase=='render':
                expected=self.session_serial if self.using_session else 0
                if packet[0]==expected:
                    (self.workers if line.startswith('@@MODO_WORKERS ') else self.buckets).emit(packet)
        self.bucket_partial=self.bucket_partial[-65536:]

        self.log = (self.log + text)[-65536:]
        if self.phase=='render' and getattr(self,'safe_files',None) and self.active and not self.closed and not self.canceled:
            # A safe render's saves are followed as MoonRay reports them: which files of the save now being made
            # are written, and whether a whole save has been made yet.
            self.safe_tail=(getattr(self,'safe_tail','')+text)[-32768:]
            lines=self.safe_tail.splitlines(True)
            self.safe_tail=lines.pop() if lines and not lines[-1].endswith('\n') else ''
            names={Path(denoising.safe_name(path)).name for path in self.safe_files};whole=False
            for line in lines:
                if not line.startswith('Wrote: '):continue
                name=Path(line[7:].strip()).name
                if name not in names:continue
                self.safe_written.add(name)
                if self.safe_written>=names:
                    self.safe_written=set();self.safe_whole=whole=True;self.saved_at=time.monotonic()
            saved=Path(denoising.safe_name(self.buffer_path))
            if whole and not self.active.get('output') and not getattr(self,'settling',False) and not self.using_session and saved.is_file():
                # A safe render is a MoonRay of its own, which shows nothing until a pass ends: each save of the
                # beauty is shown as it is made, so that the picture is seen to come on.
                try:self.buffers.publish({'beauty':str(saved)},self.active['runtime'],self.active['snapshot'],self.backend_status,partial=True)
                except (ValueError,OSError):pass
            # Waiting to stop: it is ended the moment the save it was making is whole.
            if whole and getattr(self,'settling',False) and getattr(self,'settle_wanted',None) is not None:self._settle_now()
        if self.phase=='render':
            if self.progress_state: self.progress_state.feed(text)
            self.backend_log=(self.backend_log+text)[-16384:]
            if any(term in self.backend_log for term in ('optixLaunch() failure','cudaStreamSynchronize() error')):
                self.gpu_error=True
            # In GPU mode MoonRay keeps what each ray in flight owes every output in a store of fixed size. A scene with
            # many outputs and adaptive sampling can fill it; MoonRay then warns without end and at last stops with an
            # error. The CPU modes do not hold rays that way, so the render is begun again there.
            self.pool_warnings+=text.count("Couldn't allocate a CacheLine")
            if (self.pool_warnings>200 or 'timed out whilst trying to allocate a CacheLine' in text) and not self.cpu_fallback \
                    and getattr(self,'active',None) and not self.closed and not self.canceled:
                # Not from in here, where the renderer's own output is being read: once this has returned.
                self.cpu_fallback=True
                QtCore.QTimer.singleShot(0,self._fall_back_to_cpu)
            selected=native.execution_status(self.backend_log)
            if selected and selected!=self.backend_status:
                self.backend_status=selected
                self.status.emit('Rendering · '+selected)

    def _persistent_applied(self,serial):
        # Acknowledgement means older native output files are no longer in use.
        for old in list(self.session_files):
            if old>=serial:continue
            base=self.session_files.pop(old)
            for path in base.parent.glob(base.name+'*'):
                try:path.unlink()
                except OSError:pass

    def _select_view(self,key):
        if getattr(self,'using_moonlightipr',False):
            # MoonLightIPR has its beauty and its denoised picture both: it sends the one now chosen.
            self.moonlightipr.view(key!='beauty');return
        if key=='denoised_beauty':return # Post-process result, not a native render output.
        snapshot=self.active['snapshot'] if getattr(self,'active',None) else {}
        if outputs.display_kind(snapshot,key)=='cryptomatte':
            self.status.emit('Cryptomatte ID colors become available when the current pass completes.')
            return # Cryptomatte requires every ID/coverage channel, not a 3-float snapshot.
        self.session.select_view(key)

    def _persistent_memory(self,packet):
        serial,key,width,height,pixels=packet
        # While a pass's scene is being written, what the loaded MoonRay reports is of the render that pass replaces:
        # the pass has its files named already and has not been handed over yet.
        if self.closed or self.canceled or not self.using_session or serial!=self.session_serial or getattr(self,'writer',None) is not None:return
        gather=self.gather
        if gather is not None:
            # Being stopped: the pictures asked for are taken as they come, one after another, and not shown.
            if key==gather['want'][0]:
                gather['got'].setdefault(key,[]).append((width,height,pixels));gather['want'].pop(0)
                if gather['want'] and gather['want'][0]!=key and not gather.get('held'):self.session.select_view(gather['want'][0])
                if not gather['want']:self._gathered(gather,True)
            return
        try:self.buffers.publish_memory(key,width,height,pixels,self.active['runtime'],self.active['snapshot'],self.backend_status)
        except (ValueError,OSError) as exc:self.status.emit('Progressive display skipped: '+str(exc))
        # Smart Render: is the beauty clean enough yet? Not in the two quick passes before the long one, whose
        # pictures are only a first look.
        smart=getattr(self,'smart',None)
        if smart is not None and key=='beauty' and not self.passes and self.phase=='render':
            try:
                if smart.look(width,height,pixels):self.settled_clean.emit(float(smart.noise))
            except Exception:self.smart=None

    def _persistent_image(self,serial,key,path):
        # While a pass's scene is being written, what the loaded MoonRay reports is of the render that pass replaces:
        # the pass has its files named already and has not been handed over yet.
        if self.closed or self.canceled or not self.using_session or serial!=self.session_serial or getattr(self,'writer',None) is not None:return
        try:self.buffers.publish({key:path},self.active['runtime'],self.active['snapshot'],self.backend_status,partial=True)
        except (ValueError,OSError) as exc:self.status.emit('Progressive display skipped: '+str(exc))

    def _persistent_ready(self,serial):
        # While a pass's scene is being written, what the loaded MoonRay reports is of the render that pass replaces:
        # the pass has its files named already and has not been handed over yet.
        if self.closed or self.canceled or not self.using_session or serial!=self.session_serial or getattr(self,'writer',None) is not None:return
        self._exited(0,QtCore.QProcess.NormalExit)

    def _error(self, error):
        if self.closed or self.canceled:
            return
        if error == QtCore.QProcess.FailedToStart:
            self.failed.emit('Cannot start '+('denoising tool' if self.phase=='denoise' else 'render tool')+': '+self.process.errorString()+(' Original EXR was preserved.' if getattr(self,'original_published',False) else ''))

    def _exited(self, code, exit_status):
        self.watchdog.stop()
        self._read()
        self.buckets.emit(None)
        if self.closed:
            return
        if self.canceled:
            self._begin_pending()
            return
        if getattr(self,'settling',False):
            # Stopped by hand under safe denoising: what MoonRay last saved is the render, and it ends as one.
            self.settling=False;self.settle_wanted=None
            if code==0 and exit_status==QtCore.QProcess.NormalExit:
                # MoonRay came to the end of its pass by itself while the stop was waiting: its own files are the
                # render, whole, and nothing saved part way is put in their place. No further pass follows.
                self.passes=[]
            elif self._promote_safe():
                code,exit_status=0,QtCore.QProcess.NormalExit;self.passes=[]
                # How long before the stop the picture now kept was saved: what was rendered since is not in it.
                if getattr(self,'saved_at',None) is not None and getattr(self,'stopped_at',None) is not None:
                    self.kept_behind=max(0.0,self.stopped_at-self.saved_at)
            else:
                self.resumable=getattr(self,'resumable_before',None)
                self.canceled=True;self._progress_end(False);self.status.emit('Stopped');self.stopped.emit();return
        if code != 0 or exit_status != QtCore.QProcess.NormalExit:
            status = code & 0xffffffff
            message = ('Denoising' if self.phase=='denoise' else 'Buffer conversion' if self.phase=='convert' else 'MoonRay') + ' failed (0x%08X). Open Render Log for details.' % status
            if status == 0xC000001D:
                message = ('MoonRay used an unsupported CPU instruction. This Windows runtime needs '
                           'a CPU-compatible rebuild. No render was produced.')
            if self.original_published: message+=' Original EXR preserved at '+str(self.active['output'])
            self.failed.emit(message)
            return
        if self.phase=='denoise':
            if not self.post_expected.is_file() or self.post_expected.stat().st_size<16:
                self.failed.emit('Denoising did not produce an output; original render preserved.');return
            if self.post_jobs: self._next_post();return
            self.phase='postdone'
            if self.active['output']:
                try: self._publish(self.denoise_result,denoising.sidecar(self.active['output']))
                except OSError as exc: self.failed.emit('Cannot save denoised beauty; original EXR preserved: '+str(exc));return
            # Keep the original beauty available for comparison.
        if self.phase=='render' and self.gpu_error:
            self.failed.emit('GPU execution failed. Open Render Log for details or select CPU (AVX).')
            return
        if self.phase=='render' and self.post_jobs:
            if not self.active['output'] and not self.active.get('linear_preview'):
                try:
                    self.buffers.publish(dict(self.preview_files,beauty=self.buffer_path,**{'denoise_'+k:v for k,v in self.denoise_guides.items()}),self.active['runtime'],self.active['snapshot'],self.backend_status)
                except Exception as exc:
                    self.failed.emit('Cannot retain original preview buffers: '+str(exc));return
            if self.active['output']:
                try:
                    self._publish(self.image_path,Path(self.active['output']));self.original_published=True
                    from .postprocess import preserve
                    preserve(self.active['output'],self.denoise_guides,denoising.settings(self.active['snapshot']['denoising'])['engine'])
                except OSError as exc: self.failed.emit('Cannot save original EXR: '+str(exc));return
            self._next_post();return
        if self.phase in ('render','postdone') and not self.active['output'] and not self.active.get('linear_preview'):
            try:
                files=dict(self.preview_files,beauty=self.buffer_path,**{'denoise_'+k:v for k,v in self.denoise_guides.items()})
                if self.phase=='postdone' and self.denoise_result:
                    files['denoised_beauty']=self.denoise_result
                self.buffers.publish(files,self.active['runtime'],self.active['snapshot'],self.backend_status)
                if self.phase=='postdone':self.buffers.frame['denoise_engine']=denoising.settings(self.active['snapshot']['denoising'])['engine']
            except Exception as exc:
                self.failed.emit('Cannot retain preview buffers: '+str(exc));return
            self._preview_pass_finished()
            return
        if not self.image_path.is_file() or self.image_path.stat().st_size < 16:
            self.failed.emit('MoonRay exited without a valid output image. Open Render Log for details.')
            return
        if self.active['output']:
            destination = Path(self.active['output'])
            try:
                if not self.original_published: self._publish(self.image_path,destination)
                deep=getattr(self,'deep_path',None)
                if deep is not None and deep.is_file():self._publish(deep,deep_beside(destination))
                self.deep_path=None
            except OSError as exc:
                self.failed.emit('Cannot save render: '+str(exc));return
            # The compositor's picture of the render, written beside it. A graph that cannot be made of this render
            # (it takes a buffer the render has not) is said so, and the render stands all the same.
            graph=self.active['snapshot'].get('compositor')
            if graph:
                try:
                    from .composite_output import write
                    denoised=getattr(self,'denoise_result',None) if self.phase=='postdone' else None
                    written=write(self.active['runtime'],graph,destination,denoised)
                    if written is not None:self.log+='Composite written: '+str(written)+'\n'
                except Exception as exc:
                    self.status.emit('The composite was not written: '+str(exc))
            self.finished.emit(str(destination))
            return
        self.image_ready.emit(str(self.image_path))
        self._preview_pass_finished()

    def _preview_pass_finished(self):
        if self.using_session:
            # BufferCache owns copies, independent of native/frame file lifetime.
            for path in Path(self.directory.name).iterdir():
                if path.is_file() and not path.name.startswith(self.current_base.name):
                    try:path.unlink()
                    except OSError:pass
        if self.passes:
            generation=self.active['generation']
            QtCore.QTimer.singleShot(0,lambda:self._begin_pass(generation))
        else:self.finished.emit('')

    @staticmethod
    def _publish(source,destination):
        destination=Path(destination)
        staged=destination.with_name(destination.name+'.'+uuid.uuid4().hex+'.tmp')
        try:
            shutil.copyfile(str(source),str(staged));staged.replace(destination)
        finally:
            if staged.exists(): staged.unlink()

    def _next_post(self):
        program,args,self.post_expected=self.post_jobs.pop(0)
        self.phase='denoise';self.process.setProgram(str(program));self.process.setArguments(args)
        self.status.emit('Denoising linear beauty...');self.process.start()

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.stop()
        if getattr(self, 'writer', None) is not None:
            self.writer.abandoned = True;self.writer.wait(5000)
        self.session.close()
        self.moonlightipr.close()
        self.buffers.close()
        if self.process.state() != QtCore.QProcess.NotRunning:
            self.process.waitForFinished(2000)
        if self.process.state() == QtCore.QProcess.NotRunning:
            self.directory.cleanup()
