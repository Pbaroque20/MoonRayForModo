# python
"""Reproduce right-pane Metallic edit followed by enabling live preview in an isolated host."""
import json,os,sys,traceback,time,gc
from pathlib import Path
import lx,modo
from PySide2 import QtCore,QtGui,QtWidgets
ROOT=Path('C:/Users/Raphael Tobar/MoonRayForModo')
folder=ROOT/'test-results/metallic-0330-gc';folder.mkdir(parents=True,exist_ok=True)
log=folder/'progress.log';log.write_text('',encoding='utf-8')
def record(value):
    with log.open('a',encoding='utf-8') as f:f.write(str(value)+'\n');f.flush()
record('START '+str(os.getpid()))
from moonray_modo.preview_diagnostics import record as diagnostic
diagnostic('Graph-only mouse test')
from moonray_modo import nodes,properties,native
from moonray_modo.node_editor import Editor
native.default_runtime=lambda:str(ROOT/'runtime/xpu-compatibility-0327')
state={'pid':os.getpid(),'frames':0,'cycles':0,'passed':False}
editor=None

def finish(error=None):
    if state.get('finished'):return
    state['finished']=True
    if error:state['error']=str(error)
    record('FINISH '+str(state))
    (folder/'report.json').write_text(json.dumps(state,indent=2),encoding='utf-8')
    if editor:editor.close()
    QtCore.QTimer.singleShot(100,lambda:lx.eval('!app.quit'))

def edited_live():
    try:
        panel=editor.material_preview
        record("BEGIN EDIT")
        editor.items['surface'].setSelected(True)
        row=next(r for r in range(editor.table.rowCount()) if editor.table.item(r,0).text()=='metallic')
        cell=editor.table.item(row,1);editor.table.scrollToItem(cell)
        spin=editor.table.cellWidget(row,1)
        assert spin is not None
        spin.setFocus();spin.selectAll()
        for c in str((0.5,1.0,0.0)[state['cycles']%3]):
            for kind in (QtCore.QEvent.KeyPress,QtCore.QEvent.KeyRelease):
                QtWidgets.QApplication.sendEvent(spin.lineEdit(),QtGui.QKeyEvent(kind,ord(c),QtCore.Qt.NoModifier,c))
        record('EDITED pending metallic .5 cycle '+str(state['cycles']))
        record('AUDIT QT WRAPPERS BEFORE PREVIEW')
        import shiboken2
        record('Editor module '+sys.modules[Editor.__module__].__file__)
        was_enabled=gc.isenabled();gc.disable()
        objects=gc.get_objects()
        try:
            for obj in objects:
                cls=type(obj)
                if any(base.__module__.startswith(('PySide2','shiboken2')) for base in cls.__mro__):
                    record('TRAVERSE '+hex(id(obj))+' '+cls.__module__+'.'+cls.__name__)
                    refs=gc.get_referents(obj)
                    del refs
            record('QT WRAPPERS TRAVERSED')
        finally:
            del objects
            if was_enabled:gc.enable()
        record('CLICK PREVIEW WITH PENDING TEXT')
        viewer=editor.material_preview.viewer;point=QtCore.QPointF(viewer.rect().center())
        for kind in (QtCore.QEvent.MouseButtonPress,QtCore.QEvent.MouseButtonRelease):
            QtWidgets.QApplication.sendEvent(viewer,QtGui.QMouseEvent(kind,point,QtCore.Qt.LeftButton,QtCore.Qt.LeftButton,QtCore.Qt.NoModifier))
    except BaseException:finish(traceback.format_exc())

def received(image):state['frames']+=1;record('IMAGE '+str(state['frames']))
def completed(output):
    try:
        assert editor.graph['nodes']['surface']['parameters']['metallic']==.5
        assert state['frames']>0
        state['cycles']=1;state['passed']=True;QtCore.QTimer.singleShot(0,finish)
    except BaseException:finish(traceback.format_exc())

def attach():
    global editor
    try:
        editor=next(w for w in QtWidgets.QApplication.topLevelWidgets() if isinstance(w,Editor))
        record('ATTACHED MODAL EDITOR')
        editor.material_preview.renderer.image_object.connect(received)
        editor.material_preview.renderer.finished.connect(completed)
        editor.material_preview.renderer.status.connect(record)
        editor.material_preview.renderer.failed.connect(lambda message:finish('RENDER FAILED '+message))
        QtCore.QTimer.singleShot(500,edited_live)
    except BaseException:finish(traceback.format_exc())
try:
    lx.eval('item.create mesh');record('MESH')
    lx.eval('tool.set prim.sphere on');lx.eval('tool.doApply');lx.eval('tool.set prim.sphere off');record('SPHERE')
    lx.eval('select.type polygon')
    before={i.id for i in modo.Scene().items('advancedMaterial')}
    lx.eval('!poly.setMaterial {Graph Metallic Repro}');record('M MATERIAL ASSIGNED')
    material=next(i for i in modo.Scene().items('advancedMaterial') if i.id not in before)
    modo.Scene().select(material);lx.eval('moonray.material.addOverrideAbove');record('OVERRIDE ADDED')
    record('SELECTED '+str([(i.name,i.type) for i in modo.Scene().selected]))
    QtCore.QTimer.singleShot(1000,attach)
    QtCore.QTimer.singleShot(140000,lambda:finish('Timed out'))
    lx.eval('moonray.material.nodes')
    record('COMMAND RETURNED')
except BaseException:finish(traceback.format_exc())
