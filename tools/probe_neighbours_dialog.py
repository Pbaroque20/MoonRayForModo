# python
"""Exercise the real Subsurface Neighbours command in an isolated Modo 16.1v9 profile.
Creates disposable items; verifies accept, reopen, cancel, clear and multi-material application.
Writes JSON and a dialog screenshot; never renders or saves a scene.
"""
import json,os,tempfile,traceback
from pathlib import Path
import lx,modo
from PySide2 import QtCore,QtWidgets,QtGui
from moonray_modo import properties
out=Path(os.environ.get('MOONRAY_TEST_RESULTS',str(Path(tempfile.gettempdir())/'MoonRayForModo-tests')))/'neighbours-dialog'
out.mkdir(parents=True,exist_ok=True)
result={'ok':False,'steps':[]}
def edit(chosen,expected,accept=True):
    errors=[];visited=[]
    def operate():
        dialog=QtWidgets.QApplication.activeModalWidget()
        try:
            assert dialog and dialog.windowTitle()=='Subsurface neighbours','Expected neighbours dialog'
            listed=dialog.findChild(QtWidgets.QListWidget)
            rows=[listed.item(i) for i in range(listed.count())]
            present={r.data(QtCore.Qt.UserRole) for r in rows}
            assert set(chosen)<=present,'Mesh missing from picker'
            checked={r.data(QtCore.Qt.UserRole) for r in rows if r.checkState()==QtCore.Qt.Checked}
            assert checked==set(expected),(checked,expected)
            for row in rows:row.setCheckState(QtCore.Qt.Checked if row.data(QtCore.Qt.UserRole) in chosen else QtCore.Qt.Unchecked)
            # Click a checkbox through Qt's mouse event path, then restore it.
            row=rows[0];before=row.checkState();rect=listed.visualItemRect(row)
            point=QtCore.QPoint(rect.left()+8,rect.center().y())
            for kind,buttons_down in ((QtCore.QEvent.MouseButtonPress,QtCore.Qt.LeftButton),(QtCore.QEvent.MouseButtonRelease,QtCore.Qt.NoButton)):
                QtWidgets.QApplication.sendEvent(listed.viewport(),QtGui.QMouseEvent(kind,QtCore.QPointF(point),QtCore.Qt.LeftButton,buttons_down,QtCore.Qt.NoModifier))
            assert row.checkState()!=before,'Click did not toggle membership'
            for kind,buttons_down in ((QtCore.QEvent.MouseButtonPress,QtCore.Qt.LeftButton),(QtCore.QEvent.MouseButtonRelease,QtCore.Qt.NoButton)):
                QtWidgets.QApplication.sendEvent(listed.viewport(),QtGui.QMouseEvent(kind,QtCore.QPointF(point),QtCore.Qt.LeftButton,buttons_down,QtCore.Qt.NoModifier))
            assert row.checkState()==before,'Second click did not restore membership'
            assert dialog.grab().save(str(out/('dialog-%d.png'%len(result['steps']))))
            buttons=dialog.findChild(QtWidgets.QDialogButtonBox)
            visited.append(True)
            buttons.button(QtWidgets.QDialogButtonBox.Ok if accept else QtWidgets.QDialogButtonBox.Cancel).click()
        except Exception:
            errors.append(traceback.format_exc())
            if dialog:dialog.reject()
    QtCore.QTimer.singleShot(200,operate)
    lx.eval('moonray.material.neighbours')
    assert visited and not errors,errors or 'Dialog was not shown'
try:
    lx.eval('scene.new')
    scene=modo.Scene()
    meshes=[scene.addItem('mesh') for _ in range(2)]
    meshes[0].name='Neighbour A';meshes[1].name='Neighbour B'
    mats=[scene.addItem('advancedMaterial') for _ in range(2)]
    for item in mats:properties.write(item,{'native_shader':'DwaBaseMaterial','native_parameters':{},'enabled':True})
    scene.select(mats[0])
    ids=[m.id for m in meshes]
    edit(ids,[])
    assert set(properties.read(mats[0]).get('sss_trace_set',[]))==set(ids)
    result['steps'].append('accept stores mesh IDs')
    edit([],ids,False)
    assert set(properties.read(mats[0]).get('sss_trace_set',[]))==set(ids)
    result['steps'].append('reopen restores checks; cancel preserves IDs')
    scene.select(mats)
    edit(ids[:1],ids)
    assert all(properties.read(m).get('sss_trace_set')==ids[:1] for m in mats)
    result['steps'].append('selection applies to both materials')
    edit([],ids[:1])
    assert all('sss_trace_set' not in properties.read(m) for m in mats)
    result['steps'].append('clear removes trace set from both materials')
    result['ok']=True
except Exception:result['error']=traceback.format_exc()
finally:
    (out/'report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    QtCore.QTimer.singleShot(100,lambda:lx.eval('!app.quit'))
