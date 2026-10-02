"""Visual node authoring with editable inputs and non-destructive override layers."""
import copy
import json
import uuid
from PySide2 import QtCore,QtGui,QtWidgets
from . import nodes,materialx,properties,shader_library


class Socket(QtWidgets.QGraphicsEllipseItem):
    def __init__(self,editor,identity,key,parent):
        super().__init__(-5,-5,10,10,parent)
        self.editor,self.identity,self.key=editor,identity,key
        self.setBrush(QtGui.QColor('#83c6ff' if key is None else '#d7b878'))
        self.setToolTip('Output: click then click an input' if key is None else key)
    def mousePressEvent(self,event):
        self.editor.socket(self.identity,self.key)
        event.accept()


class Node(QtWidgets.QGraphicsRectItem):
    def __init__(self,editor,identity,value):
        ports=[key for key in nodes.specs(value['type']) if nodes.connectable(value['type'],key)]
        authored=list(value.get('inputs',{}))
        ports=(authored+[key for key in ports if key not in authored])[:10]
        super().__init__(0,0,225,max(70,48+len(ports)*21))
        self.editor,self.identity=editor,identity
        self.setFlags(self.ItemIsMovable|self.ItemIsSelectable|self.ItemSendsGeometryChanges)
        self.setBrush(QtGui.QColor('#293039'));self.setPen(QtGui.QPen(QtGui.QColor('#669dba'),2))
        title=QtWidgets.QGraphicsTextItem(value['type']+('  [OUTPUT]' if identity==editor.graph['root'] else ''),self)
        title.setDefaultTextColor(QtGui.QColor('white'));title.setPos(7,3)
        self.sockets={None:Socket(editor,identity,None,self)};self.sockets[None].setPos(225,20)
        for index,key in enumerate(ports):
            label=QtWidgets.QGraphicsTextItem(key,self);label.setDefaultTextColor(QtGui.QColor('#dddddd'));label.setPos(9,32+index*21)
            socket=Socket(editor,identity,key,self);socket.setPos(0,44+index*21);self.sockets[key]=socket
        self.setPos(*value.get('position',[0,0]))
    def itemChange(self,change,value):
        if change==self.ItemPositionHasChanged and hasattr(self,'identity'):
            self.editor.graph['nodes'][self.identity]['position']=[self.pos().x(),self.pos().y()]
            self.editor.edges()
        return super().itemChange(change,value)


class Editor(QtWidgets.QDialog):
    def __init__(self,item,materialx_override=False):
        super().__init__()
        self.item=item;self.materialx_override=materialx_override;self.graph_key="materialx_graph" if materialx_override else "node_graph";settings=properties.read(item)
        self.graph=copy.deepcopy(settings.get(self.graph_key) or nodes.from_material(item))
        self.pending=None;self.items={};self.links=[];self.busy=False
        self.setWindowTitle(('MaterialX Override — ' if materialx_override else 'MoonShine Node Editor — ')+item.name);self.resize(1150,760)
        layout=QtWidgets.QVBoxLayout(self);toolbar=QtWidgets.QHBoxLayout();layout.addLayout(toolbar)
        self.kinds=QtWidgets.QComboBox();self.kinds.addItems(sorted(shader_library.catalog())+list(nodes.MAPS));toolbar.addWidget(self.kinds)
        for label,callback in [('Add node',self.add),('Delete',self.remove),('Set output',self.output),('Connect input...',self.connect_selected),('Disconnect...',self.disconnect),('Import MaterialX...',self.import_file),('Export definitions...',self.export_file)]:
            button=QtWidgets.QPushButton(label);button.clicked.connect(callback);toolbar.addWidget(button)
        splitter=QtWidgets.QSplitter();layout.addWidget(splitter,1)
        self.canvas=QtWidgets.QGraphicsScene(self);self.view=QtWidgets.QGraphicsView(self.canvas)
        self.view.setRenderHint(QtGui.QPainter.Antialiasing);self.view.setDragMode(QtWidgets.QGraphicsView.RubberBandDrag);splitter.addWidget(self.view)
        pane=QtWidgets.QWidget();right=QtWidgets.QVBoxLayout(pane);splitter.addWidget(pane);splitter.setSizes([800,350])
        self.layers=QtWidgets.QComboBox();right.addWidget(self.layers)
        layer_buttons=QtWidgets.QHBoxLayout();right.addLayout(layer_buttons)
        for label,callback in [('Add override',self.add_override),('Toggle layer',self.toggle_override)]:
            button=QtWidgets.QPushButton(label);button.clicked.connect(callback);layer_buttons.addWidget(button)
        self.table=QtWidgets.QTableWidget(0,2);self.table.setHorizontalHeaderLabels(['Input','Value (JSON)']);self.table.horizontalHeader().setStretchLastSection(True);right.addWidget(self.table)
        self.info=QtWidgets.QLabel('Connect an output socket to an input. Select a node to edit values. Blank uses the native default. Use Connect input for ports not drawn on the node.');self.info.setWordWrap(True);right.addWidget(self.info)
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save|QtWidgets.QDialogButtonBox.Cancel);layout.addWidget(buttons)
        buttons.accepted.connect(self.save);buttons.rejected.connect(self.reject)
        self.canvas.selectionChanged.connect(self.inspect);self.table.itemChanged.connect(self.edited);self.layers.currentIndexChanged.connect(self.inspect)
        self.rebuild()
    def error(self,exc): QtWidgets.QMessageBox.warning(self,'Node graph',str(exc))
    def selected(self): return next((item.identity for item in self.canvas.selectedItems() if isinstance(item,Node)),None)
    def rebuild(self):
        self.busy=True;self.pending=None;self.items={};self.links=[];self.canvas.clear()
        graph=nodes.effective(self.graph)
        for identity,value in graph['nodes'].items():
            item=Node(self,identity,value);self.items[identity]=item;self.canvas.addItem(item)
        self.edges();old=self.layers.currentIndex();self.layers.clear();self.layers.addItem('Base graph',-1)
        for index,layer in enumerate(self.graph.get('overrides',[])):
            self.layers.addItem(('On: ' if layer.get('enabled',True) else 'Off: ')+layer.get('name','Override'),index)
        self.layers.setCurrentIndex(min(max(0,old),self.layers.count()-1));self.busy=False;self.inspect()
    def edges(self):
        if not hasattr(self,'canvas'): return
        for item in self.links:
            if item.scene(): self.canvas.removeItem(item)
        self.links=[]
        for identity,node in nodes.effective(self.graph)['nodes'].items():
            if identity not in self.items: continue
            for key,source in node.get('inputs',{}).items():
                if source not in self.items: continue
                a=self.items[source].sockets[None].scenePos()
                target=self.items[identity];b=target.sockets[key].scenePos() if key in target.sockets else target.scenePos()+QtCore.QPointF(0,20)
                path=QtGui.QPainterPath(a);path.cubicTo(a+QtCore.QPointF(90,0),b-QtCore.QPointF(90,0),b)
                edge=self.canvas.addPath(path,QtGui.QPen(QtGui.QColor('#8bc6d8'),2));edge.setZValue(-1);self.links.append(edge)
    def add(self):
        identity='node_'+uuid.uuid4().hex[:12]
        self.graph['nodes'][identity]={'type':self.kinds.currentText(),'parameters':{},'inputs':{},'position':[0,len(self.items)*35]}
        self.rebuild();self.items[identity].setSelected(True)
    def remove(self):
        identity=self.selected()
        if not identity: return
        if identity==self.graph['root']: self.error('Choose another output before deleting this node');return
        self.graph['nodes'].pop(identity)
        for node in self.graph['nodes'].values(): node['inputs']={k:v for k,v in node.get('inputs',{}).items() if v!=identity}
        self.graph['overrides']=[v for v in self.graph.get('overrides',[]) if v['node']!=identity]
        for layer in self.graph['overrides']: layer['inputs']={k:v for k,v in layer.get('inputs',{}).items() if v!=identity}
        self.rebuild()
    def output(self):
        identity=self.selected()
        if identity and nodes.category(self.graph['nodes'][identity]['type'])=='material': self.graph['root']=identity;self.rebuild()
        else: self.error('Select a surface material node')
    def target(self,identity):
        index=self.layers.currentData()
        if index is None or index<0: return self.graph['nodes'][identity]
        layer=self.graph['overrides'][index]
        if layer['node']!=identity: raise ValueError('This override targets another node. Select its node or create another override.')
        return layer
    def socket(self,identity,key):
        if key is None: self.pending=identity;self.info.setText('Select an input to connect.');return
        if self.pending is None: return
        source=self.pending;self.pending=None;old=copy.deepcopy(self.graph)
        try:
            self.target(identity).setdefault('inputs',{})[key]=source
            nodes.validate(self.graph);self.rebuild()
        except ValueError as exc: self.graph=old;self.error(exc)
    def connect_selected(self):
        target=self.selected()
        if not target: return
        kind=self.graph['nodes'][target]['type'];ports=[key for key in nodes.specs(kind) if nodes.connectable(kind,key)]
        if not ports: return
        port,ok=QtWidgets.QInputDialog.getItem(self,'Connect','Input',ports,0,False)
        if not ok: return
        sources=[key for key in self.graph['nodes'] if key!=target]
        if not sources: return
        labels=[key+' — '+self.graph['nodes'][key]['type'] for key in sources]
        label,ok=QtWidgets.QInputDialog.getItem(self,'Connect','Source',labels,0,False)
        if ok: self.pending=sources[labels.index(label)];self.socket(target,port)
    def disconnect(self):
        identity=self.selected()
        if not identity: return
        keys=list(nodes.effective(self.graph)['nodes'][identity].get('inputs',{}))
        if not keys: return
        key,ok=QtWidgets.QInputDialog.getItem(self,'Disconnect','Input',keys,0,False)
        if ok:
            try:
                target=self.target(identity)
                if self.layers.currentData()<0: target.setdefault('inputs',{}).pop(key,None)
                else: target.setdefault('inputs',{})[key]=None
                self.rebuild()
            except ValueError as exc: self.error(exc)
    def inspect(self,*args):
        if self.busy: return
        self.busy=True;self.table.setRowCount(0);identity=self.selected()
        if identity:
            node=nodes.effective(self.graph)['nodes'][identity]
            for key,spec in nodes.specs(node['type']).items():
                if spec['type']=='SceneObject*': continue
                row=self.table.rowCount();self.table.insertRow(row)
                label=QtWidgets.QTableWidgetItem(key);label.setFlags(label.flags() & ~QtCore.Qt.ItemIsEditable)
                value=node.get('parameters',{}).get(key)
                cell=QtWidgets.QTableWidgetItem('' if value is None else json.dumps(value))
                cell.setToolTip(str(spec.get('comment',''))+' Default: '+str(spec.get('default',spec.get('default_value',''))))
                self.table.setItem(row,0,label);self.table.setItem(row,1,cell)
        self.busy=False
    def edited(self,cell):
        if self.busy or cell.column()!=1: return
        identity=self.selected()
        if not identity: return
        old=copy.deepcopy(self.graph)
        try:
            key=self.table.item(cell.row(),0).text();text=cell.text().strip();target=self.target(identity)
            if not text:
                if self.layers.currentData()>=0: raise ValueError('For an override, enter a value or disable the layer to restore the base')
                target.setdefault('parameters',{}).pop(key,None)
            else:
                value=json.loads(text);shader_library.typed(value,nodes.specs(self.graph['nodes'][identity]['type'])[key])
                target.setdefault('parameters',{})[key]=value
                target.setdefault('inputs',{}).pop(key,None)
            nodes.validate(self.graph);self.edges()
        except (ValueError,TypeError) as exc: self.graph=old;self.error(exc);self.inspect()
    def add_override(self):
        identity=self.selected()
        if not identity: self.error('Select a node to override');return
        name,ok=QtWidgets.QInputDialog.getText(self,'Override layer','Name')
        if ok:
            self.graph.setdefault('overrides',[]).append({'name':name or 'Override','enabled':True,'node':identity,'parameters':{},'inputs':{}})
            self.rebuild();self.layers.setCurrentIndex(self.layers.count()-1);self.items[identity].setSelected(True)
    def toggle_override(self):
        index=self.layers.currentData()
        if index is not None and index>=0:
            layer=self.graph['overrides'][index];layer['enabled']=not layer.get('enabled',True);self.rebuild()
    def import_file(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Import MaterialX','','MaterialX (*.mtlx)')
        if path:
            try: graph=materialx.read(path);self.graph=graph;self.rebuild()
            except (ValueError,OSError) as exc: self.error(exc)
    def export_file(self):
        path,_=QtWidgets.QFileDialog.getSaveFileName(self,'Export MoonRay MaterialX definitions','','MaterialX (*.mtlx)')
        if path:
            try: materialx.write(self.graph,path if path.lower().endswith('.mtlx') else path+'.mtlx')
            except (ValueError,OSError) as exc: self.error(exc)
    def save(self):
        try:
            graph=nodes.validate(self.graph);root=graph['nodes'][graph['root']]
            settings=properties.read(self.item)
            settings[self.graph_key]=self.graph
            if self.materialx_override:
                settings['materialx_override']=True
            else:
                settings.update(native_shader=root['type'],native_parameters=root.get('parameters',{}),shader='DwaBaseMaterial')
            properties.write(self.item,settings);self.accept()
        except ValueError as exc: self.error(exc)
