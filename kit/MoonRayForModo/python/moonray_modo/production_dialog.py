"""Artist-facing per-item lighting, strand and volume controls."""
import copy
from PySide2 import QtCore,QtWidgets
import modo

class Controls(QtWidgets.QDialog):
    def __init__(self,values,parent=None):
        super().__init__(parent);self.setWindowTitle('MoonRay scene controls');self.resize(760,740)
        self.values=copy.deepcopy(values);self.values.setdefault('objects',{});self.values.setdefault('lights',{})
        self.current={};self.fields={};self.selectors={};self.lists={};layout=QtWidgets.QVBoxLayout(self);tabs=QtWidgets.QTabWidget();layout.addWidget(tabs)
        scene=modo.Scene();lights=list(scene.items('light'));objects=list(scene.items('locator'));known={i.id for i in objects}
        for kind in ('mesh','meshInst','replicator','volume'):
            for item in scene.items(kind,superType=False):
                if item.id not in known:objects.append(item);known.add(item.id)
        for category,title,items in [('objects','Objects / geometry',objects),('lights','Lights / filters',lights)]:
            page=QtWidgets.QWidget();form=QtWidgets.QFormLayout(page);scroll=QtWidgets.QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(page);tabs.addTab(scroll,title)
            pick=QtWidgets.QComboBox();pick.addItem('Select an item…',None)
            for item in sorted(items,key=lambda i:i.name.casefold()):pick.addItem(item.name,item.id)
            self.selectors[category]=pick;self.fields[category]={};form.addRow('Item',pick)
            def field(key,label,kind,default,minimum=-100000,maximum=100000,choices=None):
                if kind=='color':
                    w=QtWidgets.QWidget();row=QtWidgets.QHBoxLayout(w);row.setContentsMargins(0,0,0,0);w.channels=[]
                    for name in ('R','G','B'):
                        spin=QtWidgets.QDoubleSpinBox();spin.setRange(0,10000);spin.setDecimals(4);spin.setPrefix(name+' ');row.addWidget(spin);w.channels.append(spin)
                elif kind=='bool':w=QtWidgets.QCheckBox()
                elif kind=='choice':
                    w=QtWidgets.QComboBox()
                    for title,value in choices:w.addItem(title,value)
                elif kind=='number':w=QtWidgets.QDoubleSpinBox();w.setDecimals(6);w.setRange(minimum,maximum)
                elif kind=='int':w=QtWidgets.QSpinBox();w.setRange(int(minimum),int(maximum))
                else:w=QtWidgets.QLineEdit()
                self.fields[category][key]=(w,kind,default);form.addRow(label,w);return w
            if category=='objects':
                field('link_enabled','Restrict illumination to checked lights','bool',False)
                for key,label in [('lights','Illuminating lights'),('shadow_exclude','Do not cast shadows for these lights')]:
                    w=QtWidgets.QListWidget();w.setMaximumHeight(120);self.lists[key]=w
                    for name,identity in [('All environments','__environment__')]+[(i.name+' (environment)',i.id) for i in scene.items('environment',superType=False)]+[(i.name,i.id) for i in lights]+[(i.name+' (mesh emitter)',i.id) for i in objects if i.type=='mesh']:
                        row=QtWidgets.QListWidgetItem(name,w);row.setData(QtCore.Qt.UserRole,identity);row.setFlags(row.flags()|QtCore.Qt.ItemIsUserCheckable);row.setCheckState(QtCore.Qt.Unchecked)
                    form.addRow(label,w)
                field('motion_topology','Changing topology during shutter','choice','strict',choices=[('Require stable topology','strict'),('Frame-time geometry; no deformation blur','freeze'),('Frame-time points / strands with velocities','velocity')])
                field('point_id_map','Persistent point ID weight map','text','')
                field('strand_id_tag','Persistent strand ID tag (4 characters)','text','')
                field('asset_label','Cryptomatte asset label','text','')
                field('mesh_light','Use mesh as emitter','bool',False);field('light_intensity','Emitter intensity','number',1,0)
                field('light_label','Emitter AOV group','text','');field('light_color','Emitter color (linear RGB)','color',[1,1,1])
                field('points','Render every mesh vertex as a point','bool',False)
                field('radius','Strand / point radius (m)','number',.001,.000001)
                field('curve_samples','Samples per curve bend','int',32,2,256)
                field('material','Strand / point material tag','text','')
                path=field('geometry_file','VDB or strand / point JSON file','text','')
                browse=QtWidgets.QPushButton('Choose geometry asset…');browse.clicked.connect(lambda:self._browse('objects','geometry_file','Geometry (*.vdb *.json);;All files (*)'));form.addRow(browse)
                note=QtWidgets.QLabel('Use #### in a geometry filename for an animated sequence. Attach file geometry to any locator. Strand/point material tags refer to Shader Tree material masks.');note.setWordWrap(True);form.addRow(note)
                field('density_grid','VDB density grid','text','density');field('emission_grid','VDB emission grid','text','');field('velocity_grid','VDB velocity grid','text','')
                field('volume_color','Volume scattering color (linear RGB)','color',[1,1,1])
                field('density','Volume density multiplier','number',1,0);field('emission','Volume emission multiplier','number',1,0)
                field('anisotropy','Volume scattering anisotropy','number',0,-1,1);field('velocity_scale','Volume velocity scale','number',1)
            else:
                from .lighting import LIGHT_KINDS
                field('kind','Native emitter type','choice','',choices=[('Use Modo type','')]+[(k,k) for k in LIGHT_KINDS if k])
                field('label','AOV light group','text','')
                field('portal_environment','Portal lighting environment','choice','',choices=[('Automatic (one lighting environment)','')]+[(i.name,i.id) for i in scene.items('environment',superType=False)])
                note=QtWidgets.QLabel("Use a label such as key or fill in light-path expressions. A portal requires exactly one active environment. Modo's transform, color and intensity remain active.");note.setWordWrap(True);form.addRow(note)
                field('filter_enabled','Enable intensity filter','bool',False)
                field('filter_color','Filter color (linear RGB)','color',[1,1,1])
                field('filter_intensity','Filter intensity','number',1,0);field('filter_exposure','Filter exposure (stops)','number',0,-30,30)
                field('filter_locator','Filter transform','choice','',choices=[('Use light transform','')]+[(i.name,i.id) for i in objects])
                field('rod_enabled','Enable box / rod filter','bool',False)
                for key,label,default in [('rod_width','Rod width',1),('rod_height','Rod height',1),('rod_depth','Rod depth',1),('rod_radius','Rod roundness',0),('rod_edge','Rod feather',.1),('rod_density','Rod density',1)]:field(key,label,'number',default,0)
                field('rod_color','Rod color','color',[0,0,0]);field('rod_invert','Invert rod','bool',False)
                field('barn_enabled','Enable barn doors','bool',False)
                for side in ('top','bottom','left','right'):field('barn_'+side,'Barn door '+side,'number',0)
                field('barn_edge','Barn door feather','number',.1,0)
                field('cookie_file','Projected cookie image','text','')
                choose=QtWidgets.QPushButton('Choose cookie image…');choose.clicked.connect(lambda:self._browse('lights','cookie_file','Images (*.*)'));form.addRow(choose)
                field('cookie_focal','Cookie focal length (mm)','number',30,.001);field('cookie_aperture','Cookie film width (mm)','number',24,.001)
                field('cookie_density','Cookie density','number',1,0,1);field('cookie_invert','Invert cookie','bool',False)
                field('ramp_enabled','Enable color-distance ramp','bool',False)
                field('ramp_start','Ramp start distance','number',0,0);field('ramp_end','Ramp end distance','number',10,.001)
                field('ramp_color0','Ramp start color','color',[1,1,1]);field('ramp_color1','Ramp end color','color',[0,0,0])
                field('filter_vdb','VDB filter file','text','');field('filter_vdb_grid','VDB filter grid','text','density');field('filter_vdb_tint','VDB filter tint','color',[0,0,0])
                choose=QtWidgets.QPushButton('Choose filter VDB…');choose.clicked.connect(lambda:self._browse('lights','filter_vdb','VDB (*.vdb)'));form.addRow(choose)
                field('decay_enabled','Enable distance falloff filter','bool',False)
                for key,label,default in [('near_start','Near start (m)',0),('near_end','Near end (m)',0),('far_start','Far start (m)',10),('far_end','Far end (m)',20)]:field(key,label,'number',default,0)
            pick.currentIndexChanged.connect(lambda _index,c=category:self._select(c))
            self._select(category)
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save|QtWidgets.QDialogButtonBox.Cancel);buttons.accepted.connect(self._accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
    def _save(self,category):
        identity=self.current.get(category)
        if identity is None:return
        value=dict(self.values[category].get(identity,{}))
        for key,(w,kind,default) in self.fields[category].items():value[key]=[c.value() for c in w.channels] if kind=='color' else w.isChecked() if kind=='bool' else w.currentData() if kind=='choice' else w.value() if kind in ('number','int') else w.text().strip()
        if category=='objects':
            for key,w in self.lists.items():value[key]=[w.item(i).data(QtCore.Qt.UserRole) for i in range(w.count()) if w.item(i).checkState()==QtCore.Qt.Checked]
        self.values[category][identity]=value
    def _select(self,category):
        self._save(category);identity=self.selectors[category].currentData();self.current[category]=identity;value=self.values[category].get(identity,{})
        for key,(w,kind,default) in self.fields[category].items():
            v=value.get(key,default);w.setEnabled(identity is not None)
            if kind=='color':
                for channel,component in zip(w.channels,v):channel.setValue(component)
            elif kind=='bool':w.setChecked(bool(v))
            elif kind=='choice':w.setCurrentIndex(max(0,w.findData(v)))
            elif kind in ('number','int'):w.setValue(v)
            else:w.setText(str(v))
        if category=='objects':
            for key,w in self.lists.items():
                w.setEnabled(identity is not None)
                for i in range(w.count()):w.item(i).setCheckState(QtCore.Qt.Checked if w.item(i).data(QtCore.Qt.UserRole) in value.get(key,[]) else QtCore.Qt.Unchecked)
    def _browse(self,category,key,filter):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Geometry asset','',filter)
        if path:self.fields[category][key][0].setText(path)
    def _accept(self):
        for category in self.fields:self._save(category)
        self.accept()
