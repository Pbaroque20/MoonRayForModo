"""Bounded frame-at-a-time render queue; scene sampling runs in a Modo command."""
from pathlib import Path
import json
import math
from PySide2 import QtCore
import lx
from . import host

active = None


def capture_frame(time, evaluated=False, motion=False, fps=24):
    selection = lx.service.Selection()
    original = selection.GetTime()
    try:
        selection.SetTime(float(time))
        snapshot = host.snapshot(evaluated_geometry=evaluated)
        if motion:
            camera = snapshot['camera']
            length = max(0,float(camera.get('shutter_length',.5)))
            offset = float(camera.get('shutter_offset',0))
            endpoints = [offset-length/2, offset+length/2]
            if length:
                samples = []
                for endpoint in endpoints:
                    selection.SetTime(float(time)+endpoint/fps)
                    samples.append(host.snapshot(evaluated_geometry=evaluated))
                apply_motion(snapshot, samples[0], samples[1], endpoints)
        return snapshot
    finally:
        selection.SetTime(original)


def apply_motion(scene, start, end, endpoints):
    scene['camera']['matrix'] = start['camera']['matrix']
    scene['camera']['matrix_close'] = end['camera']['matrix']
    scene['motion_steps'] = endpoints
    # Matching by export identity must be exact; topology changes cannot be
    # represented by a two-sample RdlMesh and must not blur unrelated points.
    for endpoint in (start,end):
        if len(endpoint['meshes']) != len(scene['meshes']):
            raise ValueError('Motion blur cannot export changing mesh counts')
    expanded=[]
    for mesh,a,b in zip(scene['meshes'], start['meshes'], end['meshes']):
        if any(m.get('identity',m['name']) != mesh.get('identity',mesh['name']) or m['faces'] != mesh['faces'] or
               len(m['vertices']) != len(mesh['vertices']) for m in (a,b)):
            raise ValueError('Motion blur requires stable geometry topology: '+mesh['name'])
        if 'instances' in mesh:
            if not mesh.get('instance_ids') or a.get('instance_ids')!=mesh['instance_ids'] or b.get('instance_ids')!=mesh['instance_ids']:
                raise ValueError('Motion blur requires stable instance identities')
            for identity,ma,mb in zip(mesh['instance_ids'],a['instances'],b['instances']):
                value=dict(mesh,name=mesh['name']+' / '+identity,matrix=ma,matrix_close=mb,vertices=a['vertices'],vertices_close=b['vertices'])
                value.pop('instances');value.pop('instance_ids',None)
                expanded.append(value)
        else:
            mesh.update(matrix=a['matrix'], matrix_close=b['matrix'],vertices=a['vertices'],vertices_close=b['vertices'])
            expanded.append(mesh)
    scene['meshes']=expanded
    if len(start['lights']) != len(end['lights']):
        raise ValueError('Motion blur cannot export changing light counts')
    for light,a,b in zip(scene['lights'],start['lights'],end['lights']):
        light.update(matrix=a['matrix'],matrix_close=b['matrix'])


class Sequence(QtCore.QObject):
    def __init__(self, panel, directory, first, last, fps, motion=False):
        super().__init__(panel)
        if last < first or last-first > 100000 or not math.isfinite(fps) or fps<=0:
            raise ValueError('Invalid animation frame range or frame rate')
        self.panel, self.directory = panel, Path(directory)
        if (self.directory/'moonray-sequence.json').exists():
            raise ValueError('Choose a new animation folder; a sequence manifest already exists')
        self.directory.mkdir(parents=True,exist_ok=True)
        self.frame, self.last, self.fps, self.motion = first,last,fps,motion
        self.running = False
        self.completed = []
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
        self.next_frame()

    def next_frame(self):
        if self.running:
            try:
                lx.eval('moonray.animationFrame')
            except Exception as exc:
                self.failed(str(exc))

    def capture(self):
        if not self.running:
            return
        destination = self.directory/('frame.%06d.exr'%self.frame)
        if destination.exists():
            raise ValueError('Animation output already exists: '+str(destination))
        snapshot = capture_frame(self.frame/self.fps, self.panel.surface.currentIndex()==2,
                                 self.motion, self.fps)
        snapshot = self.panel._configure_snapshot(snapshot)
        self.expected_output = destination.resolve()
        self.panel._submit(snapshot,str(destination))

    def finished(self, output):
        if not self.running or not output:
            return
        if self.expected_output is None or Path(output).resolve() != self.expected_output:
            self.failed('Received output from a different render; sequence stopped to protect frame numbering')
            return
        self.expected_output = None
        self.completed.append({'frame':self.frame,'file':output})
        try:
            self.write_manifest('rendering')
        except OSError as exc:
            self.failed('Frame saved, but sequence manifest could not be updated: '+str(exc))
            return
        if self.frame >= self.last:
            if not self.stop('complete'):
                self.panel.status.setText('Animation complete: %d frames'%len(self.completed))
        else:
            self.frame += 1
            QtCore.QTimer.singleShot(0,self.next_frame)

    def write_manifest(self, status):
        path = self.directory/'moonray-sequence.json'
        staged = path.with_suffix('.json.tmp')
        staged.write_text(json.dumps({'status':status,'fps':self.fps,'frames':self.completed},indent=2),encoding='utf-8')
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
