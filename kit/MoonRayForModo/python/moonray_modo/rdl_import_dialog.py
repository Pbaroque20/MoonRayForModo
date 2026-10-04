"""Asynchronous RDL decoding followed by an undoable editable scene import."""
import json
from pathlib import Path
from PySide2 import QtCore,QtWidgets
from . import native,rdl_import

class Dialog(QtWidgets.QDialog):
 def __init__(self,parent=None):
  super().__init__(parent);self.setWindowTitle('Import MoonRay RDL as editable objects');self.resize(700,500)
  self.data=None;self.output=bytearray();self.errors='';self.path=None
  layout=QtWidgets.QVBoxLayout(self)
  layout.addWidget(QtWidgets.QLabel('Convert supported RDL meshes, cameras, lights and MoonShine material graphs into the current Modo scene.'))
  self.report=QtWidgets.QPlainTextEdit();self.report.setReadOnly(True);layout.addWidget(self.report,1)
  row=QtWidgets.QHBoxLayout();layout.addLayout(row)
  self.choose=QtWidgets.QPushButton('Choose RDL scene…');self.choose.clicked.connect(lambda:self.load());row.addWidget(self.choose)
  self.import_button=QtWidgets.QPushButton('Import editable objects');self.import_button.setEnabled(False);self.import_button.clicked.connect(self.apply);row.addWidget(self.import_button)
  self.cancel=QtWidgets.QPushButton('Cancel loading');self.cancel.setEnabled(False);self.cancel.clicked.connect(self.abort);row.addWidget(self.cancel)
  self.process=QtCore.QProcess(self);self.process.readyReadStandardOutput.connect(self.read);self.process.readyReadStandardError.connect(self.read_error)
  self.process.finished.connect(self.finished);self.process.errorOccurred.connect(self.error)
 def load(self,path=None):
  if self.process.state()!=QtCore.QProcess.NotRunning:return
  if not path:path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Choose MoonRay scene','','MoonRay scenes (*.rdla *.rdlb *.rdl)')
  if not path:return
  try:
   self.path=Path(path).resolve()
   if not self.path.is_file() or self.path.suffix.lower() not in ('.rdla','.rdlb','.rdl'):raise ValueError('Choose an existing RDL scene')
   if self.path.suffix.lower()=='.rdl':raise ValueError('Use .rdla for an ASCII MoonRay scene or .rdlb for a binary MoonRay scene; generic .rdl is ambiguous.')
   settings=QtCore.QSettings('MoonRayForModo','NativePreview');runtime=native.find_runtime(str(settings.value('runtime',native.default_runtime())))
   helper=runtime/'modo_rdl_import.exe'
   if not helper.is_file():raise ValueError('Install the RDL-import runtime before importing')
   self.data=None;self.output.clear();self.errors='';self.import_button.setEnabled(False);self.choose.setEnabled(False);self.cancel.setEnabled(True)
   env=QtCore.QProcessEnvironment()
   for key,value in native.environment(runtime).items():env.insert(key,value)
   self.process.setProcessEnvironment(env);self.process.setWorkingDirectory(str(self.path.parent));self.process.setProgram(str(helper));self.process.setArguments([str(self.path),str(runtime)])
   self.report.setPlainText('Reading '+str(self.path)+'…');self.process.start()
  except Exception as exc:self.report.setPlainText(str(exc));self.choose.setEnabled(True);self.cancel.setEnabled(False)
 def read(self):
  self.output.extend(bytes(self.process.readAllStandardOutput()))
  if len(self.output)>256*1024*1024:self.abort();self.report.setPlainText('Scene exceeds the import transfer limit (256 MiB).')
 def read_error(self):self.errors=(self.errors+bytes(self.process.readAllStandardError()).decode('utf-8',errors='replace'))[-16384:]
 def error(self,value):
  if value==QtCore.QProcess.FailedToStart:self.report.setPlainText(self.process.errorString());self.choose.setEnabled(True);self.cancel.setEnabled(False)
 def finished(self,code,status):
  self.read();self.read_error();self.choose.setEnabled(True);self.cancel.setEnabled(False)
  try:
   if code or status!=QtCore.QProcess.NormalExit:raise ValueError(self.errors or 'RDL loading canceled or failed')
   marker=b'@@MODO_RDL_JSON\n';offset=self.output.rfind(marker)
   if offset<0:raise ValueError('Decoder returned no scene document')
   document=json.loads(bytes(self.output[offset+len(marker):]).decode('utf-8'));self.output.clear()
   self.data=rdl_import.plan(document,self.path)
   counts='%d meshes, %d cameras, %d lights, %d materials ready.'%(len(self.data['meshes']),len(self.data['cameras']),len(self.data['lights']),len(self.data['materials']))
   self.report.setPlainText(counts+'\n\n'+'\n'.join(self.data['warnings']))
   self.import_button.setEnabled(bool(self.data['meshes'] or self.data['cameras'] or self.data['lights'] or self.data['materials']))
  except Exception as exc:self.report.setPlainText('Cannot import: '+str(exc))
 def apply(self):
  if self.data is None:return
  try:
   import lx
   rdl_import.pending=self.data;lx.eval('moonray.rdl.apply')
   self.report.setPlainText(rdl_import.result);self.import_button.setEnabled(False)
  except Exception as exc:self.report.setPlainText('Import failed: '+str(exc))
  finally:rdl_import.pending=None
 def abort(self):
  if self.process.state()!=QtCore.QProcess.NotRunning:self.process.kill()
 def closeEvent(self,event):self.abort();super().closeEvent(event)

_dialog=None
def show(path=None):
 global _dialog
 if _dialog is None:_dialog=Dialog()
 _dialog.show();_dialog.raise_();_dialog.activateWindow()
 if path:_dialog.load(path)
