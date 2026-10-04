"""Asynchronous native renderer lifecycle; no Modo API calls here."""
from pathlib import Path
import shutil
import tempfile
import uuid
from PySide2 import QtCore
from . import native, rdla, options, denoising, outputs
from .progress import Progress, duration
from .buffer_cache import BufferCache
from .persistent import Session, supported as persistent_supported


class Renderer(QtCore.QObject):
    buckets = QtCore.Signal(object)
    image_ready = QtCore.Signal(str)
    image_object = QtCore.Signal(object)
    status = QtCore.Signal(str)
    failed = QtCore.Signal(str)
    finished = QtCore.Signal(str)
    progress = QtCore.Signal(int,str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.buffers=BufferCache(self)
        self.buffers.image_ready.connect(self.image_ready.emit)
        self.buffers.image_object.connect(self.image_object.emit)
        self.buffers.notice.connect(self.status.emit)
        self.session=Session(self)
        self.buffers.selected.connect(self._select_view)
        self.session.output.connect(self._consume_log)
        self.session.ready.connect(self._persistent_ready)
        self.session.image.connect(self._persistent_image)
        self.session.memory_image.connect(self._persistent_memory)
        self.session.acknowledged.connect(self._persistent_applied)
        self.session_files={}
        self.session.failed.connect(self.failed.emit)
        self.session.status.connect(self.status.emit)
        self.session_serial=0
        self.using_session=False
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

    def submit(self, snapshot, runtime, width, height, samples, environment, threads, output=None, linear_preview=False, persistent_preview=True):
        if self.closed:
            raise ValueError('Renderer is closed')
        runtime = native.find_runtime(runtime)
        if not output and not linear_preview:
            self.buffers.select(snapshot.get('preview_buffer','beauty'),snapshot.get('display',{}))
        self.buckets.emit(None)
        self.bucket_partial = ''
        self.generation += 1
        request = dict(snapshot=snapshot, runtime=runtime, width=width, height=height, generation=self.generation,
                       samples=samples, environment=environment, threads=threads, output=output,
                       linear_preview=linear_preview,
                       persistent=bool(persistent_preview and not output and not linear_preview and persistent_supported(runtime)))
        # New edits replace queued work; stale images never reach the panel.
        self.pending = request
        if not request['persistent']:self.session.stop()
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

    def stop(self):
        self._progress_end(False)
        self.watchdog.stop()
        self.pending = None
        self.session.stop()
        self.canceled = True
        if self.process.state() != QtCore.QProcess.NotRunning:
            self.process.kill()
        self.status.emit('Stopped')

    def _begin_pending(self):
        if self.closed or not self.pending:
            return
        self.active, self.pending = self.pending, None
        if not self.session.running():
            for path in Path(self.directory.name).iterdir():
                if path.is_file():path.unlink()
        self.canceled = False
        self.progress_state=Progress()
        self.progress_timer.start()
        target = int(self.active['samples'])
        adaptive=options.render_values(self.active['snapshot'].get('render_settings',{}))['sampling_mode']==2
        self.passes = [target] if self.active['output'] or adaptive else sorted(set([1, min(2, target), target]))
        self.log = ''
        self.bucket_partial = ''
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
        self.using_session=request['persistent']
        self.progress_state.reset_pass()
        self._progress_tick()
        self.original_published=False
        self.post_jobs=[]
        self.denoise_result=None
        self.backend_log = ''
        self.gpu_error = False
        mode=request['snapshot'].get('execution_mode','auto')
        self.backend_status={'auto':'Auto requested (XPU → Vector → Scalar)','xpu':'XPU requested','vectorized':'Vector requested','vector':'Vector requested','scalar':'Scalar requested'}[mode]
        self.buffer_key = 'beauty'
        self.buffer_path = self.current_base.with_suffix('.buffer.exr')
        snapshot = dict(request['snapshot'],preview_buffer=self.buffer_key)
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
        try:
            use_denoise=denoising.enabled(snapshot,bool(request['output']),request.get('linear_preview',False))
            if use_denoise or (not request['output'] and not request.get('linear_preview')):
                snapshot['_denoise_guides']={key:str(self.current_base.with_suffix('.denoise-'+key+'.exr')) for key in ('albedo','normal')}
                self.denoise_guides=snapshot['_denoise_guides']
            if use_denoise:
                if request['output'] and denoising.sidecar(request['output']).exists(): raise ValueError('Denoised output already exists: '+str(denoising.sidecar(request['output'])))
                self.post_jobs=denoising.jobs(request['runtime'],self.image_path if request['output'] else self.buffer_path,self.current_base,denoising.settings(snapshot['denoising'])['engine'],snapshot['_denoise_guides'])
                self.denoise_result=self.post_jobs[-1][2]
            if mode=='xpu' and not native.supports_xpu(request['runtime']):
                raise ValueError('The selected runtime has no XPU GPU program/CUDA runtime. Choose the XPU runtime or CPU mode.')
            if request['output']:
                from .recovery import prepare as prepare_recovery
                snapshot['_recovery']=prepare_recovery(snapshot,request['output'],request['width'],request['height'],self.sample_grid,request['environment'],request['runtime'])
            text = rdla.scene_text(snapshot, request['width'], request['height'],
                                   self.sample_grid, request['environment'],
                                   str(self.image_path) if request['output'] else None)
            scene.write_text(text, encoding='utf-8')
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
            if snapshot.get('_ipr'):label='IPR · '+label
            self.status.emit(label+' · '+self.backend_status)
            if self.using_session:
                self.session_serial+=1
                self.session_files[self.session_serial]=self.current_base
                self._started()
                self.session.submit(text,request['runtime'],request['threads'],mode,self.session_serial,bucket_size)
            else:
                self.process.start()
        except Exception as exc:
            self.failed.emit(str(exc))

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
                if packet[0]==expected:self.buckets.emit(packet)
        self.bucket_partial=self.bucket_partial[-65536:]

        self.log = (self.log + text)[-65536:]
        if self.phase=='render':
            if self.progress_state: self.progress_state.feed(text)
            self.backend_log=(self.backend_log+text)[-16384:]
            if any(term in self.backend_log for term in ('optixLaunch() failure','cudaStreamSynchronize() error')):
                self.gpu_error=True
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
        if key=='denoised_beauty':return # Post-process result, not a native render output.
        snapshot=self.active['snapshot'] if getattr(self,'active',None) else {}
        if outputs.display_kind(snapshot,key)=='cryptomatte':
            self.status.emit('Cryptomatte ID colors become available when the current pass completes.')
            return # Cryptomatte requires every ID/coverage channel, not a 3-float snapshot.
        self.session.select_view(key)

    def _persistent_memory(self,packet):
        serial,key,width,height,pixels=packet
        if self.closed or self.canceled or not self.using_session or serial!=self.session_serial:return
        try:self.buffers.publish_memory(key,width,height,pixels,self.active['runtime'],self.active['snapshot'],self.backend_status)
        except (ValueError,OSError) as exc:self.status.emit('Progressive display skipped: '+str(exc))

    def _persistent_image(self,serial,key,path):
        if self.closed or self.canceled or not self.using_session or serial!=self.session_serial:return
        try:self.buffers.publish({key:path},self.active['runtime'],self.active['snapshot'],self.backend_status,partial=True)
        except (ValueError,OSError) as exc:self.status.emit('Progressive display skipped: '+str(exc))

    def _persistent_ready(self,serial):
        if self.closed or self.canceled or not self.using_session or serial!=self.session_serial:return
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
            except OSError as exc:
                self.failed.emit('Cannot save render: '+str(exc));return
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
        self.session.close()
        self.buffers.close()
        if self.process.state() != QtCore.QProcess.NotRunning:
            self.process.waitForFinished(2000)
        if self.process.state() == QtCore.QProcess.NotRunning:
            self.directory.cleanup()
