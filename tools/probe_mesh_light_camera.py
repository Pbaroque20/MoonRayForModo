# python
"""Verify the native emitter camera mode control saves and restores in Modo."""
import json,os,tempfile,traceback
from pathlib import Path
import lx,modo
from PySide2 import QtCore,QtWidgets
from moonray_modo.production_dialog import Controls
out=Path(os.environ.get('MOONRAY_TEST_RESULTS',str(Path(tempfile.gettempdir())/'MoonRayForModo-tests')))/'mesh-light-camera';out.mkdir(parents=True,exist_ok=True)
result={'ok':False}
try:
 lx.eval('scene.new');mesh=modo.Scene().addItem('mesh',name='Emitter test')
 dialog=Controls({'objects':{mesh.id:{'mesh_light':True}}});dialog.show();QtWidgets.QApplication.processEvents()
 dialog.selectors['objects'].setCurrentIndex(dialog.selectors['objects'].findData(mesh.id))
 field=dialog.fields['objects']['mesh_camera_mode'][0]
 assert field.currentData()=='auto'
 field.setCurrentIndex(field.findData('hidden'));dialog._accept()
 assert dialog.values['objects'][mesh.id]['mesh_camera_mode']=='hidden'
 reopened=Controls(dialog.values);reopened.selectors['objects'].setCurrentIndex(reopened.selectors['objects'].findData(mesh.id))
 assert reopened.fields['objects']['mesh_camera_mode'][0].currentData()=='hidden'
 reopened.reject();result['ok']=True
except Exception:result['error']=traceback.format_exc()
finally:
 (out/'host-report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
 QtCore.QTimer.singleShot(100,lambda:lx.eval('!app.quit'))
