"""The asset library: what can be put to use in a scene, shown as pictures, each with the one thing it is for."""
import json
from pathlib import Path
from PySide2 import QtCore,QtGui,QtWidgets
from . import asset_library as library

# What each kind of asset is for, in the words of the button that does it, and a line saying so. An asset with no
# purpose here is not listed: the library is for things to use, not for a catalogue of what MoonRay contains.
PURPOSES={'Assign material':('Assign to Selected Meshes','A saved material. Select one or more meshes, then assign it; it can be edited afterwards in the material\'s properties.'),
          'Import scene / model':('Bring into the Scene','A model or scene file. It is brought into the scene that is open, with Modo\'s own reader for its format.'),
          'Import image clip':('Add to the Scene\'s Images','A picture. It is added to the scene\'s images, ready to be chosen for a material\'s input or an environment.'),
          'Use display LUT':('Use as the Display LUT','A colour table. The preview is shown through it.'),
          'Import MaterialX override':('Bring in as a Material','A MaterialX material. It is brought in with its graph and its images.'),
          'Add VDB volume':('Add as a Volume','A volume file: smoke, cloud or fire. A MoonRay volume item is made for it.'),
          'Import RDL scene':('Open in the Import Dialog','A MoonRay scene. The import dialog opens on it, to choose what comes in.')}
SIZE=112
# The colour a file type's tile is drawn in, where it has no picture of its own.
TILES={'Models':'#5b7fa6','Modo scenes':'#5b7fa6','USD / models':'#4f8f8a','Example scenes':'#7a6aa8','Volumes':'#8a8f98','MaterialX':'#a8794f','Color / LUT':'#a35d7c','Textures / environments':'#6d8f55'}
PICTURES=('.png','.jpg','.jpeg','.tif','.tiff','.bmp','.tga')


def ball(colour,metal=0.0,rough=.4,clear=0.0,size=SIZE):
    """A shaded ball of a material's colour: dull or shiny, metal or not, clear or solid. A drawing, not a render."""
    image=QtGui.QImage(size,size,QtGui.QImage.Format_ARGB32);image.fill(QtCore.Qt.transparent)
    painter=QtGui.QPainter(image)
    try:
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        area=QtCore.QRectF(size*.08,size*.08,size*.84,size*.84)
        base=QtGui.QColor.fromRgbF(*[min(1.0,max(0.0,float(c))) for c in colour[:3]])
        shade=QtGui.QRadialGradient(area.center()+QtCore.QPointF(-size*.16,-size*.2),size*.62)
        lit=base.lighter(135 if not metal else 160);dark=base.darker(260 if not metal else 420)
        if clear>0:
            lit.setAlphaF(.75);base.setAlphaF(max(.25,1-.7*clear));dark.setAlphaF(.8)
        shade.setColorAt(0.0,lit);shade.setColorAt(.55,base);shade.setColorAt(1.0,dark)
        painter.setPen(QtCore.Qt.NoPen);painter.setBrush(shade);painter.drawEllipse(area)
        # The highlight: small and bright on a smooth surface, wide and faint on a rough one.
        wide=size*(.07+.3*min(1.0,max(0.0,rough)))
        spot=QtGui.QRadialGradient(area.center()+QtCore.QPointF(-size*.17,-size*.21),wide)
        glint=QtGui.QColor(255,255,255) if not metal else base.lighter(190)
        glint.setAlphaF(max(.12,.95-.8*min(1.0,max(0.0,rough))));spot.setColorAt(0.0,glint)
        fade=QtGui.QColor(glint);fade.setAlphaF(0.0);spot.setColorAt(1.0,fade)
        painter.setBrush(spot);painter.drawEllipse(area)
    finally:painter.end()
    return image


def tile(letters,colour,size=SIZE):
    """A plain tile with a file type's letters on it."""
    image=QtGui.QImage(size,size,QtGui.QImage.Format_ARGB32);image.fill(QtCore.Qt.transparent)
    painter=QtGui.QPainter(image)
    try:
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setPen(QtCore.Qt.NoPen);painter.setBrush(QtGui.QColor(colour))
        painter.drawRoundedRect(QtCore.QRectF(size*.12,size*.12,size*.76,size*.76),size*.08,size*.08)
        font=painter.font();font.setBold(True);font.setPixelSize(int(size*.2));painter.setFont(font)
        painter.setPen(QtGui.QColor(255,255,255,230));painter.drawText(image.rect(),QtCore.Qt.AlignCenter,letters)
    finally:painter.end()
    return image


def picture(row,size=SIZE):
    """What stands for an asset: the picture itself, a picture kept beside the file under the same name, a ball in a
    saved material's colour, or a tile with the file type on it."""
    path=Path(row.get('path',''))
    try:
        if str(path).lower().endswith('.moonmat.json'):
            held=json.loads(path.read_text(encoding='utf-8')) if path.stat().st_size<2*1024*1024 else {}
            values=held.get('parameters') or {};shader=str(held.get('shader',''))
            metal='Metal' in shader or float(values.get('metallic',0) or 0)>.5
            colour=next((values[k] for k in ('metallic_color','albedo','color','transmission_color','diffuse_color') if isinstance(values.get(k),(list,tuple))),[.75,.75,.75])
            clear=float(values.get('transmission',1.0 if 'Refractive' in shader else 0.0) or 0.0)
            return ball(colour,metal,float(values.get('roughness',.4) or 0.0),clear,size)
        beside=[path]+[path.with_suffix(ext) for ext in ('.png','.jpg','.jpeg')] if path.suffix.lower() in PICTURES else [path.with_suffix(ext) for ext in ('.png','.jpg','.jpeg')]
        for candidate in beside:
            if candidate.suffix.lower() in PICTURES and candidate.is_file() and candidate.stat().st_size<64*1024*1024:
                reader=QtGui.QImageReader(str(candidate));full=reader.size()
                if full.isValid() and full.width()>0:
                    reader.setScaledSize(full.scaled(size,size,QtCore.Qt.KeepAspectRatio))
                found=reader.read()
                if not found.isNull():
                    return found
    except (OSError,ValueError,TypeError):pass
    return tile(path.suffix.lstrip('.').upper()[:4] or '?',TILES.get(row.get('category',''),'#70747c'),size)


class Browser(QtWidgets.QDialog):
 def __init__(self,parent=None):
  super().__init__(parent);self.setWindowTitle('MoonRay Asset Library');self.resize(980,640)
  self.settings=QtCore.QSettings('MoonRayForModo','AssetLibrary');self.roots=json.loads(str(self.settings.value('roots','[]')));self.rows=[];self.iterator=None;self.waiting=[]
  layout=QtWidgets.QVBoxLayout(self)
  self.search=QtWidgets.QLineEdit();self.search.setPlaceholderText('Search by name');self.search.setClearButtonEnabled(True);layout.addWidget(self.search)
  middle=QtWidgets.QHBoxLayout();layout.addLayout(middle,1)
  # The kinds of asset, at the left; the assets of the kind chosen, as pictures; and what is chosen, at the right.
  self.category=QtWidgets.QListWidget();self.category.setFixedWidth(170);middle.addWidget(self.category)
  self.list=QtWidgets.QListWidget();self.list.setViewMode(QtWidgets.QListView.IconMode);self.list.setIconSize(QtCore.QSize(SIZE,SIZE))
  self.list.setGridSize(QtCore.QSize(SIZE+24,SIZE+40));self.list.setResizeMode(QtWidgets.QListView.Adjust);self.list.setMovement(QtWidgets.QListView.Static)
  self.list.setWordWrap(True);self.list.setSpacing(4);middle.addWidget(self.list,1)
  # Modo's own lists are light; pictures are judged better on the dark of its viewports.
  dark='QListWidget { background-color: #2f3136; color: #d8dae0; border: 1px solid #1b1c20; } QListWidget::item { padding: 3px; color: #d8dae0; } QListWidget::item:selected { background-color: #4b6ea8; color: #ffffff; }'
  self.list.setStyleSheet(dark);self.category.setStyleSheet(dark)
  side=QtWidgets.QVBoxLayout();middle.addLayout(side)
  self.shown=QtWidgets.QLabel();self.shown.setFixedSize(230,230);self.shown.setAlignment(QtCore.Qt.AlignCenter);self.shown.setStyleSheet('background-color: #2a2c31; border: 1px solid #1b1c20;');side.addWidget(self.shown)
  self.title=QtWidgets.QLabel();self.title.setWordWrap(True);self.title.setStyleSheet('font-weight: bold;');side.addWidget(self.title)
  self.details=QtWidgets.QLabel();self.details.setWordWrap(True);self.details.setFixedWidth(230);self.details.setAlignment(QtCore.Qt.AlignTop);side.addWidget(self.details,1)
  # The one thing the chosen asset is for.
  self.use=QtWidgets.QPushButton('Use');self.use.setMinimumHeight(32);self.use.clicked.connect(self.put_to_use);side.addWidget(self.use)
  self.reveal=QtWidgets.QPushButton('Show in Folder');self.reveal.clicked.connect(self.open_source);side.addWidget(self.reveal)
  row=QtWidgets.QHBoxLayout();layout.addLayout(row)
  for title,callback,tip in [('Add Folder...',self.add_folder,'Show the assets of a folder of your own here: materials you have saved, models, scenes, pictures'),
                             ('Remove Folder...',self.remove_folder,'Stop showing a folder that was added. Its files stay where they are'),('Refresh',self.refresh,'Look through the folders again')]:
   button=QtWidgets.QPushButton(title);button.setToolTip(tip);button.clicked.connect(callback);row.addWidget(button)
  row.addStretch(1)
  save=QtWidgets.QPushButton('Save Selected Material...');save.setToolTip('Save the MoonRay material selected in the Shader Tree into the library, to use again in other scenes')
  menu=QtWidgets.QMenu(save);menu.addAction('Its Settings Only...',self.save_material);menu.addAction('With Its Graph and Images...',self.save_bundle);save.setMenu(menu);row.addWidget(save)
  more=QtWidgets.QPushButton('More Scenes Online...');more.setToolTip('MoonRay\'s example scenes to download. Add the folder they are unpacked into, and they are shown here')
  more.clicked.connect(lambda:QtGui.QDesktopServices.openUrl(QtCore.QUrl(library.SOURCE)));row.addWidget(more)
  self.status=QtWidgets.QLabel();layout.addWidget(self.status)
  self.search.textChanged.connect(self.filter);self.category.currentRowChanged.connect(self.filter);self.list.itemSelectionChanged.connect(self.selection)
  self.list.itemDoubleClicked.connect(lambda item:self.put_to_use())
  self.timer=QtCore.QTimer(self);self.timer.setInterval(1);self.timer.timeout.connect(self.scan_next)
  # Pictures are made a few at a time after the names are up, so that a large folder does not hold the window.
  self.painter=QtCore.QTimer(self);self.painter.setInterval(1);self.painter.timeout.connect(self.paint_next)
  # What stands in a place until its picture is made.
  empty=QtGui.QPixmap(SIZE,SIZE);empty.fill(QtCore.Qt.transparent);self.blank=QtGui.QIcon(empty)
  self.refresh();self.selection()
 def refresh(self):
  self.timer.stop();self.painter.stop();self.list.clear();self.rows=[];self.waiting=[]
  self.category.blockSignals(True);self.category.clear();self.category.addItem('Everything');self.category.setCurrentRow(0);self.category.blockSignals(False)
  # The kit's own library holds what came with it, the example scenes of the content download among it.
  self.iterator=library.scan([library.bundled()]+self.roots);self.timer.start();self.status.setText('Looking through the library...')
 def add_rows(self,rows):
  from .asset_import import action
  for row in rows:
   # Only what there is something to do with.
   if not action(row.get('path','')) in PURPOSES:continue
   # A MoonRay scene is two files of one name that belong together: it is shown once, by the one that is read last.
   held=Path(row.get('path',''))
   if held.suffix.lower()=='.rdlb' and held.with_suffix('.rdla').is_file():continue
   # And where every scene's file is called scene, each in a folder of its own, it is called by its folder.
   if row['name'].casefold() in ('scene','main','untitled'):row=dict(row,name=held.parent.name.replace('_',' ').replace('-',' ').capitalize())
   # A saved material is called by its name, without the ending its file has.
   if row['name'].endswith('.moonmat'):row=dict(row,name=row['name'][:-len('.moonmat')])
   self.rows.append(row);item=QtWidgets.QListWidgetItem(row['name']);item.setData(QtCore.Qt.UserRole,row);item.setToolTip(row.get('path',''))
   item.setSizeHint(QtCore.QSize(SIZE+24,SIZE+40));item.setIcon(self.blank)
   item.setTextAlignment(QtCore.Qt.AlignHCenter|QtCore.Qt.AlignTop);self.list.addItem(item);self.waiting.append(item)
   if not self.category.findItems(row['category'],QtCore.Qt.MatchExactly):self.category.addItem(row['category'])
  self.filter()
  if self.waiting and not self.painter.isActive():self.painter.start()
 def scan_next(self):
  try:self.add_rows(next(self.iterator))
  except StopIteration:
   self.timer.stop();self.status.setText('%d assets. Double-click one to use it, or add a folder of your own.'%len(self.rows))
  except (OSError,ValueError) as exc:self.timer.stop();self.status.setText(str(exc))
 def paint_next(self):
  for _ in range(4):
   if not self.waiting:self.painter.stop();return
   item=self.waiting.pop(0)
   try:
    # The same picture whether chosen or not: left to itself, Qt washes a chosen one over with the highlight.
    made=QtGui.QPixmap.fromImage(picture(item.data(QtCore.Qt.UserRole)));icon=QtGui.QIcon(made);icon.addPixmap(made,QtGui.QIcon.Selected);item.setIcon(icon)
   except RuntimeError:pass
 def filter(self,*args):
  query=self.search.text().casefold();chosen=self.category.currentItem();category=chosen.text() if chosen is not None else 'Everything'
  for i in range(self.list.count()):
   item=self.list.item(i);row=item.data(QtCore.Qt.UserRole)
   item.setHidden(bool((category!='Everything' and category!=row['category']) or query not in (' '.join([row['name'],row['category'],row.get('description','')])).casefold()))
 def selected(self):
  items=self.list.selectedItems();return items[0].data(QtCore.Qt.UserRole) if items else {}
 def selection(self):
  from .asset_import import action
  row=self.selected();label,about=PURPOSES.get(action(row.get('path','')),('Use',''))
  self.use.setText(label);self.use.setEnabled(bool(row));self.reveal.setEnabled(bool(row.get('path')))
  if not row:
   self.shown.setPixmap(QtGui.QPixmap());self.title.setText('Nothing chosen');self.details.setText('Choose an asset to see what it is and what it is for.');return
  self.shown.setPixmap(QtGui.QPixmap.fromImage(picture(row,220)).scaled(220,220,QtCore.Qt.KeepAspectRatio,QtCore.Qt.SmoothTransformation))
  self.title.setText(row.get('name',''))
  self.details.setText('\n\n'.join(part for part in (about,row.get('category',''),'In the folder '+Path(row['path']).parent.name if row.get('path') else '') if part))
 def put_to_use(self):
  """Do the one thing the chosen asset is for."""
  row=self.selected()
  if not row:return
  if str(row.get('path','')).lower().endswith('.moonmat.json'):self.assign()
  else:self.import_asset()
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
   from . import properties,asset_import
   path=self.selected().get('path','');suffix=Path(path).suffix.lower()
   if str(path).lower().endswith('.moonmat.json'):self.assign();return
   if suffix in ('.rdla','.rdlb'):
    from .rdl_import_dialog import show
    show(path);return
   material_name=None
   if suffix=='.mtlx':
    from .materialx_document import load
    document,_=load(path);names=[e.get('name') for e in document.findall('surfacematerial')]
    if len(names)>1:
     material_name,ok=QtWidgets.QInputDialog.getItem(self,'MaterialX material','Choose material',names,0,False)
     if not ok:return
   lx.eval('moonray.library.importAsset '+properties.encode({'path':path,'material_name':material_name}))
   self.status.setText(asset_import.action(path)+' completed. Review imported settings before rendering.')
  except Exception as exc:self.status.setText(str(exc))
 def copy_path(self):QtWidgets.QApplication.clipboard().setText(self.selected().get('path',self.selected().get('url','')))
 def assign(self):
  try:
   from . import properties
   import lx
   row=self.selected()
   if row.get('category')=='Saved materials':
    path=Path(row['path'])
    if path.stat().st_size>16*1024*1024:raise ValueError('Preset exceeds size limit')
    if json.loads(path.read_text(encoding='utf-8')).get('format')==2:
     lx.eval('moonray.library.bundle '+properties.encode({'path':str(path)}));self.status.setText('Material graph and dependencies assigned.');return
   shader,parameters=library.read_preset(row['path']) if row.get('category')=='Saved materials' else (row['shader'],row['parameters'])
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
   if values.get('node_graph') or values.get('materialx_override'):raise ValueError('Use Save graph bundle to include graph dependencies and textures.')
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
 def save_bundle(self):
  try:
   from . import materials,properties,material_bundle
   import modo
   selected=materials.selected()
   if len(selected)!=1:raise ValueError('Select one native MoonShine material or MaterialX override')
   parent=QtWidgets.QFileDialog.getExistingDirectory(self,'Choose a parent folder for the new material bundle')
   if not parent:return
   name,ok=QtWidgets.QInputDialog.getText(self,'Material bundle','New folder name:')
   if not ok:return
   if not name or name in ('.','..') or any(c in name for c in '<>:"/\\|?*') or name[-1] in '. ':raise ValueError('Enter a valid folder name')
   items={item.id:item for item in modo.Scene().items()}
   def lookup(identity):
    item=items[identity];return {'name':item.name,'settings':properties.read(item)}
   manifest=material_bundle.save(selected[0].id,lookup,Path(parent)/name)
   if parent not in self.roots:self.roots.append(parent);self.settings.setValue('roots',json.dumps(self.roots))
   self.refresh();self.status.setText('Saved graph, referenced materials and textures: '+str(manifest))
  except Exception as exc:self.status.setText(str(exc))
 def closeEvent(self,event):self.timer.stop();self.painter.stop();super().closeEvent(event)

_dialog=None
def show(parent=None):
 global _dialog
 if _dialog is None:_dialog=Browser(parent)
 elif not _dialog.isVisible():_dialog.refresh()
 _dialog.show();_dialog.raise_();_dialog.activateWindow()
