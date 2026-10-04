# python
"""Reproduce right-pane Metallic edit followed by enabling live preview in an isolated host."""
import json,os,sys,traceback,time
from pathlib import Path
import lx,modo
from PySide2 import QtCore,QtGui,QtWidgets
ROOT=Path('C:/Users/Raphael Tobar/MoonRayForModo')
folder=ROOT/'test-results/metallic-0327-installed-runtime';folder.mkdir(parents=True,exist_ok=True)
log=folder/'progress.log';log.write_text('',encoding='utf-8')
def record(value):
    with log.open('a',encoding='utf-8') as f:f.write(str(value)+'\n');f.flush()
record('START '+str(os.getpid()))
from moonray_modo import nodes,properties,native
from moonray_modo.node_editor import Editor
native.default_runtime=lambda:str(ROOT/'runtime/xpu-compatibility-0324')
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
        panel.live.setChecked(False)
        editor.items['surface'].setSelected(True)
        row=next(r for r in range(editor.table.rowCount()) if editor.table.item(r,0).text()=='metallic')
        cell=editor.table.item(row,1);editor.table.scrollToItem(cell);editor.table.editItem(cell)
        spin=editor.table.itemDelegateForColumn(1).active_editor
        assert spin is not None
        spin.setFocus();spin.selectAll()
        for c in '0.5':
            for kind in (QtCore.QEvent.KeyPress,QtCore.QEvent.KeyRelease):
                QtWidgets.QApplication.sendEvent(spin,QtGui.QKeyEvent(kind,ord(c),QtCore.Qt.NoModifier,c))
        record('EDITED pending metallic .5 cycle '+str(state['cycles']))
        panel.live.setFocus(QtCore.Qt.MouseFocusReason)
        center=QtCore.QPointF(panel.live.rect().center())
        for kind in (QtCore.QEvent.MouseButtonPress,QtCore.QEvent.MouseButtonRelease):
            QtWidgets.QApplication.sendEvent(panel.live,QtGui.QMouseEvent(kind,center,QtCore.Qt.LeftButton,QtCore.Qt.LeftButton,QtCore.Qt.NoModifier))
        assert panel.live.isChecked()
        record('LIVE ON')
    except BaseException:finish(traceback.format_exc())

def received(image):
    state['frames']+=1;record('IMAGE '+str(state['frames']))
    if state['frames']%2:return
    value=editor.graph['nodes']['surface'].get('parameters',{}).get('metallic')
    record('COMMITTED '+str(value))
    if value!=.5:finish('Metallic not committed');return
    state['cycles']+=1
    if state['cycles']>=3:
        state['passed']=True;QtCore.QTimer.singleShot(0,finish)
    else:QtCore.QTimer.singleShot(100,edited_live)
try:
    item=modo.Scene().addMaterial(name='Metallic crash reproduction')
    properties.write(item,{'node_graph':nodes.new(),'node_override':True})
    editor=Editor(item);editor.show();record('EDITOR SHOWN')
    editor.material_preview.renderer.status.connect(record)
    editor.material_preview.renderer.failed.connect(lambda message:finish('RENDER FAILED '+message))
    editor.material_preview.renderer.image_object.connect(received)
    QtCore.QTimer.singleShot(1000,edited_live)
    QtCore.QTimer.singleShot(120000,lambda:finish('Timed out'))
except BaseException:finish(traceback.format_exc())
