"""Isolated MoonRay Widget preview of draft native materials and node graphs."""
import copy
import json
import math
from pathlib import Path
from PySide2 import QtCore, QtWidgets
from . import coordinates, native, nodes, properties, shader_library
from .rdla import IDENTITY
from .render import Renderer
from .viewer import Preview


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


class Dialog(QtWidgets.QDialog):
    def __init__(self, item, draft, parent=None):
        super().__init__(parent)
        self.item,self.draft=item,draft
        self.setWindowTitle('MoonRay Widget — '+item.name);self.resize(520,620)
        layout=QtWidgets.QVBoxLayout(self);bar=QtWidgets.QHBoxLayout();layout.addLayout(bar)
        refresh=QtWidgets.QPushButton('Render / Refresh');bar.addWidget(refresh)
        stop=QtWidgets.QPushButton('Stop');bar.addWidget(stop)
        self.parts=QtWidgets.QCheckBox('Apply to base and stand');bar.addWidget(self.parts)
        self.viewer=Preview(self);layout.addWidget(self.viewer,1)
        self.status=QtWidgets.QLabel('Click Render / Refresh to preview the current draft.');self.status.setWordWrap(True);layout.addWidget(self.status)
        note=QtWidgets.QLabel('Native material / node draft with widget UVs and studio lighting. Refresh reads current draft edits. External Shader Tree masks, scene projectors and hair strands are not reproduced.');note.setWordWrap(True);layout.addWidget(note)
        credit=QtWidgets.QLabel('MoonRay Widget Copyright 2023–2025 DreamWorks Animation LLC. All rights reserved.\nASWF Digital Assets License v1.1 · Material demonstration asset.');credit.setWordWrap(True);layout.addWidget(credit)
        self.renderer=Renderer(self)
        self.renderer.image_object.connect(self.viewer.set_image);self.renderer.image_ready.connect(self.viewer.load)
        self.renderer.status.connect(self.status.setText);self.renderer.failed.connect(self.status.setText)
        self.renderer.buckets.connect(self.viewer.set_buckets)
        refresh.clicked.connect(self.refresh);stop.clicked.connect(self.renderer.stop)
        self.viewer.start_requested.connect(self.refresh)
        self.finished.connect(lambda *_:self.renderer.close())
    def refresh(self):
        try:
            import modo
            library={candidate.id:properties.read(candidate) for candidate in modo.Scene().items('advancedMaterial',superType=False)}
            draft=self.draft();library[self.item.id]=draft
            scene=snapshot(draft,library,self.parts.isChecked())
            settings=QtCore.QSettings('MoonRayForModo','NativePreview')
            runtime=native.default_runtime() or str(settings.value('runtime',''))
            self.renderer.submit(scene,runtime,384,384,2,.2,0)
        except Exception as exc:self.status.setText(str(exc))
    def closeEvent(self,event):
        self.renderer.close();super().closeEvent(event)


def show(item,draft,parent=None):
    # A parent-owned modeless dialog keeps the editor available for draft edits.
    old=getattr(parent,'_widget_preview',None)
    if old is not None:old.close()
    dialog=Dialog(item,draft,parent)
    if parent is not None:parent._widget_preview=dialog
    dialog.show();dialog.raise_()
    return dialog
