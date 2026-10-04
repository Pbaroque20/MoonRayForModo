"""Visual node authoring with editable inputs and non-destructive override layers."""
import copy
import json
import uuid
from PySide2 import QtCore,QtGui,QtWidgets
from . import nodes,materialx,properties,shader_library
from .node_widgets import GraphView,ParameterDelegate,COLORS,curve


class Socket(QtWidgets.QGraphicsEllipseItem):
    def __init__(self,editor,identity,key,parent):
        super().__init__(-7,-7,14,14,parent)
        self.is_socket=True
        self.setAcceptHoverEvents(True);self.setCursor(QtCore.Qt.CrossCursor)
        self.editor,self.identity,self.key=editor,identity,key
        category=nodes.category(editor.graph['nodes'][identity]['type']) if key is None else 'map'
        if key is not None:
            spec=nodes.specs(editor.graph['nodes'][identity]['type'])[key]
            if spec['type']=='SceneObject*':category={'INTERFACE_NORMALMAP':'normal','INTERFACE_MAP':'map','INTERFACE_DISPLACEMENT':'displacement'}.get(spec.get('interface'),'material')
        self.setBrush(QtGui.QColor(COLORS[category]));self.setPen(QtGui.QPen(QtGui.QColor('#171b22'),2))
        self.setToolTip('Drag output to a compatible input' if key is None else key+' — drag a connection here; right-click to disconnect')
    def mousePressEvent(self,event):
        self.editor.socket(self.identity,self.key)
        event.accept()


class Node(QtWidgets.QGraphicsRectItem):
    def __init__(self,editor,identity,value):
        ports=[key for key in nodes.specs(value['type']) if nodes.connectable(value['type'],key)]
        authored=list(value.get('inputs',{}))
        ports=authored+[key for key in ports if key not in authored]
        self.hidden_ports=max(0,len(ports)-12) if not editor.show_all.isChecked() else 0
        if self.hidden_ports:ports=ports[:max(12,len(authored))]
        super().__init__(0,0,225,max(70,48+len(ports)*21+(22 if self.hidden_ports else 0)))
        self.editor,self.identity=editor,identity
        self.setFlags(self.ItemIsMovable|self.ItemIsSelectable|self.ItemSendsGeometryChanges)
        self.setBrush(QtGui.QColor('#293039'));self.setPen(QtGui.QPen(QtGui.QColor('#89ce94' if identity==editor.graph['root'] else '#669dba'),2))
        title=QtWidgets.QGraphicsTextItem(value.get('label',value['type'])+('  [OUTPUT]' if identity==editor.graph['root'] else '  [DISPLACEMENT]' if identity==editor.graph.get('displacement') else ''),self)
        title.setToolTip(title.toPlainText());title.setPlainText(QtGui.QFontMetrics(title.font()).elidedText(title.toPlainText(),QtCore.Qt.ElideRight,195));title.setDefaultTextColor(QtGui.QColor('white'));title.setPos(7,3)
        self.sockets={None:Socket(editor,identity,None,self)};self.sockets[None].setPos(225,20)
        for index,key in enumerate(ports):
            label=QtWidgets.QGraphicsTextItem(key,self);label.setToolTip(key);label.setPlainText(QtGui.QFontMetrics(label.font()).elidedText(key,QtCore.Qt.ElideRight,195));label.setDefaultTextColor(QtGui.QColor('#dddddd'));label.setPos(9,32+index*21)
            socket=Socket(editor,identity,key,self);socket.setPos(0,44+index*21);self.sockets[key]=socket
        if self.hidden_ports:
            more=QtWidgets.QGraphicsTextItem('More ports: enable Show all inputs',self);more.setDefaultTextColor(QtGui.QColor('#a9b5c4'));more.setPos(7,34+len(ports)*21)
        self.setPos(*value.get('position',[0,0]))
    def itemChange(self,change,value):
        if change==self.ItemPositionHasChanged and hasattr(self,'identity') and not self.editor.busy:
            self.editor.graph['nodes'][self.identity]['position']=[self.pos().x(),self.pos().y()]
            self.editor.edges()
        return super().itemChange(change,value)


class Editor(QtWidgets.QDialog):
    def __init__(self,item,materialx_override=False):
        super().__init__()
        self.setMinimumSize(900,560)
        self.item=item;self.materialx_override=materialx_override;self.graph_key="materialx_graph" if materialx_override else "node_graph";settings=properties.read(item)
        self.graph=copy.deepcopy(settings.get(self.graph_key) or nodes.from_material(item))
        self.pending=None;self.items={};self.links=[];self.busy=False
        self.undo_states=[];self.redo_states=[];self.selected_input=None;self.add_at=None
        self.setWindowTitle(('MaterialX Override — ' if materialx_override else 'MoonShine Node Editor — ')+item.name);self.resize(1150,760)
        layout=QtWidgets.QVBoxLayout(self);toolbar=QtWidgets.QHBoxLayout();layout.addLayout(toolbar)
        self.kinds=QtWidgets.QComboBox();self.kinds.addItems(nodes.kinds());self.kinds.setEditable(True);self.kinds.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        self.kinds.completer().setFilterMode(QtCore.Qt.MatchContains);self.kinds.completer().setCompletionMode(QtWidgets.QCompleter.PopupCompletion)
        self.kinds.setMinimumWidth(210);self.kinds.setToolTip('Search for a material, texture or value node');toolbar.addWidget(self.kinds,1)
        for label,callback in [('Add node',self.add),('Delete',self.remove),('Set output',self.output),('Displacement output',self.displacement_output),('Connect input…',self.connect_selected),('Disconnect…',self.disconnect)]:
            button=QtWidgets.QPushButton(label);button.clicked.connect(callback);toolbar.addWidget(button)
        tools=QtWidgets.QHBoxLayout();layout.addLayout(tools)
        for label,callback in [('Undo',self.undo),('Redo',self.redo),('Frame all',self.frame),('Browse image…',self.browse_image),('Reset input',self.reset_input),('Import MaterialX…',self.import_file),('Export definitions…',self.export_file)]:
            button=QtWidgets.QPushButton(label);button.clicked.connect(callback);tools.addWidget(button)
        preview=QtWidgets.QPushButton('Widget preview');preview.clicked.connect(self.preview_widget);tools.addWidget(preview)
        self.finished.connect(lambda *_:getattr(self,'_widget_preview',None) and self._widget_preview.close())
        self.auto_connect=QtWidgets.QCheckBox('Auto-connect new node');self.auto_connect.setChecked(True);tools.addWidget(self.auto_connect)
        self.show_all=QtWidgets.QCheckBox('Show all inputs');self.show_all.setToolTip('Expand every connectable socket. Connected inputs are always visible.');tools.addWidget(self.show_all);self.show_all.toggled.connect(self.rebuild)
        splitter=QtWidgets.QSplitter();layout.addWidget(splitter,1)
        self.canvas=QtWidgets.QGraphicsScene(self);self.view=GraphView(self,self.canvas)
        self.view.setRenderHint(QtGui.QPainter.Antialiasing);self.view.setDragMode(QtWidgets.QGraphicsView.RubberBandDrag);splitter.addWidget(self.view)
        pane=QtWidgets.QWidget();right=QtWidgets.QVBoxLayout(pane);splitter.addWidget(pane);splitter.setSizes([800,350])
        self.layers=QtWidgets.QComboBox();right.addWidget(self.layers)
        layer_buttons=QtWidgets.QHBoxLayout();right.addLayout(layer_buttons)
        for label,callback in [('Add override',self.add_override),('Toggle layer',self.toggle_override)]:
            button=QtWidgets.QPushButton(label);button.clicked.connect(callback);layer_buttons.addWidget(button)
        self.table=QtWidgets.QTableWidget(0,2);self.table.setHorizontalHeaderLabels(['Input','Value']);self.table.horizontalHeader().setStretchLastSection(True);right.addWidget(self.table)
        self.table.setItemDelegateForColumn(1,ParameterDelegate(self))
        self.property_search=QtWidgets.QLineEdit();self.property_search.setPlaceholderText('Filter properties…');right.insertWidget(1,self.property_search);self.property_search.textChanged.connect(self.filter_properties)
        self.info=QtWidgets.QLabel('Drag output → input to connect. Green wire = compatible. Right-click a socket or wire to disconnect. Wheel: zoom · middle drag: pan · F: frame. Select an input to auto-connect a new node. Double-click values to edit.');self.info.setWordWrap(True);right.addWidget(self.info)
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save|QtWidgets.QDialogButtonBox.Cancel);layout.addWidget(buttons)
        buttons.accepted.connect(self.save);buttons.rejected.connect(self.reject)
        self.canvas.selectionChanged.connect(self.inspect);self.table.itemChanged.connect(self.edited);self.layers.currentIndexChanged.connect(self.inspect)
        self.rebuild();self.frame()
    def preview_widget(self):
        from .material_preview import show
        def draft():
            material=copy.deepcopy(properties.read(self.item))
            material.update(node_graph=copy.deepcopy(self.graph),node_override=True)
            return material
        show(self.item,draft,self)
    def error(self,exc): QtWidgets.QMessageBox.warning(self,'Node graph',str(exc))
    def selected(self): return next((item.identity for item in self.canvas.selectedItems() if isinstance(item,Node)),None)
    def rebuild(self,*args):
        selected=self.selected()
        if hasattr(self,'view'):self.view.cancel_wire()
        self.busy=True;self.pending=None;self.items={};self.links=[];self.canvas.clear()
        graph=nodes.effective(self.graph)
        for identity,value in graph['nodes'].items():
            item=Node(self,identity,value);self.items[identity]=item;self.canvas.addItem(item)
        self.edges();old=self.layers.currentIndex();self.layers.clear();self.layers.addItem('Base graph',-1)
        for index,layer in enumerate(self.graph.get('overrides',[])):
            self.layers.addItem(('On: ' if layer.get('enabled',True) else 'Off: ')+layer.get('name','Override'),index)
        self.layers.setCurrentIndex(min(max(0,old),self.layers.count()-1));self.busy=False
        if selected in self.items:self.items[selected].setSelected(True)
        self.canvas.setSceneRect(self.canvas.itemsBoundingRect().adjusted(-250,-250,250,250));self.inspect()
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
                path=curve(a,b)
                edge=self.canvas.addPath(path,QtGui.QPen(QtGui.QColor('#8bc6d8'),2));edge.setZValue(-1);edge.connection=(identity,key);edge.setToolTip('Right-click to disconnect '+key);self.links.append(edge)
    def remember(self,before):
        if before!=self.graph:self.undo_states.append(before);self.undo_states=self.undo_states[-50:];self.redo_states=[]
    def undo(self):
        if self.undo_states:self.redo_states.append(copy.deepcopy(self.graph));self.graph=self.undo_states.pop();self.rebuild()
    def redo(self):
        if self.redo_states:self.undo_states.append(copy.deepcopy(self.graph));self.graph=self.redo_states.pop();self.rebuild()
    def frame(self):
        if self.items:self.view.fitInView(self.canvas.itemsBoundingRect().adjusted(-35,-35,35,35),QtCore.Qt.KeepAspectRatio)
    def focus_socket(self,identity,key):
        self.canvas.clearSelection();self.items[identity].setSelected(True)
        if key is not None:self.selected_input=(identity,key);self.info.setText('Selected input: '+key+'. Drag a wire here or add a compatible node with Auto-connect enabled.')
    def validate_draft(self):
        draft=copy.deepcopy(self.graph);index=self.layers.currentData()
        if index is not None and index>=0:draft['overrides'][index]['enabled']=True
        return nodes.validate(draft)
    def can_connect(self,source,identity,key):
        before=copy.deepcopy(self.graph)
        try:self.target(identity).setdefault('inputs',{})[key]=source;self.validate_draft();return True
        except (ValueError,KeyError,TypeError):return False
        finally:self.graph=before
    def connect_nodes(self,source,identity,key):
        before=copy.deepcopy(self.graph)
        try:
            self.target(identity).setdefault('inputs',{})[key]=source
            self.validate_draft();self.remember(before);self.rebuild();self.info.setText('Connected to '+key)
        except (ValueError,KeyError) as exc:self.graph=before;self.error(exc)
    def unlink(self,identity,key):
        before=copy.deepcopy(self.graph)
        try:
            target=self.target(identity)
            if self.layers.currentData()<0:target.setdefault('inputs',{}).pop(key,None)
            else:target.setdefault('inputs',{})[key]=None
            self.validate_draft();self.remember(before);self.rebuild()
        except ValueError as exc:self.graph=before;self.error(exc)
    def add(self):
        kind=self.kinds.currentText()
        if kind not in nodes.kinds():self.error('Choose a supported node from the search results');return
        before=copy.deepcopy(self.graph);identity='node_'+uuid.uuid4().hex[:12]
        point=self.add_at or self.view.mapToScene(self.view.viewport().rect().center());self.add_at=None
        self.graph['nodes'][identity]={'type':kind,'parameters':{},'inputs':{},'position':[point.x()-110,point.y()-30]}
        if self.auto_connect.isChecked() and self.selected_input:
            target,key=self.selected_input
            if target in self.graph['nodes']:
                try:
                    self.target(target).setdefault('inputs',{})[key]=identity;self.validate_draft()
                except (ValueError,KeyError) as exc:
                    self.graph=before;self.error('Cannot auto-connect this node: '+str(exc));return
        self.remember(before);self.rebuild();self.canvas.clearSelection();self.items[identity].setSelected(True)
    def browse_image(self):
        identity=self.selected()
        if not identity:self.error('Select a texture node first');return
        kind=self.graph['nodes'][identity]['type'];schema=nodes.specs(kind)
        filenames=['file'] if kind=='image' else [key for key,spec in schema.items() if spec['type']=='String' and 'FLAGS_FILENAME' in spec.get('flags','')]
        if not filenames:self.error('This node has no texture file input');return
        key=filenames[0]
        if len(filenames)>1:
            key,ok=QtWidgets.QInputDialog.getItem(self,'Texture input','Input',filenames,0,False)
            if not ok:return
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Choose texture image','','Images (*.exr *.hdr *.png *.jpg *.jpeg *.tif *.tiff *.tx);;All files (*)')
        if path:
            before=copy.deepcopy(self.graph)
            try:self.target(identity).setdefault('parameters',{})[key]=path;self.validate_draft();self.remember(before);self.inspect()
            except ValueError as exc:self.graph=before;self.error(exc)
    def reset_input(self):
        identity=self.selected();row=self.table.currentRow()
        if not identity or row<0:return
        key=self.table.item(row,0).text();before=copy.deepcopy(self.graph)
        try:
            target=self.target(identity);target.setdefault('parameters',{}).pop(key,None);target.setdefault('inputs',{}).pop(key,None)
            self.validate_draft();self.remember(before);self.rebuild()
        except ValueError as exc:self.graph=before;self.error(exc)
    def filter_properties(self,*args):
        query=self.property_search.text().casefold()
        for row in range(self.table.rowCount()):self.table.setRowHidden(row,query not in self.table.item(row,0).text().casefold())
    def remove(self):
        identity=self.selected()
        if not identity: return
        if identity==self.graph['root']: self.error('Choose another output before deleting this node');return
        before=copy.deepcopy(self.graph)
        self.graph['nodes'].pop(identity)
        if self.graph.get('displacement')==identity:self.graph.pop('displacement')
        for node in self.graph['nodes'].values(): node['inputs']={k:v for k,v in node.get('inputs',{}).items() if v!=identity}
        self.graph['overrides']=[v for v in self.graph.get('overrides',[]) if v['node']!=identity]
        for layer in self.graph['overrides']: layer['inputs']={k:v for k,v in layer.get('inputs',{}).items() if v!=identity}
        self.remember(before);self.rebuild()
    def output(self):
        identity=self.selected()
        if identity and nodes.category(self.graph['nodes'][identity]['type'])=='material':
            before=copy.deepcopy(self.graph);self.graph['root']=identity;self.remember(before);self.rebuild()
        else: self.error('Select a surface material node')
    def displacement_output(self):
        identity=self.selected()
        if identity and nodes.category(self.graph['nodes'][identity]['type'])=='displacement':
            before=copy.deepcopy(self.graph)
            if self.graph.get('displacement')==identity:self.graph.pop('displacement')
            else:self.graph['displacement']=identity
            self.remember(before);self.rebuild()
        else:self.error('Select a scalar, vector or combined displacement node. Click again to detach it.')

    def target(self,identity):
        index=self.layers.currentData()
        if index is None or index<0: return self.graph['nodes'][identity]
        layer=self.graph['overrides'][index]
        if layer['node']!=identity: raise ValueError('This override targets another node. Select its node or create another override.')
        return layer
    def socket(self,identity,key):
        if key is None: self.pending=identity;self.info.setText('Select an input to connect.');return
        if self.pending is None: return
        source=self.pending;self.pending=None;self.connect_nodes(source,identity,key)
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
        if ok:self.unlink(identity,key)
    def inspect(self,*args):
        if self.busy: return
        self.busy=True;self.table.setRowCount(0);identity=self.selected()
        if identity:
            node=nodes.effective(self.graph)['nodes'][identity]
            for key,spec in nodes.specs(node['type']).items():
                if spec['type']=='SceneObject*':
                    if spec.get('interface') in ('INTERFACE_CAMERA','INTERFACE_NODE'):
                        import modo
                        row=self.table.rowCount();self.table.insertRow(row);self.table.setItem(row,0,QtWidgets.QTableWidgetItem(key))
                        pick=QtWidgets.QComboBox();pick.addItem('None',None)
                        for item in sorted(modo.Scene().items('camera' if spec.get('interface')=='INTERFACE_CAMERA' else 'locator'),key=lambda i:i.name.casefold()):pick.addItem(item.name,item.id)
                        chosen=node.get('parameters',{}).get(key) or {};pick.setCurrentIndex(max(0,pick.findData(chosen.get('item'))));self.table.setCellWidget(row,1,pick)
                        pick.currentIndexChanged.connect(lambda _index,n=identity,k=key,w=pick:self.scene_reference(n,k,w.currentData()))
                    continue
                row=self.table.rowCount();self.table.insertRow(row)
                label=QtWidgets.QTableWidgetItem(key);label.setFlags(label.flags() & ~QtCore.Qt.ItemIsEditable)
                value=node.get('parameters',{}).get(key)
                cell=QtWidgets.QTableWidgetItem('' if value is None else json.dumps(value))
                if key in node.get('inputs',{}):cell.setBackground(QtGui.QColor('#294757'));label.setToolTip('Connected from '+node['inputs'][key]+'; editing this value replaces the connection')
                cell.setToolTip(str(spec.get('comment',''))+' Default: '+str(spec.get('default',spec.get('default_value',''))))
                self.table.setItem(row,0,label);self.table.setItem(row,1,cell)
        self.busy=False;self.filter_properties()
    def scene_reference(self,identity,key,value):
        before=copy.deepcopy(self.graph)
        try:
            self.target(identity).setdefault('parameters',{})[key]={'item':value} if value else None
            self.validate_draft();self.remember(before)
        except (ValueError,TypeError) as exc:self.graph=before;self.error(exc)

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
            self.validate_draft();self.remember(old);QtCore.QTimer.singleShot(0,self.rebuild)
        except (ValueError,TypeError) as exc: self.graph=old;self.error(exc);self.inspect()
    def add_override(self):
        identity=self.selected()
        if not identity: self.error('Select a node to override');return
        name,ok=QtWidgets.QInputDialog.getText(self,'Override layer','Name')
        if ok:
            before=copy.deepcopy(self.graph)
            self.graph.setdefault('overrides',[]).append({'name':name or 'Override','enabled':True,'node':identity,'parameters':{},'inputs':{}})
            self.remember(before);self.rebuild();self.layers.setCurrentIndex(self.layers.count()-1);self.items[identity].setSelected(True)
    def toggle_override(self):
        index=self.layers.currentData()
        if index is not None and index>=0:
            before=copy.deepcopy(self.graph);layer=self.graph['overrides'][index];layer['enabled']=not layer.get('enabled',True)
            try:nodes.validate(self.graph);self.remember(before);self.rebuild()
            except ValueError as exc:self.graph=before;self.error(exc)
    def import_file(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Import MaterialX','','MaterialX (*.mtlx)')
        if path:
            try: graph=materialx.read(path);before=copy.deepcopy(self.graph);self.graph=graph;self.remember(before);self.rebuild();self.frame()
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
