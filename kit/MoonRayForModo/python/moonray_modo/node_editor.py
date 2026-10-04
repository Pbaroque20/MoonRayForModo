"""Visual node authoring with editable inputs and non-destructive override layers."""
import copy
import json
import os
import uuid
from PySide2 import QtCore,QtGui,QtWidgets
from . import nodes,materialx,properties,shader_library,node_defaults
from .node_widgets import GraphView,ParameterDelegate,NumericField,COLORS,curve,file_parameter


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
        from .preview_diagnostics import record
        record('Graph editor opened')
        self.numeric_fields=[]
        self.item=item;self.materialx_override=materialx_override;self.graph_key="materialx_graph" if materialx_override else "node_graph";settings=properties.read(item)
        self.graph=copy.deepcopy(settings.get(self.graph_key) or nodes.from_material(item))
        self.pending=None;self.items={};self.links=[];self.busy=False
        self.undo_states=[];self.redo_states=[];self.selected_input=None;self.add_at=None
        self.setWindowTitle(('MaterialX Override — ' if materialx_override else 'MoonShine Node Editor — ')+item.name);self.resize(1150,760)
        layout=QtWidgets.QVBoxLayout(self);toolbar=QtWidgets.QHBoxLayout();layout.addLayout(toolbar)
        self.kinds=QtWidgets.QComboBox(self);self.kinds.addItems(nodes.kinds());self.kinds.hide()
        def menu_button(title,actions):
            button=QtWidgets.QToolButton();button.setText(title);button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
            menu=QtWidgets.QMenu(button)
            for label,callback in actions:
                if label is None:menu.addSeparator()
                else:menu.addAction(label,callback)
            button.setMenu(menu);toolbar.addWidget(button);return menu
        menu_button('Graph', [('Inspect MaterialX support...',self.inspect_materialx),('Check asset files...',self.check_assets),('Import MaterialX…',self.import_file),('Export definitions…',self.export_file),
                    (None,None),('Add override layer…',self.add_override),('Toggle override layer',self.toggle_override)])
        menu_button('Node', [('Set material output',self.output),('Set / clear displacement output',self.displacement_output),
                    (None,None),('Connect input…',self.connect_selected),('Disconnect input…',self.disconnect),
                    ('Browse image…',self.browse_image),('Reset selected input',self.reset_input),
                    (None,None),('Delete selected node',self.remove)])
        view_menu=menu_button('View',[])
        self.auto_connect=view_menu.addAction('Auto-connect new nodes');self.auto_connect.setCheckable(True);self.auto_connect.setChecked(True)
        self.show_all=view_menu.addAction('Show all input sockets');self.show_all.setCheckable(True)
        self.show_all.setToolTip('Connected inputs are always visible.');self.show_all.toggled.connect(self.rebuild)
        for label,callback in [('Undo',self.undo),('Redo',self.redo),('Frame all',self.frame)]:
            button=QtWidgets.QPushButton(label);button.clicked.connect(callback);toolbar.addWidget(button)
        self.output_label=QtWidgets.QLabel();self.output_label.setToolTip('The Output material is rendered. Apply or Save updates the scene override.');toolbar.addWidget(self.output_label)
        toolbar.addStretch(1)
        splitter=QtWidgets.QSplitter();layout.addWidget(splitter,1)
        self.build_node_browser(splitter)
        self.canvas=QtWidgets.QGraphicsScene(self);self.view=GraphView(self,self.canvas)
        self.view.setRenderHint(QtGui.QPainter.Antialiasing);self.view.setDragMode(QtWidgets.QGraphicsView.RubberBandDrag);splitter.addWidget(self.view)
        inspector=QtWidgets.QSplitter(QtCore.Qt.Vertical);splitter.addWidget(inspector)
        pane=QtWidgets.QWidget();right=QtWidgets.QVBoxLayout(pane);inspector.addWidget(pane);splitter.setSizes([225,600,360]);splitter.setStretchFactor(1,1)
        self.property_title=QtWidgets.QLabel('Select a node');right.addWidget(self.property_title)
        self.layers=QtWidgets.QComboBox();self.layers.setToolTip('Property override layer');right.addWidget(self.layers)
        self.table=QtWidgets.QTableWidget(0,2);self.table.setHorizontalHeaderLabels(['Input','Value']);self.table.horizontalHeader().setStretchLastSection(True);self.table.verticalHeader().hide();self.table.setShowGrid(False);self.table.setAlternatingRowColors(True);right.addWidget(self.table)
        self.table.setItemDelegateForColumn(1,ParameterDelegate(self))
        self.table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.property_menu)
        self.property_search=QtWidgets.QLineEdit();self.property_search.setClearButtonEnabled(True);self.property_search.setPlaceholderText('Filter properties…');right.insertWidget(1,self.property_search);self.property_search.textChanged.connect(self.filter_properties)
        from .material_preview import Panel
        self.material_preview=Panel(self.item,self.preview_draft,self,embedded=True);inspector.addWidget(self.material_preview);inspector.setSizes([320,380])
        self.finished.connect(lambda *_:self.material_preview.shutdown())
        self.info=QtWidgets.QLabel('Drag sockets to connect. Enter commits values; Save applies the graph.')
        self.info.setWordWrap(True)
        self.info.setToolTip('Green wire: compatible input. Right-click a socket or wire to disconnect. Wheel: zoom. Middle drag: pan. F: frame all. Double-click a property to edit. Node and Graph menus contain additional actions.')
        layout.addWidget(self.info)
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save|QtWidgets.QDialogButtonBox.Apply|QtWidgets.QDialogButtonBox.Cancel);layout.addWidget(buttons)
        buttons.accepted.connect(self.save);buttons.rejected.connect(self.reject)
        buttons.button(QtWidgets.QDialogButtonBox.Apply).clicked.connect(lambda:self.save(False))
        self.canvas.selectionChanged.connect(self.inspect);self.table.itemChanged.connect(self.edited);self.layers.currentIndexChanged.connect(self.inspect)
        for button in self.findChildren(QtWidgets.QPushButton):
            button.setAutoDefault(False);button.setDefault(False)
        self.rebuild();self.frame()
    def keyPressEvent(self,event):
        if event.key() in (QtCore.Qt.Key_Return,QtCore.Qt.Key_Enter):
            self.commit_inputs()
            event.accept();return
        super().keyPressEvent(event)
    def build_node_browser(self,splitter):
        pane=QtWidgets.QWidget();layout=QtWidgets.QVBoxLayout(pane)
        layout.addWidget(QtWidgets.QLabel('Node library'))
        self.node_search=QtWidgets.QLineEdit();self.node_search.setClearButtonEnabled(True);self.node_search.setPlaceholderText('Search nodes or groups…');layout.addWidget(self.node_search)
        self.node_tree=QtWidgets.QTreeWidget();self.node_tree.setHeaderHidden(True);self.node_tree.setIndentation(12);layout.addWidget(self.node_tree,1)
        hint=QtWidgets.QLabel('Click a node to add it.');hint.setWordWrap(True);layout.addWidget(hint)
        groups={}
        for kind in nodes.kinds():
            category=nodes.category(kind);name=kind.casefold()
            if category=='material':group='Hair materials' if 'hair' in name else 'Materials'
            elif category=='normal':group='Normals and bump'
            elif category=='displacement':group='Displacement'
            elif any(v in name for v in ('image','udim','uvtexture')):group='Image textures'
            elif any(v in name for v in ('project','texcoord','transform','primvar')):group='Coordinates and projections'
            elif any(v in name for v in ('colorcorrect','hsv','rgbto','gamma','saturation','contrast')):group='Color adjustments'
            elif any(v in name for v in ('noise','checker','ramp','gradient','random','wireframe','curvature','vdb')):group='Procedural textures'
            elif kind in nodes.MAPS or any(v in name for v in ('opmap','blend','mix','layer','switch','clamp','remap','constant')):group='Math and blending'
            else:group='Data and utilities'
            if group not in groups:
                groups[group]=QtWidgets.QTreeWidgetItem(self.node_tree,[group])
                groups[group].setExpanded(group=='Materials')
            row=QtWidgets.QTreeWidgetItem(groups[group],[kind]);row.setData(0,QtCore.Qt.UserRole,kind)
            from .node_descriptions import tooltip
            row.setToolTip(0,tooltip(kind))
        self.node_tree.sortItems(0,QtCore.Qt.AscendingOrder)
        self.node_tree.itemClicked.connect(self.add_from_browser)
        self.node_search.textChanged.connect(self.filter_node_browser)
        splitter.addWidget(pane)
    def filter_node_browser(self,text):
        query=text.casefold().strip()
        for index in range(self.node_tree.topLevelItemCount()):
            group=self.node_tree.topLevelItem(index);visible=False
            for child in range(group.childCount()):
                row=group.child(child);match=query in (group.text(0)+' '+row.text(0)).casefold()
                row.setHidden(not match);visible=visible or match
            group.setHidden(not visible)
            if query and visible:group.setExpanded(True)
    def add_from_browser(self,item,column):
        kind=item.data(0,QtCore.Qt.UserRole)
        if not kind:return
        self.kinds.setCurrentText(kind);self.add()
    def choose_node_color(self,identity,key):
        self.commit_inputs()
        node=nodes.effective(self.graph)['nodes'][identity];spec=nodes.specs(node['type'])[key]
        current=node.get('parameters',{}).get(key,node_defaults.value(spec))
        color=QtWidgets.QColorDialog.getColor(QtGui.QColor.fromRgbF(*[max(0,min(1,v)) for v in current[:3]]),self,'Choose '+key)
        if not color.isValid():return
        before=copy.deepcopy(self.graph)
        try:
            target=self.target(identity);target.setdefault('parameters',{})[key]=[color.redF(),color.greenF(),color.blueF()]
            target.setdefault('inputs',{}).pop(key,None);self.validate_draft();self.remember(before);self.rebuild()
        except ValueError as exc:self.graph=before;self.error(exc)
    def choose_node_file(self,identity,key):
        self.commit_inputs()
        node=nodes.effective(self.graph)['nodes'][identity];spec=nodes.specs(node['type'])[key]
        current=node.get('parameters',{}).get(key,node_defaults.value(spec)) or ''
        multiple=spec['type']=='StringVector'
        start=current[0] if multiple and current else current if isinstance(current,str) else ''
        start=os.path.expandvars(os.path.expanduser(start))
        if not os.path.isfile(start):start=os.path.dirname(start) or getattr(self,'last_asset_directory','')
        filters=('OpenVDB (*.vdb);;All files (*)' if node['type']=='OpenVdbMap' else
                 'Textures (*.exr *.tx *.hdr *.png *.jpg *.jpeg *.tif *.tiff *.tga *.bmp *.dds *.pic *.rat);;All files (*)')
        chooser=QtWidgets.QFileDialog.getOpenFileNames if multiple else QtWidgets.QFileDialog.getOpenFileName
        path,_=chooser(self,'Choose '+key,start,filters)
        if not path:return
        self.last_asset_directory=os.path.dirname(path[0] if multiple else path)
        before=copy.deepcopy(self.graph)
        try:
            target=self.target(identity);target.setdefault('parameters',{})[key]=path
            target.setdefault('inputs',{}).pop(key,None)
            self.validate_draft();self.remember(before);self.rebuild()
        except (ValueError,TypeError) as exc:self.graph=before;self.error(exc)
    def commit_inputs(self):
        from shiboken2 import isValid
        for field in list(self.numeric_fields):
            if isValid(field):field.interpretText()
        self.table.itemDelegateForColumn(1).commit_pending()

    @QtCore.Slot(str,str)
    def numeric_focus(self,identity,key):
        if self.selected()!=identity:return
        for row in range(self.table.rowCount()):
            if self.table.item(row,0).text()==key:self.table.setCurrentCell(row,1);return

    @QtCore.Slot(str,str,int,float)
    def numeric_changed(self,identity,key,layer,value):
        if self.busy:return
        before=copy.deepcopy(self.graph)
        try:
            node=self.graph['nodes'][identity];spec=nodes.specs(node['type'])[key]
            value=shader_library.typed(value,spec)
            target=node if layer<0 else self.graph['overrides'][layer]
            if layer>=0 and target['node']!=identity:raise ValueError('Override targets another node')
            target.setdefault('parameters',{})[key]=value;target.setdefault('inputs',{}).pop(key,None)
            self.validate_draft();self.remember(before)
            # Update backing text without invoking the transient delegate path.
            if self.selected()==identity:
                blocker=QtCore.QSignalBlocker(self.table)
                for row in range(self.table.rowCount()):
                    if self.table.item(row,0).text()==key:
                        cell=self.table.item(row,1);cell.setText(json.dumps(value))
                        font=cell.font();font.setItalic(False);cell.setFont(font)
                        cell.setBackground(QtGui.QBrush());break
                del blocker
            self.edges()
        except (ValueError,TypeError,KeyError,IndexError) as exc:
            self.graph=before;self.info.setText(str(exc))

    def preview_draft(self):
        self.commit_inputs()
        material=copy.deepcopy(properties.read(self.item))
        material.update(node_graph=copy.deepcopy(self.graph),node_override=True)
        return material
    def error(self,exc): QtWidgets.QMessageBox.warning(self,'Node graph',str(exc))
    def selected(self): return next((item.identity for item in self.canvas.selectedItems() if isinstance(item,Node)),None)
    def rebuild(self,*args):
        selected=self.selected()
        if hasattr(self,'view'):self.view.cancel_wire()
        self.busy=True;self.pending=None;self.items={};self.links=[];self.canvas.clear()
        graph=nodes.effective(self.graph)
        self.output_label.setText('Output: '+graph['nodes'][graph['root']]['type'])
        for identity,value in graph['nodes'].items():
            item=Node(self,identity,value);self.items[identity]=item;self.canvas.addItem(item)
        self.edges();old=self.layers.currentIndex();self.layers.clear();self.layers.addItem('Base graph',-1)
        for index,layer in enumerate(self.graph.get('overrides',[])):
            self.layers.addItem(('On: ' if layer.get('enabled',True) else 'Off: ')+layer.get('name','Override'),index)
        self.layers.setCurrentIndex(min(max(0,old),self.layers.count()-1));self.busy=False
        if selected in self.items:self.items[selected].setSelected(True)
        self.canvas.setSceneRect(self.canvas.itemsBoundingRect().adjusted(-250,-250,250,250));self.inspect()
        self.material_preview.graph_changed(self.graph)
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
        self.material_preview.graph_changed(self.graph)
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
        self.commit_inputs()
        kind=self.kinds.currentText()
        if kind not in nodes.kinds():self.error('Choose a supported node from the search results');return
        try:defaults=node_defaults.parameters(kind)
        except ValueError as exc:self.error('Cannot initialize node defaults: '+str(exc));return
        before=copy.deepcopy(self.graph);identity='node_'+uuid.uuid4().hex[:12]
        visible=self.view.mapToScene(self.view.viewport().rect()).boundingRect()
        ports=sum(1 for key in nodes.specs(kind) if nodes.connectable(kind,key))
        shown=ports if self.show_all.isChecked() else min(ports,12)
        width=225; height=max(70,48+shown*21+(22 if shown<ports else 0))
        point=self.add_at or visible.center();self.add_at=None
        def clamp(x,y):
            return QtCore.QPointF(max(visible.left(),min(x,visible.right()-width)) if visible.width()>=width else visible.center().x()-width/2,
                                 max(visible.top(),min(y,visible.bottom()-height)) if visible.height()>=height else visible.center().y()-height/2)
        position=clamp(point.x()-width/2,point.y()-height/2)
        candidates=[position]
        for row in range(5):
            for column in range(5):
                candidates.append(clamp(visible.left()+column*max(0,visible.width()-width)/4,
                                        visible.top()+row*max(0,visible.height()-height)/4))
        def overlap(pos):
            bounds=QtCore.QRectF(pos,QtCore.QSizeF(width,height));total=0
            for item in self.items.values():
                intersection=bounds.intersected(item.sceneBoundingRect().adjusted(-12,-12,12,12))
                total+=max(0,intersection.width())*max(0,intersection.height())
            return total
        # Search only the visible area. Crowded views may overlap, never jump offscreen.
        position=min(candidates,key=overlap)
        self.graph['nodes'][identity]={'type':kind,'parameters':defaults,'inputs':{},'position':[position.x(),position.y()]}
        unconnected=copy.deepcopy(self.graph)
        if self.auto_connect.isChecked() and self.selected_input:
            target,key=self.selected_input
            if target in self.graph['nodes']:
                try:
                    self.target(target).setdefault('inputs',{})[key]=identity;self.validate_draft()
                except (ValueError,KeyError) as exc:
                    self.graph=unconnected;self.info.setText('Node added without a connection: '+str(exc))
        self.remember(before);self.rebuild();self.canvas.clearSelection();self.items[identity].setSelected(True)
    def browse_image(self):
        identity=self.selected()
        if not identity:self.error('Select a texture node first');return
        kind=self.graph['nodes'][identity]['type'];schema=nodes.specs(kind)
        filenames=[key for key,spec in schema.items() if file_parameter(spec)]
        if not filenames:self.error('This node has no file input');return
        key=filenames[0]
        if len(filenames)>1:
            key,ok=QtWidgets.QInputDialog.getItem(self,'File input','Input',filenames,0,False)
            if not ok:return
        self.choose_node_file(identity,key)
    def property_menu(self,point):
        row=self.table.rowAt(point.y());identity=self.selected()
        if row<0 or not identity:return
        self.table.setCurrentCell(row,1)
        key=self.table.item(row,0).text();spec=nodes.specs(self.graph['nodes'][identity]['type'])[key]
        if spec['type']=='SceneObject*':return
        menu=QtWidgets.QMenu(self);browse=None
        if file_parameter(spec):browse=menu.addAction('Browse files...')
        reset=menu.addAction('Reset input to inherited value')
        action=menu.exec_(self.table.viewport().mapToGlobal(point))
        if action is None:return
        if browse is not None and action==browse:self.choose_node_file(identity,key)
        elif action==reset:self.reset_input()
    def check_assets(self):
        self.commit_inputs()
        from .textures import source_tiles
        missing=[];checked=0
        graph=nodes.effective(self.graph)
        for identity,node in graph['nodes'].items():
            for key,spec in nodes.specs(node['type']).items():
                if not file_parameter(spec):continue
                value=node.get('parameters',{}).get(key,node_defaults.value(spec))
                for path in value if isinstance(value,list) else [value]:
                    if not path:continue
                    checked+=1
                    try:exists=bool(source_tiles(path))
                    except (OSError,ValueError):exists=False
                    if not exists:missing.append(node.get('label',node['type'])+' / '+key+': '+path)
        dialog=QtWidgets.QMessageBox(self)
        dialog.setWindowTitle('Graph asset files')
        dialog.setIcon(QtWidgets.QMessageBox.Warning if missing else QtWidgets.QMessageBox.Information)
        dialog.setText(str(len(missing))+' missing file inputs out of '+str(checked)+'.' if missing else 'All '+str(checked)+' assigned file inputs were found.')
        dialog.setInformativeText('Checks the current graph and enabled overrides, including UDIM tiles. External referenced materials are not included.')
        if missing:dialog.setDetailedText('\n'.join(missing))
        dialog.exec_()
    def reset_input(self):
        self.commit_inputs()
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
    def output(self,identity=None):
        self.commit_inputs()
        if not isinstance(identity,str):identity=self.selected()
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
        self.busy=True;self.numeric_fields=[];self.table.setRowCount(0);identity=self.selected()
        self.property_title.setText(self.graph['nodes'][identity].get('label',self.graph['nodes'][identity]['type']) if identity else 'Select a node')
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
                inherited=key not in node.get('parameters',{})
                value=node.get('parameters',{}).get(key,node_defaults.value(spec))
                cell=QtWidgets.QTableWidgetItem('' if value is None else json.dumps(value))
                if key in node.get('inputs',{}):cell.setBackground(QtGui.QColor('#294757'));label.setToolTip('Connected from '+node['inputs'][key]+'; editing this value replaces the connection')
                if inherited:
                    font=cell.font();font.setItalic(True);cell.setFont(font)
                cell.setToolTip(('Renderer default; edit to override. ' if inherited else '')+str(spec.get('comment',''))+' Default: '+str(spec.get('default',spec.get('default_value',''))))
                limits=[str(spec[k]) for k in ('min','max') if k in spec]
                if limits:
                    cell.setToolTip(cell.toolTip()+' Allowed range: '+str(spec.get('min','unbounded'))+' to '+str(spec.get('max','unbounded')))
                if file_parameter(spec):cell.setToolTip(cell.toolTip()+' Click to browse for a file. Press F2 to type or paste a path, including <UDIM> patterns.')
                self.table.setItem(row,0,label);self.table.setItem(row,1,cell)
                if spec['type'] in ('Float','Double') and not spec.get('enum'):
                    field=NumericField(identity,key,self.layers.currentData() if self.layers.currentData() is not None else -1,spec,value,self.table)
                    field.setToolTip(cell.toolTip());field.changed.connect(self.numeric_changed);field.focused.connect(self.numeric_focus)
                    cell.setFlags(cell.flags() & ~QtCore.Qt.ItemIsEditable)
                    self.table.setCellWidget(row,1,field);self.numeric_fields.append(field)
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
                spec=nodes.specs(self.graph['nodes'][identity]['type'])[key]
                try:value=shader_library.typed(json.loads(text),spec)
                except ValueError as exc:raise ValueError(key+': '+str(exc))
                target.setdefault('parameters',{})[key]=value
                target.setdefault('inputs',{}).pop(key,None)
            self.validate_draft();self.remember(old)
            # Scalar edits do not change the node layout. Keep the active Qt
            # cell editor alive until its delegate has finished committing.
            self.edges();self.material_preview.graph_changed(self.graph)
        except (ValueError,TypeError) as exc:
            self.graph=old
            # No modal dialog or table destruction inside setModelData: both
            # can re-enter Qt while it still owns the committing editor.
            self.info.setText(str(exc))
            QtCore.QTimer.singleShot(0,self.inspect)
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
    def inspect_materialx(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Inspect MaterialX','','MaterialX (*.mtlx)')
        if not path:return
        try:
            result=materialx.inspect_document(path)
            dialog=QtWidgets.QMessageBox(self);dialog.setWindowTitle('MaterialX compatibility')
            supported=sum(v['status']=='translatable' for v in result['materials'])
            dialog.setText(str(supported)+' of '+str(len(result['materials']))+' surface materials translate with the current bridge.')
            dialog.setInformativeText('This checks translation, not rendered equivalence. External shader-source implementations are not executed.')
            dialog.setDetailedText(json.dumps(result,indent=2));dialog.exec_()
        except (ValueError,OSError) as exc:self.error(exc)
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
    def save(self,close=True):
        self.commit_inputs()
        try:
            graph=nodes.validate(self.graph);root=graph['nodes'][graph['root']]
            settings=properties.read(self.item)
            settings[self.graph_key]=self.graph
            if self.materialx_override:
                settings['materialx_override']=True
            else:
                from .material_override import synchronize
                settings=synchronize(settings,self.graph)
            properties.write(self.item,settings)
            self.info.setText('Applied output material: '+root['type'])
            if close:self.accept()
        except ValueError as exc: self.error(exc)
