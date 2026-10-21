"""Bounded frame-at-a-time render queue; scene sampling runs in a Modo command."""
from pathlib import Path
import json
import math
import re
import hashlib
from PySide2 import QtCore
import lx
from . import host

active = None


def capture_frame(time, evaluated=False, motion=False, fps=24, preview=False):
    selection = lx.service.Selection()
    original = selection.GetTime()
    try:
        selection.SetTime(float(time))
        from . import properties
        from .extra_geometry import attach
        import copy
        asset_controls=copy.deepcopy(properties.scene_settings().get('production',{}))
        def capture():
            value=host.snapshot(evaluated_geometry=evaluated);attach(value,asset_controls);return value
        snapshot = capture()
        snapshot.pop('_evaluated_data',None);snapshot.pop('_full_capture',None)
        if motion:
            camera = snapshot['camera']
            length = max(0,float(camera.get('shutter_length',.5)))
            offset = float(camera.get('shutter_offset',0))
            endpoints = [offset-length/2, offset+length/2]
            if length:
                # Where nothing in the scene bends a mesh or makes one come and go, the meshes read at the frame hold
                # for the whole shutter: at its ends only where things stand is read (incremental.rigid), as when an
                # item is moved, not every mesh again: the same scene as reading them, in less time (a test interior
                # of 16 surfaces, 15.5 s to 10.6 s from opening; 7.7 s to 2.7 s read again).
                import modo
                from .incremental import rigid, item_matrices, follow_items
                document = modo.Scene()
                steady = rigid(document, snapshot)
                standing = item_matrices(document, snapshot) if steady else None
                samples = []
                for endpoint in endpoints:
                    selection.SetTime(float(time)+endpoint/fps)
                    if steady:
                        sample = host.snapshot(evaluated_geometry=evaluated, reuse_geometry=snapshot)
                        sample.pop('_full_capture', None)
                        follow_items(document, sample, standing)
                        attach(sample, asset_controls)
                        samples.append(sample)
                    else:
                        samples.append(capture())
                apply_motion(snapshot, samples[0], samples[1], endpoints, preview=preview)
                snapshot['_external_motion_settings']=asset_controls
        return snapshot
    finally:
        selection.SetTime(original)


from .motion import apply_motion


class Sequence(QtCore.QObject):
    def __init__(self, panel, directory, first, last, fps, motion=False, step=1, prefix="frame", missing=False, export_as=None):
        super().__init__(panel)
        # Each frame in another picture type as well, beside its EXR (image_formats): {'type', 'quality'}, or None.
        self.export_as = export_as
        if last < first or last-first > 100000 or not math.isfinite(fps) or fps<=0:
            raise ValueError('Invalid animation frame range or frame rate')
        if not isinstance(step,int) or step<1:
            raise ValueError('Frame step must be a positive integer')
        if not re.fullmatch(r'[A-Za-z0-9_-]+',prefix):
            raise ValueError('Output prefix must use letters, digits, underscores or hyphens')
        self.first,self.step,self.prefix=first,step,prefix
        self.total=len(range(first,last+1,step))
        self.panel, self.directory = panel, Path(directory)
        from .sequence_plan import plan
        from .assets import file_hash,signature as asset_signature
        import modo
        filename=modo.Scene().filename
        if missing and not (filename and Path(filename).is_file()):raise ValueError('Save the scene before resuming a sequence; unsaved scene revisions cannot be verified')
        source=[str(filename),file_hash(filename)] if filename and Path(filename).is_file() else ['unsaved',modo.Scene().renderItem.id]
        settings={k:v for k,v in panel._settings_values().items() if k not in ('display','preview_buffer','recovery')}
        snapshot=panel._capture()
        self.signature=hashlib.sha256(json.dumps([source,settings,asset_signature(snapshot)],sort_keys=True).encode()).hexdigest()
        self.pending_frames,self.completed=plan(self.directory,first,last,step,prefix,fps,motion,missing,settings.get('denoising',{}).get('final',True) and settings.get('denoising',{}).get('engine','off')!='off',self.signature)
        self.directory.mkdir(parents=True,exist_ok=True)
        self.frame, self.last, self.fps, self.motion = first,last,fps,motion
        self.running = False
        if self.pending_frames:self.frame=self.pending_frames.pop(0)
        self.expected_output = None

    def start(self):
        global active
        if active is not None and active.running:
            raise ValueError('An animation render is already running')
        active = self
        self.running = True
        self.panel.renderer.finished.connect(self.finished)
        self.panel.renderer.failed.connect(self.failed)
        try:
            self.write_manifest('rendering')
        except OSError as exc:
            self.failed('Cannot create sequence manifest: '+str(exc))
            return
        if len(self.completed)==self.total:self.stop('complete');self.panel.status.setText('All sequence frames already exist.')
        else:self.next_frame()

    def next_frame(self):
        if self.running:
            try:
                lx.eval('moonray.animationFrame')
            except Exception as exc:
                self.failed(str(exc))

    def capture(self):
        if not self.running:
            return
        destination = self.directory/('%s.%06d.exr'%(self.prefix,self.frame))
        if destination.exists():
            self.expected_output=destination.resolve()
            self.panel.renderer.resume_denoise(destination,self.panel.runtime_path(),self.panel._settings_values()['denoising'])
            return
        snapshot = capture_frame(self.frame/self.fps, self.panel._settings_values()['surface']==2,
                                 self.motion, self.fps)
        snapshot['frame']=self.frame;snapshot['fps']=self.fps
        snapshot = self.panel._configure_snapshot(snapshot)
        if self.export_as:snapshot['_export_as']=dict(self.export_as)
        self.expected_output = destination.resolve()
        self.panel._submit(snapshot,str(destination))

    def finished(self, output):
        if not self.running or not output:
            return
        if self.expected_output is None or Path(output).resolve() != self.expected_output:
            self.failed('Received output from a different render; sequence stopped to protect frame numbering')
            return
        self.expected_output = None
        from .assets import file_hash
        from .denoising import sidecar
        entry={'frame':self.frame,'file':output,'sha256':file_hash(output)}
        if sidecar(output).is_file():entry['denoised_sha256']=file_hash(sidecar(output))
        self.completed.append(entry)
        try:
            self.write_manifest('rendering')
        except OSError as exc:
            self.failed('Frame saved, but sequence manifest could not be updated: '+str(exc))
            return
        if not self.pending_frames:
            if not self.stop('complete'):
                self.panel.status.setText('Animation complete: %d frames'%len(self.completed))
        else:
            self.frame=self.pending_frames.pop(0)
            QtCore.QTimer.singleShot(0,self.next_frame)

    def write_manifest(self, status):
        path = self.directory/'moonray-sequence.json'
        staged = path.with_suffix('.json.tmp')
        staged.write_text(json.dumps({'signature':self.signature,'status':status,'fps':self.fps,'first':self.first,'last':self.last,'step':self.step,'prefix':self.prefix,'motion_blur':self.motion,'total_frames':self.total,'frames':sorted(self.completed,key=lambda value:value['frame'])},indent=2),encoding='utf-8')
        staged.replace(path)

    def failed(self, message):
        manifest_error = self.stop('failed')
        self.panel.status.setText('Animation stopped: '+message + ('; '+manifest_error if manifest_error else ''))

    def stop(self, status='canceled'):
        global active
        if not self.running:
            return
        self.running = False
        self.expected_output = None
        if active is self:
            active = None
        self.panel.renderer.finished.disconnect(self.finished)
        self.panel.renderer.failed.disconnect(self.failed)
        self.panel.renderer.stop()
        try:
            self.write_manifest(status)
        except OSError as exc:
            message = 'Could not save animation manifest: '+str(exc)
            self.panel.status.setText(message)
            return message


single_request=None
single_result=None

def capture_current(evaluated=False):
    """The scene now, with where things are at the shutter's ends. Read here and not through moonray.captureMotion:
    Modo holds a command back while another is under way (its colour picker's, for one), and the preview waited on
    it without end, Modo still answering (2026-10-21). capture_frame puts the time back as it found it."""
    global single_request
    import modo
    if single_request is not None:raise ValueError('A motion capture is already running')
    moment=lx.service.Selection().GetTime();fps=float(modo.Scene().fps)
    single_request=True
    try:return capture_frame(moment,evaluated,True,fps,preview=True)
    finally:single_request=None
