"""Isolated MoonRay Widget preview of draft native materials and node graphs."""
import collections
import copy
import hashlib
import json
import math
from pathlib import Path
from PySide2 import QtCore, QtGui, QtWidgets
from . import coordinates, native, nodes, options, shader_library
from .ipr import WIDGET_SAMPLES,widget_samples
from .rdla import IDENTITY
from .preview_diagnostics import record
from .render import Renderer
from .viewer import SoftwarePreview as Preview


# The widget's last finished pictures, kept while Modo runs: the same material, clay and runtime is shown again at once,
# with no render (reopening the editor, undoing an edit, going back to a clay). Twelve pictures of 384 pixels.
CACHE=collections.OrderedDict()
CACHE_SIZE=12


def cache_key(scene, runtime, width, height):
    text=json.dumps(scene,sort_keys=True,default=str)+'|%s|%d|%d'%(runtime,width,height)
    return hashlib.sha1(text.encode('utf-8')).hexdigest()


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
    # The camera looks a little below the middle, for the object to sit higher in the picture and not sink to its foot.
    return {'camera':{'identity':'widget/camera','matrix':look_at((2.5,1.4,3.8),(0,-.22,0)),
                      'focal_mm':55,'film_mm':36},
            'meshes':meshes,'materials':materials,'native_materials':library,'fps':24,
            'lights':[{'identity':'widget/key','kind':'RectLight','matrix':look_at((2,3,3)),
                       'color':[1,1,1],'intensity':3,'width':2,'height':2},
                      {'identity':'widget/rim','kind':'RectLight','matrix':look_at((-2,1,-2)),
                       'color':[1,1,1],'intensity':2,'width':2,'height':3}],
            'display':{'view':'srgb'},'render_settings':options.render_values({'target_adaptive_error':5.0})}


class WidgetPreview(Preview):
    """Trim empty upper margin only in the material widget's displayed image."""
    TOP_CROP=0.10

    @QtCore.Slot(object)
    def set_image(self,image):
        if not image.isNull():
            top=min(image.height()-1,int(image.height()*self.TOP_CROP))
            image=image.copy(0,top,image.width(),image.height()-top)
        super().set_image(image)


class Panel(QtWidgets.QWidget):
    def __init__(self,item,draft,parent=None,embedded=False):
        super().__init__(parent)
        self.item,self.draft=item,draft;self.closed=False;self.refreshing=False;self.last_signature=None
        self.embedded=embedded;self.warmed=False;self.rendering=None;self.picture=None;self.done=None
        layout=QtWidgets.QVBoxLayout(self);layout.setContentsMargins(4,4,4,4)
        layout.addWidget(QtWidgets.QLabel('MoonRay Widget'))
        bar=QtWidgets.QHBoxLayout();layout.addLayout(bar)
        self.live=QtWidgets.QCheckBox('Live material preview');self.live.setChecked(False);self.live.setVisible(embedded);bar.addWidget(self.live)
        # One button: Refresh, or Stop while the widget renders.
        self.button=QtWidgets.QPushButton('Refresh');bar.addWidget(self.button)
        self.button.setAutoDefault(False);self.button.setDefault(False)
        self.parts=QtWidgets.QCheckBox('Apply material to base and stand');layout.addWidget(self.parts)
        from .clay import CHOICES
        self.clay_mode=QtWidgets.QComboBox()
        for label,key in CHOICES:self.clay_mode.addItem(label,key)
        self.clay_mode.setToolTip('Preview only: show the material graph, terracotta clay or gray clay.')
        self.samples=QtWidgets.QComboBox()
        for key,label,*_ in WIDGET_SAMPLES:self.samples.addItem(label,key)
        stored=self.samples.findData(QtCore.QSettings('MoonRayForModo','GraphEditor').value('widget_samples','standard'))
        self.samples.setCurrentIndex(stored if stored>=0 else self.samples.findData('standard'))
        self.samples.setToolTip('Preview only: the most samples a pixel of the widget takes, and how clean it renders. More is cleaner and slower; clean parts still stop early. Live takes far fewer, to keep up.')
        choices=QtWidgets.QHBoxLayout();choices.addWidget(self.clay_mode,1);choices.addWidget(self.samples);layout.addLayout(choices)

        self.viewer=WidgetPreview(self);layout.addWidget(self.viewer,1)
        self.status=QtWidgets.QLabel('Live preview is off. Enable it or click Refresh.');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.setToolTip('Previews the current draft with widget UVs and studio lighting. Scene masks, projectors and hair geometry are not recreated. Live preview updates committed graph edits after a short pause.')
        credit=QtWidgets.QLabel('MoonRay Widget Copyright 2023–2025 DreamWorks Animation LLC. All rights reserved.\nASWF Digital Assets License v1.1');credit.setWordWrap(True);layout.addWidget(credit)
        self.renderer=Renderer(self)
        self.renderer.image_object.connect(self.viewer.set_image);self.renderer.image_ready.connect(self.viewer.load)
        self.renderer.status.connect(self.status.setText);self.renderer.failed.connect(self.preview_failed)
        # The widget shows its picture with no bucket outlines over it.
        self.renderer.image_object.connect(self.keep);self.renderer.image_ready.connect(lambda path:self.keep(QtGui.QImage(path)))
        self.renderer.finished.connect(self.cache);self.renderer.failed.connect(lambda *_:self.idle())
        self.renderer.stopped.connect(self.idle)
        self.timer=QtCore.QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(650);self.timer.timeout.connect(self.refresh)
        self.live.toggled.connect(self.live_changed)
        self.parts.toggled.connect(lambda *_:self.schedule())
        self.clay_mode.currentIndexChanged.connect(self.refresh,QtCore.Qt.QueuedConnection)
        self.samples.currentIndexChanged.connect(self.samples_changed,QtCore.Qt.QueuedConnection)
        self.button.clicked.connect(self.pressed)
        self.viewer.start_requested.connect(self.refresh,QtCore.Qt.QueuedConnection)
    def showEvent(self,event):
        super().showEvent(event)
        # Opened in the graph editor, the widget starts its picture at once, a moment after the editor is up: MoonRay
        # is loaded and the picture ready (or taken from the cache) before it is asked for.
        if self.embedded and not self.warmed:
            self.warmed=True;QtCore.QTimer.singleShot(300,self.refresh)
    def pressed(self):
        if self.rendering:self.stop()
        else:QtCore.QTimer.singleShot(0,self.refresh)
    def idle(self):
        self.rendering=None
        if not self.closed:self.button.setText('Refresh')
    def keep(self,image):
        if image.isNull():return
        if self.rendering:self.picture=image.copy()
        # The last picture can be converted after the render said it was done: it is the one kept.
        elif self.done in CACHE:CACHE[self.done]=image.copy()
    def cache(self,*args):
        # "Rendered." only where this render's picture came, and that picture is the one shown: a finish with none
        # (an earlier render's, or one that ended without a picture) says so rather than claim the old one is new.
        if self.rendering and self.picture is not None:
            CACHE[self.rendering]=self.picture;CACHE.move_to_end(self.rendering);self.done=self.rendering
            while len(CACHE)>CACHE_SIZE:CACHE.popitem(last=False)
            if not self.closed:
                self.viewer.set_image(self.picture);self.status.setText('Rendered.')
        elif self.rendering and not self.closed:
            self.status.setText('The render ended without a new picture. Click Refresh to render it again.')
        self.picture=None;self.idle()
    def preview_failed(self,message):
        if not self.closed:self.status.setText('Preview failed: '+message)
    def live_changed(self,enabled):
        record("Live preview "+("enabled" if enabled else "disabled"))
        if enabled:self.schedule()
        else:
            self.timer.stop();self.renderer.stop();self.status.setText('Live preview off. Last image retained.')
    def samples_changed(self,*_):
        QtCore.QSettings('MoonRayForModo','GraphEditor').setValue('widget_samples',self.samples.currentData())
        self.refresh()
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
        self.timer.stop();self.idle();self.done=None
        if self.live.isChecked():self.live.setChecked(False)
        else:self.renderer.stop()
    def capture_snapshot(self):
        import modo
        from .host import material_values
        library={candidate.id:material_values(candidate) for candidate in modo.Scene().items('advancedMaterial',superType=True)}
        draft=material_values(self.item);draft.update(self.draft());library[self.item.id]=draft
        return dict(snapshot(draft,library,self.parts.isChecked()),_clay_preview=self.clay_mode.currentData())

    @QtCore.Slot()
    def refresh(self):
        if self.closed or self.refreshing:return
        from .interaction import dragging
        if dragging():self.timer.start(80);return
        self.timer.setInterval(650)
        self.refreshing=True
        try:
            record("Capture draft begin")
            scene=self.capture_snapshot()
            record("Capture draft complete")
            self.timer.stop()  # Draft commit can itself notify graph_changed.
            # MoonRay LS, as the render window's quick look, with the samples chosen under the picture and an adaptive
            # error that stops once the picture is clean, to load fast. Live, while values are being dragged, it is held
            # lighter to keep up.
            live=self.live.isChecked()
            size=256 if live else 384
            samples,error=widget_samples(self.samples.currentData(),live)
            # The fewest as MoonRay LS takes them (2): the scene's own fewest (16 by default) is more than Live's most.
            scene['render_settings'].update(sampling_mode=2,min_adaptive_samples=2,max_adaptive_samples=samples,target_adaptive_error=error)
            scene=dict(scene,width=size,height=size)
            from .ipr import prepare
            scene,width,height=prepare(scene,size,size,1,640,samples,error)
            scene['_pixel_samples']=samples
            # Rendered by MoonRay on the processor where XPU2 would take it: XPU2 reads a texture at a coarser level,
            # and on the widget's small ball an image came out as its average colour. The ball is small enough for
            # MoonRay to render quickly.
            if native.xpu2():scene['execution_mode']='vectorized'
            # The runtime the preview window renders with, chosen in Preferences (the kit's own where none is).
            from .preferences import Preferences
            runtime=Preferences().get('runtime') or native.default_runtime()
            key=cache_key(scene,runtime,width,height)
            if key in CACHE:
                if self.rendering:self.renderer.stop()
                self.idle();self.done=None;CACHE.move_to_end(key)
                self.viewer.set_image(CACHE[key]);self.status.setText('Shown from the cache: nothing changed since it was rendered.')
                return
            record("Submit material preview; runtime="+str(runtime))
            self.rendering=key;self.picture=None;self.done=None;self.button.setText('Stop')
            self.renderer.submit(scene,runtime,width,height,1,.2,0)
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
                            (self.renderer.failed,self.preview_failed)):
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
