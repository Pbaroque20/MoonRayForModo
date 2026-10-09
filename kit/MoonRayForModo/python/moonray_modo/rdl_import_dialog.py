"""Asynchronous RDL decoding followed by an undoable editable scene import."""
import json,re
from pathlib import Path
from PySide2 import QtCore,QtWidgets
from . import native,rdl_import

class Dialog(QtWidgets.QDialog):
 def __init__(self,parent=None):
  super().__init__(parent);self.setWindowTitle('Import MoonRay RDL as editable objects');self.resize(700,500)
  self.data=None;self.output=bytearray();self.errors='';self.path=None
  layout=QtWidgets.QVBoxLayout(self)
  layout.addWidget(QtWidgets.QLabel('Bring a MoonRay scene into the current Modo scene: meshes, instances and curves as Modo items, materials as MoonRay materials,\n'
   'and lights, light filters, volumes and other MoonRay objects as MoonRay items. What cannot be held is listed before anything is made.'))
  self.report=QtWidgets.QPlainTextEdit();self.report.setReadOnly(True);layout.addWidget(self.report,1)
  self.alone=QtWidgets.QCheckBox('Light it only as the RDL scene is lit');self.alone.setChecked(True)
  self.alone.setToolTip("Sets the lights already in the Modo scene not to render and keeps Modo's environment out of MoonRay's picture,\nso that the imported scene renders as it did. Off, the scene's lights are added to what is there.")
  layout.addWidget(self.alone)
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
   settings=QtCore.QSettings('MoonRayForModo','NativePreview');runtime=native.configured_runtime(settings)
   helper=runtime/'modo_rdl_import.exe'
   if not helper.is_file():raise ValueError('Install the RDL-import runtime before importing')
   self.data=None;self.output.clear();self.errors='';self.import_button.setEnabled(False);self.choose.setEnabled(False);self.cancel.setEnabled(True)
   env=QtCore.QProcessEnvironment()
   for key,value in native.environment(runtime).items():env.insert(key,value)
   self.process.setProcessEnvironment(env);self.process.setWorkingDirectory(str(self.path.parent));self.process.setProgram(str(helper));together=rdl_import.files(self.path);self.process.setArguments([together[0],str(runtime)]+together[1:])
   self.report.setPlainText('Reading '+' and '.join(Path(p).name for p in together)+' in '+str(self.path.parent)+'…');self.process.start()
  except Exception as exc:self.report.setPlainText(str(exc));self.choose.setEnabled(True);self.cancel.setEnabled(False)
 def read(self):
  self.output.extend(bytes(self.process.readAllStandardOutput()))
  # As text a scene is three to four times the size of its binary file; a scene of a few hundred megabytes fits.
  if len(self.output)>2048*1024*1024:self.abort();self.report.setPlainText('Scene exceeds the import transfer limit (2 GiB as text).')
 def read_error(self):self.errors=(self.errors+bytes(self.process.readAllStandardError()).decode('utf-8',errors='replace'))[-16384:]
 def error(self,value):
  if value==QtCore.QProcess.FailedToStart:self.report.setPlainText(self.process.errorString());self.choose.setEnabled(True);self.cancel.setEnabled(False)
 def finished(self,code,status):
  self.read();self.read_error();self.choose.setEnabled(True);self.cancel.setEnabled(False)
  try:
   if code or status!=QtCore.QProcess.NormalExit:raise ValueError(self.errors or 'RDL loading canceled or failed')
   marker=b'@@MODO_RDL_JSON';offset=self.output.rfind(marker)
   if offset<0:raise ValueError('Decoder returned no scene document')
   document=json.loads(bytes(self.output[offset+len(marker):]).decode('utf-8'));self.output.clear()
   self.data=rdl_import.plan(document,self.path)
   counts=rdl_import.summary(self.data);counts=counts[:1].upper()+counts[1:]+' ready.'
   self.report.setPlainText(counts+'\n\n'+'\n'.join(self.data['warnings']))
   self.import_button.setEnabled(not rdl_import.empty(self.data))
  except Exception as exc:
   message=str(exc)
   missing=re.search(r"global variable '([^']+)' was never declared",message)
   if missing and 'DSO' in message:
    message=('The scene requires '+missing.group(1)+', which could not be loaded from the selected MoonRay runtime. '
     'Choose the updated bundled runtime in MoonRay settings. Third-party geometry or shader plugins require a compatible Windows build.\n\n'+message)
   self.report.setPlainText('Cannot import: '+message)
 def apply(self):
  if self.data is None:return
  try:
   import lx
   rdl_import.pending=dict(self.data,alone=self.alone.isChecked());lx.eval('moonray.rdl.apply')
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
