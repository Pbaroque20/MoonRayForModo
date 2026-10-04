"""Isolated MoonRay Widget preview of draft native materials and node graphs."""
import copy
import json
import math
from pathlib import Path
from PySide2 import QtCore, QtWidgets
from . import coordinates, native, nodes, shader_library
from .rdla import IDENTITY
from .preview_diagnostics import record
from .render import Renderer
from .viewer import SoftwarePreview as Preview


def look_at(eye, target=(0, 0, 0)):
    def norm(v):
        length=math.sqrt(sum(x*x for x in v))
        return [x/length for x in v]
    def cross(a,b):
        return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
    back=norm([a-b for a,b in zip(eye,target)])
    right=norm(cross([0,1,0],back));up=cross(back,right)
    return right+[0]+up+[0]+back+[0]+list(eye)+[1]


def snapshot(material, library, all_parts=False):
    material=copy.deepcopy(material);library=copy.deepcopy(library)
    if material.get('node_graph'):
        material['node_graph']=nodes.validate(material['node_graph'])
        material['node_override']=True
    materials={'preview':material,'':{'color':[.18,.18,.18],'roughness':.3}}
    shader_library.attach_dependencies(materials,library)
    path=Path(__file__).resolve().parents[2]/'assets/library/MoonRayWidget/geometry.json'
    document=json.loads(path.read_text(encoding='utf-8'))
    if document.get('format')!=1:raise ValueError('Unsupported MoonRay Widget geometry')
    meshes=document['meshes'];points=[v for mesh in meshes for v in mesh['vertices']]
    low=[min(p[i] for p in points) for i in range(3)]
    high=[max(p[i] for p in points) for i in range(3)]
    center=[(a+b)/2 for a,b in zip(low,high)];scale=2/max(b-a for a,b in zip(low,high))
    descriptors=coordinates.descriptors(materials)
    for mesh in meshes:
        mesh['vertices']=[[(v[i]-center[i])*scale for i in range(3)] for v in mesh['vertices']]
        mesh['matrix']=IDENTITY[:]
        mesh['material']='preview' if all_parts or mesh['name'] not in ('base','stand') else ''
        mesh['uv_sets']={}
        for key,layer in descriptors.items():
            values=[];offset=0
            for face in mesh['faces']:
                uv=mesh['uvs'][offset:offset+len(face)];offset+=len(face)
                values.extend(coordinates.face(layer,[mesh['vertices'][i] for i in face],uv,IDENTITY))
            mesh['uv_sets'][key]=values
    return {'camera':{'identity':'widget/camera','matrix':look_at((2.5,1.4,3.8)),
                      'focal_mm':55,'film_mm':36},
            'meshes':meshes,'materials':materials,'native_materials':library,'fps':24,
            'lights':[{'identity':'widget/key','kind':'RectLight','matrix':look_at((2,3,3)),
                       'color':[1,1,1],'intensity':3,'width':2,'height':2},
                      {'identity':'widget/rim','kind':'RectLight','matrix':look_at((-2,1,-2)),
                       'color':[1,1,1],'intensity':2,'width':2,'height':3}],
            'display':{'view':'srgb'},'render_settings':{'sampling_mode':2,
                'min_adaptive_samples':4,'max_adaptive_samples':64,'target_adaptive_error':5.0}}


class Panel(QtWidgets.QWidget):
    def __init__(self,item,draft,parent=None,embedded=False):
        super().__init__(parent)
        self.item,self.draft=item,draft;self.closed=False;self.refreshing=False;self.last_signature=None
        layout=QtWidgets.QVBoxLayout(self);layout.setContentsMargins(4,4,4,4)
        layout.addWidget(QtWidgets.QLabel('MoonRay Widget'))
        bar=QtWidgets.QHBoxLayout();layout.addLayout(bar)
        self.live=QtWidgets.QCheckBox('Live material preview');self.live.setChecked(False);self.live.setVisible(embedded);bar.addWidget(self.live)
        refresh=QtWidgets.QPushButton('Refresh');bar.addWidget(refresh)
        stop=QtWidgets.QPushButton('Stop');bar.addWidget(stop)
        for button in (refresh,stop):button.setAutoDefault(False);button.setDefault(False)
        self.parts=QtWidgets.QCheckBox('Apply material to base and stand');layout.addWidget(self.parts)
        self.viewer=Preview(self);layout.addWidget(self.viewer,1)
        self.status=QtWidgets.QLabel('Live preview is off. Enable it or click Refresh.');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.setToolTip('Previews the current draft with widget UVs and studio lighting. Scene masks, projectors and hair geometry are not recreated. Live preview updates committed graph edits after a short pause.')
        credit=QtWidgets.QLabel('MoonRay Widget Copyright 2023–2025 DreamWorks Animation LLC. All rights reserved.\nASWF Digital Assets License v1.1');credit.setWordWrap(True);layout.addWidget(credit)
        self.renderer=Renderer(self)
        self.renderer.image_object.connect(self.viewer.set_image);self.renderer.image_ready.connect(self.viewer.load)
        self.renderer.status.connect(self.status.setText);self.renderer.failed.connect(self.preview_failed)
        self.renderer.buckets.connect(self.viewer.set_buckets)
        self.timer=QtCore.QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(650);self.timer.timeout.connect(self.refresh)
        self.live.toggled.connect(self.live_changed)
        self.parts.toggled.connect(lambda *_:self.schedule())
        refresh.clicked.connect(self.refresh,QtCore.Qt.QueuedConnection);stop.clicked.connect(self.stop)
        self.viewer.start_requested.connect(self.refresh,QtCore.Qt.QueuedConnection)
    def preview_failed(self,message):
        if not self.closed:self.status.setText('Preview failed: '+message)
    def live_changed(self,enabled):
        record("Live preview "+("enabled" if enabled else "disabled"))
        if enabled:self.schedule()
        else:
            self.timer.stop();self.renderer.stop();self.status.setText('Live preview off. Last image retained.')
    def schedule(self):
        if not self.closed and self.live.isChecked():self.timer.start()
    def graph_changed(self,graph):
        data=copy.deepcopy(graph)
        for node in data.get('nodes',{}).values():
            for key in ('position','expanded','label'):node.pop(key,None)
        signature=json.dumps(data,sort_keys=True)
        if signature!=self.last_signature:
            self.last_signature=signature;self.schedule()
    def stop(self):
        self.timer.stop()
        if self.live.isChecked():self.live.setChecked(False)
        else:self.renderer.stop()
    def capture_snapshot(self):
        import modo
        from .host import material_values
        library={candidate.id:material_values(candidate) for candidate in modo.Scene().items('advancedMaterial',superType=True)}
        draft=material_values(self.item);draft.update(self.draft());library[self.item.id]=draft
        return snapshot(draft,library,self.parts.isChecked())

    @QtCore.Slot()
    def refresh(self):
        if self.closed or self.refreshing:return
        self.refreshing=True
        try:
            record("Capture draft begin")
            scene=self.capture_snapshot()
            record("Capture draft complete")
            self.timer.stop()  # Draft commit can itself notify graph_changed.
            size=256 if self.live.isChecked() else 384
            if self.live.isChecked():scene['render_settings'].update(max_adaptive_samples=16,target_adaptive_error=10.0)
            settings=QtCore.QSettings('MoonRayForModo','NativePreview')
            runtime=native.default_runtime() or str(settings.value('runtime',''))
            record("Submit material preview; runtime="+str(runtime))
            self.renderer.submit(scene,runtime,size,size,2,.2,0)
        except Exception as exc:self.status.setText('Preview could not start: '+str(exc))
        finally:self.refreshing=False
    def shutdown(self):
        if self.closed:return
        self.closed=True;self.timer.stop()
        # waitForFinished can dispatch queued signals during shutdown. Detach
        # UI receivers first so they cannot touch a closing widget/context.
        for signal,slot in ((self.renderer.image_object,self.viewer.set_image),
                            (self.renderer.image_ready,self.viewer.load),
                            (self.renderer.status,self.status.setText),
                            (self.renderer.failed,self.preview_failed),
                            (self.renderer.buckets,self.viewer.set_buckets)):
            try:signal.disconnect(slot)
            except (RuntimeError,TypeError):pass
        self.viewer.bucket_timeout.stop();self.renderer.close()
    def closeEvent(self,event):
        self.shutdown();super().closeEvent(event)


class Dialog(QtWidgets.QDialog):
    def __init__(self,item,draft,parent=None):
        super().__init__(parent);self.setWindowTitle('MoonRay Widget — '+item.name);self.resize(520,620)
        layout=QtWidgets.QVBoxLayout(self);self.panel=Panel(item,draft,self);layout.addWidget(self.panel)
        self.finished.connect(lambda *_:self.panel.shutdown())
    def closeEvent(self,event):
        self.panel.shutdown();super().closeEvent(event)


def show(item,draft,parent=None):
    # A parent-owned modeless dialog keeps the editor available for draft edits.
    old=getattr(parent,'_widget_preview',None)
    if old is not None:old.close()
    dialog=Dialog(item,draft,parent)
    if parent is not None:parent._widget_preview=dialog
    dialog.show();dialog.raise_()
    return dialog
