"""Searchable asset browser and undoable material preset handoff."""
import json
from pathlib import Path
from PySide2 import QtCore,QtGui,QtWidgets
from . import asset_library as library

class Browser(QtWidgets.QDialog):
 def __init__(self,parent=None):
  super().__init__(parent);self.setWindowTitle('MoonRay Asset Library');self.resize(850,620)
  self.settings=QtCore.QSettings('MoonRayForModo','AssetLibrary');self.roots=json.loads(str(self.settings.value('roots','[]')));self.rows=[];self.iterator=None
  layout=QtWidgets.QVBoxLayout(self);bar=QtWidgets.QHBoxLayout()
  self.search=QtWidgets.QLineEdit();self.search.setPlaceholderText('Search materials, models, scenes, textures…');bar.addWidget(self.search,1)
  self.category=QtWidgets.QComboBox();self.category.addItem('All categories');bar.addWidget(self.category);layout.addLayout(bar)
  self.list=QtWidgets.QTreeWidget();self.list.setHeaderLabels(['Asset','Category','Source']);self.list.setRootIsDecorated(False);self.list.setSortingEnabled(True);layout.addWidget(self.list,1)
  self.details=QtWidgets.QPlainTextEdit();self.details.setReadOnly(True);self.details.setMaximumHeight(135);layout.addWidget(self.details)
  actions=QtWidgets.QHBoxLayout();layout.addLayout(actions)
  self.apply=QtWidgets.QPushButton('Assign material to selected meshes');self.apply.clicked.connect(self.assign);actions.addWidget(self.apply)
  self.reveal=QtWidgets.QPushButton('Open folder / source');self.reveal.clicked.connect(self.open_source);actions.addWidget(self.reveal)
  self.import_model=QtWidgets.QPushButton('Import model');self.import_model.clicked.connect(self.import_asset);actions.addWidget(self.import_model)
  copy=QtWidgets.QPushButton('Copy path');copy.clicked.connect(self.copy_path);actions.addWidget(copy)
  row=QtWidgets.QHBoxLayout();layout.addLayout(row)
  for title,callback in [('Add asset folder…',self.add_folder),('Remove folder...',self.remove_folder),('Refresh',self.refresh),('Save selected material…',self.save_material)]:
   button=QtWidgets.QPushButton(title);button.clicked.connect(callback);row.addWidget(button)
  self.status=QtWidgets.QLabel();layout.addWidget(self.status)
  self.search.textChanged.connect(self.filter);self.category.currentTextChanged.connect(self.filter);self.list.itemSelectionChanged.connect(self.selection)
  self.timer=QtCore.QTimer(self);self.timer.setInterval(1);self.timer.timeout.connect(self.scan_next)
  self.refresh();self.selection()
 def refresh(self):
  self.timer.stop();self.list.clear();self.rows=[];self.category.clear();self.category.addItem('All categories')
  self.add_rows(library.builtins());self.iterator=library.scan([library.bundled()]+self.roots);self.timer.start();self.status.setText('Indexing local assets…')
 def add_rows(self,rows):
  self.list.setSortingEnabled(False)
  for row in rows:
   self.rows.append(row);item=QtWidgets.QTreeWidgetItem([row['name'],row['category'],row['source']]);item.setData(0,QtCore.Qt.UserRole,row);self.list.addTopLevelItem(item)
   if self.category.findText(row['category'])<0:self.category.addItem(row['category'])
  self.list.setSortingEnabled(True);self.filter()
 def scan_next(self):
  try:self.add_rows(next(self.iterator))
  except StopIteration:self.timer.stop();self.status.setText('%d assets · Native RDLA and USD examples are not automatically converted into Modo scenes.'%len(self.rows))
  except (OSError,ValueError) as exc:self.timer.stop();self.status.setText(str(exc))
 def filter(self,*args):
  query=self.search.text().casefold();category=self.category.currentText()
  for i in range(self.list.topLevelItemCount()):
   item=self.list.topLevelItem(i);row=item.data(0,QtCore.Qt.UserRole)
   item.setHidden(bool((category!='All categories' and category!=row['category']) or query not in (' '.join([row['name'],row['category'],row.get('description','')])).casefold()))
 def selected(self):
  items=self.list.selectedItems();return items[0].data(0,QtCore.Qt.UserRole) if items else {}
 def selection(self):
  row=self.selected();self.details.setPlainText('\n'.join([row.get('name',''),row.get('description',''),'License: '+row.get('license',''),'Source: '+row.get('source','')]))
  self.import_model.setEnabled(Path(row.get('path','')).suffix.lower() in ('.obj','.fbx'))
  self.apply.setEnabled(bool(row.get('shader') or row.get('category')=='Saved materials'));self.reveal.setEnabled(bool(row.get('path') or row.get('url')))
 def add_folder(self):
  folder=QtWidgets.QFileDialog.getExistingDirectory(self,'Add an asset folder')
  if folder and folder not in self.roots:self.roots.append(folder);self.settings.setValue('roots',json.dumps(self.roots));self.refresh()
 def remove_folder(self):
  if not self.roots:self.status.setText('No added folders to remove.');return
  folder,ok=QtWidgets.QInputDialog.getItem(self,'Remove library folder','Stop indexing this folder (files stay on disk):',self.roots,0,False)
  if ok and folder in self.roots:self.roots.remove(folder);self.settings.setValue('roots',json.dumps(self.roots));self.refresh()
 def open_source(self):
  row=self.selected()
  if row.get('url'):QtGui.QDesktopServices.openUrl(QtCore.QUrl(row['url']))
  elif row.get('path'):QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(Path(row['path']).parent)))
 def import_asset(self):
  try:
   import lx
   path=self.selected().get('path','')
   if Path(path).suffix.lower() not in ('.obj','.fbx') or not Path(path).is_file():raise ValueError('Select an existing OBJ or FBX model')
   if any(c in path for c in '{}\r\n'):raise ValueError('Rename the file to remove command delimiters before importing')
   lx.eval('scene.open {'+path+'} import')
   self.status.setText('Model imported into the current Modo scene.')
  except Exception as exc:self.status.setText(str(exc))
 def copy_path(self):QtWidgets.QApplication.clipboard().setText(self.selected().get('path',self.selected().get('url','')))
 def assign(self):
  try:
   from . import properties
   import lx
   row=self.selected();shader,parameters=library.read_preset(row['path']) if row.get('category')=='Saved materials' else (row['shader'],row['parameters'])
   payload=properties.encode({'shader':shader,'parameters':parameters});lx.eval('moonray.library.assign '+payload)
   self.status.setText('Material assigned. Its properties are available in the MoonShine panel.')
  except Exception as exc:self.status.setText(str(exc))
 def save_material(self):
  try:
   from . import materials,properties,shader_library
   selected=materials.selected()
   if len(selected)!=1:raise ValueError('Select one MoonShine material in the Shader Tree')
   values=properties.read(selected[0]);shader=values.get('native_shader')
   if not shader:raise ValueError('Choose a native MoonRay material type before saving a preset')
   if values.get('node_graph') or values.get('materialx_override'):raise ValueError('Graph presets need their dependencies. Export a MaterialX document from the node editor instead.')
   parameters=shader_library.validate(shader,values.get('native_parameters',{}))
   for key,value in parameters.items():
    if shader_library.catalog()[shader]['attributes'][key]['type'].startswith('SceneObject') and value is not None:raise ValueError('This material references other scene items; save a self-contained preset')
   path,_=QtWidgets.QFileDialog.getSaveFileName(self,'Save material preset',str(Path.home()/'MoonRayAssets'/ 'material.moonmat.json'),'MoonRay material (*.moonmat.json)')
   if not path:return
   if not path.endswith('.moonmat.json'):path+='.moonmat.json'
   target=Path(path);target.parent.mkdir(parents=True,exist_ok=True)
   target.write_text(json.dumps({'format':1,'name':selected[0].name,'shader':shader,'parameters':parameters},indent=2),encoding='utf-8')
   if str(target.parent) not in self.roots:self.roots.append(str(target.parent));self.settings.setValue('roots',json.dumps(self.roots))
   self.refresh()
  except Exception as exc:self.status.setText(str(exc))
 def closeEvent(self,event):self.timer.stop();super().closeEvent(event)

_dialog=None
def show(parent=None):
 global _dialog
 if _dialog is None:_dialog=Browser(parent)
 elif not _dialog.isVisible():_dialog.refresh()
 _dialog.show();_dialog.raise_();_dialog.activateWindow()
