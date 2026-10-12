# python
"""Exercise asynchronous native LPE validation, stale edits and cancellation in Modo."""
import json,os,tempfile,traceback,time
from pathlib import Path
import lx
from PySide2 import QtCore
out=Path(os.environ.get('MOONRAY_TEST_RESULTS',str(Path(tempfile.gettempdir())/'MoonRayForModo-tests')))/'native-lpe';out.mkdir(parents=True,exist_ok=True)
result={'ok':False,'steps':[]};stage=0;started=time.monotonic()
(out/'started.txt').write_text('script entered',encoding='utf-8')
def finish(error=None):
 timer.stop()
 if error:result['error']=error
 else:result['ok']=True
 dialog.reject();(out/'host-report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
 QtCore.QTimer.singleShot(100,lambda:lx.eval('!app.quit'))
def poll():
 global stage
 try:
  if time.monotonic()-started>90:raise RuntimeError('UI validation probe timed out')
  if dialog._native_job is not None:return
  if stage==0:
   assert '1 expression(s) rejected' in dialog.problem.text(),dialog.problem.text()
   assert 'rejected' in dialog.table.item(1,2).toolTip()
   result['steps'].append('native error marks the correct field')
   dialog.check_native();dialog.table.item(1,2).setText('C.*L');stage=1
  elif stage==1:
   assert 'Expressions changed' in dialog.problem.text(),dialog.problem.text()
   result['steps'].append('stale validation is discarded')
   dialog.check_native();dialog.reject()
   assert dialog._native_process is None or dialog._native_process.state()==QtCore.QProcess.NotRunning
   result['steps'].append('closing cancels the native process');finish()
 except Exception:finish(traceback.format_exc())
try:
 from moonray_modo import native
 from moonray_modo.outputs_dialog import OutputsDialog
 settings=QtCore.QSettings('MoonRayForModo',native.settings_name());settings.setValue('runtime',os.environ['MOONRAY_TEST_RUNTIME'])
 dialog=OutputsDialog([{'name':'valid','kind':'lpe','expression':'C.*L'},{'name':'invalid','kind':'lpe','expression':'C(L|)'}]);dialog.show()
 timer=QtCore.QTimer(dialog);timer.timeout.connect(poll);timer.start(100);dialog.check_native()
 (out/'started.txt').write_text('entering modal loop',encoding='utf-8')
 dialog.exec_()
except Exception:
 result['error']=traceback.format_exc();(out/'host-report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
 QtCore.QTimer.singleShot(100,lambda:lx.eval('!app.quit'))
