"""Portable animation collection, bounded to a single captured frame at a time."""
import json,math
from pathlib import Path
from PySide2 import QtCore,QtWidgets
from . import animation,assets

class PackageSequence(QtCore.QObject):
    def __init__(self,panel,destination,first,last,step,fps,motion):
        super().__init__(panel)
        self.panel=panel;self.root=Path(destination).resolve();self.frames=list(range(first,last+1,step));self.fps=fps;self.motion=motion
        if not math.isfinite(fps) or fps<=0:raise ValueError('Frame rate must be positive')
        if self.root.exists():raise ValueError('Choose a new sequence folder')
        if not self.frames or len(self.frames)>10000:raise ValueError('Package between 1 and 10000 frames')
        self.root.mkdir(parents=True);self.finished=[];self.index=0
        import shutil
        shutil.copy2(str(Path(__file__).with_name('package_runner.py')),str(self.root/'render_sequence.py'))
        (self.root/'README.txt').write_text('Run python render_sequence.py --runtime PATH_TO_MOONRAY_RUNTIME. Add --missing to skip verified completed frames. Packaged assets are immutable and may share storage through hard links. Copying a frame folder preserves its independent asset paths. This exports render scenes, not editable LXO files.\n',encoding='utf-8')
        self.dialog=QtWidgets.QProgressDialog('Collecting render assets…','Cancel',0,len(self.frames),panel);self.dialog.setWindowTitle('Package MoonRay sequence');self.dialog.setAutoClose(False);self.dialog.setWindowModality(QtCore.Qt.ApplicationModal);self.dialog.show()
    def start(self):
        import modo
        self.scene_id=modo.Scene().renderItem.id;self.running=True
        self.previous_lock=self.panel.preview_lock.isChecked();self.panel.preview_lock.setChecked(True)
        QtCore.QTimer.singleShot(0,self.next)
    def next(self):
        if self.dialog.wasCanceled():self.finish('canceled');return
        if self.index>=len(self.frames):self.finish('complete');return
        frame=self.frames[self.index]
        try:
            import modo
            if modo.Scene().renderItem.id!=self.scene_id:raise ValueError('Scene changed during packaging')
            if animation.single_request is not None:raise ValueError('Another scene capture is active')
            animation.single_request=lambda:animation.capture_frame(frame/self.fps,self.panel.surface.currentIndex()==2,self.motion,self.fps)
            animation.single_result=None
            import lx
            try:lx.eval('moonray.captureMotion');snapshot=animation.single_result
            finally:animation.single_request=None;animation.single_result=None
            if snapshot is None:raise ValueError('Frame capture returned no scene')
            snapshot=self.panel._configure_snapshot(snapshot);w,h=self.panel._dimensions(snapshot,True)
            name='frame.%06d'%frame;assets.package(snapshot,self.root/name,w,h,self.panel.samples.value(),self.panel.environment.value(),asset_store=self.root/'shared-assets')
            self.finished.append({'frame':frame,'scene':name+'/scene.rdla','sha256':assets.file_hash(self.root/name/'scene.rdla')});self.index+=1;self.write('collecting');self.dialog.setValue(self.index)
            QtCore.QTimer.singleShot(0,self.next)
        except Exception as exc:self.finish('failed',str(exc))
    def write(self,status,error=''):
        data={'format':1,'status':status,'fps':self.fps,'requested':self.frames,'frames':self.finished,'error':error}
        staged=self.root/'sequence.json.tmp';staged.write_text(json.dumps(data,indent=2),encoding='utf-8');staged.replace(self.root/'sequence.json')
    def finish(self,status,error=''):
        self.running=False;self.panel.preview_lock.setChecked(self.previous_lock);self.panel.changes.invalidate()
        self.write(status,error);self.dialog.close();self.panel.status.setText('Sequence package '+status+(': '+error if error else ': '+str(self.root)))
