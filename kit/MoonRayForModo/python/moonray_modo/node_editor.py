"""Visual node authoring with editable inputs and non-destructive override layers.

The editor is a window of its own that does not block Modo: it can sit on another monitor
while the scene is worked on. open_editor() shows it. The material in the scene is the one
copy of the graph: every edit here is written to it through an undoable command, and an edit
made elsewhere, such as in the material's properties form, is shown here.
"""
import copy
import json
import os
import uuid
from PySide2 import QtCore,QtGui,QtWidgets
from . import nodes,materialx,properties,shader_library,node_defaults
from .node_widgets import (GraphView,ParameterDelegate,NumericField,ChoiceField,IntegerField,VectorField,TextField,NameField,RampField,ramp_groups,QuickAdd,key_of,describe,hint,COLORS,HEADERS,NODE_BODY,NODE_EDGE,ACCENT,
                           TEXT,TEXT_PORT,TEXT_DIM,GRID,MENU_STYLE,curve,file_parameter,tint_value)
import lx


WIDTH,HEADER,ROW=190,24,20
# Inputs shown on a node that has more; the rest are a click away.
SHOWN=6


def socket_category(editor,identity,key):
    kind=editor.graph['nodes'][identity]['type']
    if key is None:return nodes.category(kind)
    spec=nodes.specs(kind)[key]
    if spec['type']=='SceneObject*':
        return {'INTERFACE_NORMALMAP':'normal','INTERFACE_MAP':'map','INTERFACE_DISPLACEMENT':'displacement'}.get(spec.get('interface'),'material')
    return 'map'


def rounded(width,height,radius,square_bottom=False):
    path=QtGui.QPainterPath();path.addRoundedRect(QtCore.QRectF(0,0,width,height),radius,radius)
    if square_bottom:
        lower=QtGui.QPainterPath();lower.addRect(QtCore.QRectF(0,height-radius,width,radius));path=path.united(lower)
    return path


def text(parent,words,color,x,y,width,size=-1):
    """A label cut short to fit, with the whole of it as its tooltip."""
    item=QtWidgets.QGraphicsSimpleTextItem(parent)
    font=item.font()
    if size:font.setPointSizeF(max(6.0,font.pointSizeF()+size))
    item.setFont(font);item.setBrush(QtGui.QColor(color))
    item.setText(QtGui.QFontMetrics(font).elidedText(words,QtCore.Qt.ElideRight,int(width)))
    if item.text()!=words:item.setToolTip(words)
    item.setPos(x,y)
    return item


class Socket(QtWidgets.QGraphicsEllipseItem):
    def __init__(self,editor,identity,key,parent):
        super().__init__(-5,-5,10,10,parent)
        self.is_socket=True
        self.setCursor(QtCore.Qt.CrossCursor)
        self.editor,self.identity,self.key=editor,identity,key
        self.setBrush(QtGui.QColor(COLORS[socket_category(editor,identity,key)]));self.setPen(QtGui.QPen(QtGui.QColor(NODE_EDGE),1.5))
        self.setToolTip('Drag to an input to connect' if key is None else key+': drag a wire here, or drag from here to empty canvas to add a node. Right-click to disconnect.')
    def mousePressEvent(self,event):
        self.editor.socket(self.identity,self.key)
        event.accept()


class Toggle(QtWidgets.QGraphicsSimpleTextItem):
    """The line at the foot of a node that shows or hides the rest of its inputs."""
    def __init__(self,editor,identity,words,parent):
        super().__init__(words,parent)
        self.editor,self.identity=editor,identity
        self.setBrush(QtGui.QColor(TEXT_DIM));self.setCursor(QtCore.Qt.PointingHandCursor)
    def mousePressEvent(self,event):
        event.accept()
        # The node is rebuilt, and this item with it, once the click has been dealt with.
        QtCore.QTimer.singleShot(0,lambda editor=self.editor,identity=self.identity:editor.toggle_expanded(identity))


class Node(QtWidgets.QGraphicsRectItem):
    """A node, made of Qt's own shapes. The item itself paints nothing, so that Qt does not
    draw its dashed selection box; the outline changes colour instead."""
    def __init__(self,editor,identity,value):
        kind=value['type'];category=nodes.category(kind)
        ports=[key for key in nodes.specs(kind) if nodes.connectable(kind,key)]
        authored=list(value.get('inputs',{}))
        ports=authored+[key for key in ports if key not in authored]
        expanded=identity in editor.expanded or editor.show_all.isChecked()
        shown=ports if expanded else ports[:max(SHOWN,len(authored))]
        self.hidden_ports=len(ports)-len(shown)
        foot=bool(self.hidden_ports) or (identity in editor.expanded and len(ports)>SHOWN)
        height=HEADER+len(shown)*ROW+(ROW if foot else 0)+8
        super().__init__(0,0,WIDTH,height)
        self.editor,self.identity=editor,identity
        self.setFlags(self.ItemIsMovable|self.ItemIsSelectable|self.ItemSendsGeometryChanges|self.ItemHasNoContents)
        self.body=QtWidgets.QGraphicsPathItem(rounded(WIDTH,height,6),self)
        self.body.setBrush(QtGui.QColor(NODE_BODY));self.body.setPen(QtGui.QPen(QtGui.QColor(NODE_EDGE),1))
        header=QtWidgets.QGraphicsPathItem(rounded(WIDTH,HEADER,6,square_bottom=True),self)
        header.setBrush(QtGui.QColor(HEADERS[category]));header.setPen(QtGui.QPen(QtCore.Qt.NoPen))
        role='OUTPUT' if identity==editor.graph['root'] else 'DISPLACEMENT' if identity==editor.graph.get('displacement') else ''
        # A ramp left in MoonRay's default space slides over the surface as the camera moves; say so on the node.
        if follows_camera(value):role='FOLLOWS CAMERA'
        badge=None
        if role:
            badge=text(self,role,TEXT,0,6,90,size=-2);badge.setPos(WIDTH-badge.boundingRect().width()-12,6);badge.setOpacity(.8)
        title=text(self,value.get('label',kind),TEXT,10,4,WIDTH-24-(badge.boundingRect().width()+8 if badge else 0))
        if not title.toolTip():title.setToolTip(kind)
        self.sockets={None:Socket(editor,identity,None,self)};self.sockets[None].setPos(WIDTH,HEADER/2)
        for index,key in enumerate(shown):
            y=HEADER+4+index*ROW
            label=text(self,key.replace('_',' '),TEXT if key in authored else TEXT_PORT,12,y+2,WIDTH-22,size=-1);label.setToolTip(key)
            socket=Socket(editor,identity,key,self);socket.setPos(0,y+ROW/2);self.sockets[key]=socket
        if foot:
            words=('+ %d more inputs'%self.hidden_ports) if self.hidden_ports else '- fewer inputs'
            toggle=Toggle(editor,identity,words,self);font=toggle.font();font.setPointSizeF(max(6.0,font.pointSizeF()-1));toggle.setFont(font)
            toggle.setPos(12,HEADER+6+len(shown)*ROW)
        self.setPos(*value.get('position',[0,0]))
    def itemChange(self,change,value):
        if change==self.ItemPositionHasChanged and hasattr(self,'identity') and not self.editor.busy:
            self.editor.graph['nodes'][self.identity]['position']=[self.pos().x(),self.pos().y()]
            self.editor.edges()
        elif change==self.ItemSelectedHasChanged and hasattr(self,'body'):
            self.body.setPen(QtGui.QPen(QtGui.QColor(ACCENT),2) if value else QtGui.QPen(QtGui.QColor(NODE_EDGE),1))
            self.setZValue(1 if value else 0)
        return super().itemChange(change,value)


def owner_name(item):
    """What a material belongs to: the object its mask is for, or else the mask itself."""
    mask=item.parent
    if mask is None or mask.type!='mask':return 'All objects'
    try:
        # A mask can be tied to an item rather than to a material tag.
        linked=mask.itemGraph('shadeLoc').forward()
        if linked:return ', '.join(entry.name for entry in linked)
    except Exception:pass
    # A mask made by Assign MoonShine Material is named for its mesh.
    name=mask.name
    return name[len('MoonShine - '):] if name.startswith('MoonShine - ') else name


def material_meshes(item):
    """The meshes a material is on: the item its mask is tied to, or those that use the mask's
    material tag. With nothing to go on, every mesh in the scene."""
    import modo
    scene=modo.Scene();mask=item.parent
    everything=list(scene.items('mesh'))
    if mask is None or mask.type!='mask':return everything
    try:
        linked=[entry for entry in mask.itemGraph('shadeLoc').forward() if entry.type=='mesh']
        if linked:return linked
    except Exception:pass
    try:tag=mask.channel('ptag').get()
    except Exception:tag=''
    if not tag:return everything
    found=[]
    for mesh in everything:
        try:
            inner=mesh.geometry.internalMesh
            if tag in [inner.PTagByIndex(lx.symbol.i_PTAG_MATR,index) for index in range(inner.PTagCount(lx.symbol.i_PTAG_MATR))]:found.append(mesh)
        except Exception:pass
    return found or everything


def uv_choices(item):
    """The UV maps to choose from for a material, as (label, name): those of the meshes it is on."""
    names=[]
    try:
        for mesh in material_meshes(item):
            for uv in mesh.geometry.vmaps.uvMaps:
                if uv.name not in names:names.append(uv.name)
    except Exception:pass
    return [('First UV map','')]+[(name,name) for name in sorted(names,key=str.casefold)]


def graph_materials():
    """The scene's materials that have a MoonShine graph, as (label, item), in name order."""
    import modo
    from . import material_override
    found=[]
    try:
        scene=modo.Scene()
        candidates=[item for item in scene.items('advancedMaterial',superType=True) if item.type!='material.moonrayMaterialX']
    except Exception:return found
    for item in candidates:
        try:
            if item.type=='advancedMaterial' and not material_override.enabled(properties.read(item)):continue
            found.append((owner_name(item)+'  /  '+item.name,item))
        except Exception:pass
    return sorted(found,key=lambda entry:entry[0].casefold())


def follows_camera(node):
    """A ramp or gradient laid out in the camera's space, which MoonRay calls render space and uses by default."""
    return node['type'] in ('RampMap','GradientMap') and int(node.get('parameters',{}).get('space',0)) in (0,1)


# The open editors, by the material they edit, so that asking for one again brings it forward.
_open={}


def open_editor(item,materialx_override=False):
    """Show the graph editor for a material without blocking Modo."""
    from shiboken2 import isValid
    key=(item.id,bool(materialx_override))
    editor=_open.get(key)
    if editor is not None and isValid(editor) and editor.isVisible():
        editor.raise_();editor.activateWindow();return editor
    editor=_open[key]=Editor(item,materialx_override)
    editor.finished.connect(lambda *_,key=key:_open.pop(key,None))
    editor.show();editor.raise_();editor.activateWindow()
    return editor


class Editor(QtWidgets.QDialog):
    def __init__(self,item,materialx_override=False):
        # A window in its own right, above Modo's but not blocking it.
        super().__init__(QtWidgets.QApplication.activeWindow())
        self.setWindowFlags(QtCore.Qt.Window|QtCore.Qt.WindowTitleHint|QtCore.Qt.WindowSystemMenuHint|QtCore.Qt.WindowMinMaxButtonsHint|QtCore.Qt.WindowCloseButtonHint)
        self.setModal(False);self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.setMinimumSize(900,560)
        from .preview_diagnostics import record
        record('Graph editor opened')
        self.numeric_fields=[]
        self.item=item;self.materialx_override=materialx_override;self.graph_key="materialx_graph" if materialx_override else "node_graph";settings=properties.read(item)
        self.graph=copy.deepcopy(settings.get(self.graph_key) or nodes.from_material(item))
        self.pending=None;self.items={};self.links=[];self.busy=False
        # writing: this window is the one changing the material. live: edits are written as made.
        self.writing=False;self.live=False
        self.undo_states=[];self.redo_states=[];self.selected_input=None;self.add_at=None
        # The nodes showing all of their inputs. A matter of the view, not of the graph.
        self.expanded=set()
        self.setWindowTitle(('MaterialX Override - ' if materialx_override else 'MoonShine Graph - ')+item.name);self.resize(1280,800)
        layout=QtWidgets.QVBoxLayout(self);layout.setContentsMargins(6,6,6,6);layout.setSpacing(4)
        toolbar=QtWidgets.QHBoxLayout();toolbar.setSpacing(4);layout.addLayout(toolbar)
        self.kinds=QtWidgets.QComboBox(self);self.kinds.addItems(nodes.kinds());self.kinds.hide()
        self.menus=[]
        def menu_button(title,actions):
            button=QtWidgets.QToolButton();button.setText(title);button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
            button.setMinimumWidth(button.fontMetrics().horizontalAdvance(title)+36)
            menu=QtWidgets.QMenu(button);menu.setStyleSheet(MENU_STYLE);self.menus.append(menu)
            for label,callback in actions:
                if label is None:menu.addSeparator()
                else:menu.addAction(label,callback)
            button.setMenu(menu);toolbar.addWidget(button);return menu
        def checkable(menu,label,checked):
            # Made first and then added: an action a menu makes for a label cannot be used later in Modo's Qt.
            action=QtWidgets.QAction(label,self);action.setCheckable(True);action.setChecked(checked);menu.addAction(action)
            return action
        menu_button('Graph', [('Import MaterialX...',self.import_file),('Export Definitions...',self.export_file),('Inspect MaterialX Support...',self.inspect_materialx),
                    (None,None),('Check Asset Files...',self.check_assets),('Fix Ramps That Follow the Camera',self.fix_camera_ramps),
                    (None,None),('Add Override Layer...',self.add_override),('Toggle Override Layer',self.toggle_override)])
        menu_button('Node', [('Add Node...\tTab',lambda:self.quick_add()),('Duplicate\tCtrl+D',self.duplicate),('Delete\tDel',self.remove),
                    (None,None),('Set as Material Output',self.output),('Set / Clear Displacement Output',self.displacement_output),
                    (None,None),('Connect Input...',self.connect_selected),('Disconnect Input...',self.disconnect),
                    ('Browse Image...',self.browse_image),('Reset Selected Input',self.reset_input)])
        view_menu=menu_button('View',[('Frame Selected\tF',self.frame),('Frame All\tA',lambda:self.frame(everything=True)),('Arrange Nodes',self.arrange_nodes),(None,None)])
        self.snap=checkable(view_menu,'Snap to Grid',True)
        self.auto_connect=checkable(view_menu,'Connect New Nodes to the Selected Input',True)
        self.show_all=checkable(view_menu,'Show All Inputs on Every Node',False)
        self.show_library=checkable(view_menu,'Node Library',True)
        self.show_all.toggled.connect(self.rebuild)
        # Every material with a graph, named with the object it belongs to; choosing one moves
        # the editor to it.
        self.material_picker=QtWidgets.QComboBox();self.material_picker.setMinimumWidth(260)
        self.material_picker.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)
        self.material_picker.setToolTip('The material being edited. Choose another to switch to it.')
        self.material_picker.activated.connect(self.switch_material)
        toolbar.addWidget(self.material_picker);self.material_picker.setVisible(not materialx_override)
        self.fill_materials()
        for label,tip,callback in [('Undo','Ctrl+Z',self.undo),('Redo','Ctrl+Y',self.redo)]:
            button=QtWidgets.QToolButton();button.setText(label);button.setToolTip(tip);button.setAutoRaise(True);button.clicked.connect(callback);toolbar.addWidget(button)
        toolbar.addStretch(1)
        self.output_label=QtWidgets.QLabel();self.output_label.setEnabled(False);self.output_label.setToolTip('The material that is rendered.');toolbar.addWidget(self.output_label)
        splitter=QtWidgets.QSplitter();layout.addWidget(splitter,1)
        self.build_node_browser(splitter)
        self.show_library.toggled.connect(self.library.setVisible)
        self.canvas=QtWidgets.QGraphicsScene(self);self.view=GraphView(self,self.canvas);splitter.addWidget(self.view)
        inspector=QtWidgets.QSplitter(QtCore.Qt.Vertical);splitter.addWidget(inspector)
        pane=QtWidgets.QWidget();right=QtWidgets.QVBoxLayout(pane);right.setContentsMargins(0,0,0,0);right.setSpacing(4);inspector.addWidget(pane)
        splitter.setSizes([200,760,320]);splitter.setStretchFactor(1,1)
        self.property_title=QtWidgets.QLabel('Properties');font=self.property_title.font();font.setBold(True);self.property_title.setFont(font);right.addWidget(self.property_title)
        self.property_search=QtWidgets.QLineEdit();self.property_search.setClearButtonEnabled(True);self.property_search.setPlaceholderText('Filter properties');right.addWidget(self.property_search);self.property_search.textChanged.connect(self.filter_properties)
        self.layers=QtWidgets.QComboBox();self.layers.setToolTip('The override layer that edits go to');right.addWidget(self.layers)
        self.table=QtWidgets.QTableWidget(0,2);self.table.horizontalHeader().hide();self.table.horizontalHeader().setStretchLastSection(True);self.table.verticalHeader().hide();self.table.setShowGrid(False);self.table.setAlternatingRowColors(True);right.addWidget(self.table,1)
        # With nothing selected there is only the title, not an empty table.
        self.property_hint=QtWidgets.QLabel('Select a node to edit its inputs.');self.property_hint.setEnabled(False);self.property_hint.setAlignment(QtCore.Qt.AlignTop);right.addWidget(self.property_hint,1)
        self.table.setItemDelegateForColumn(1,ParameterDelegate(self))
        self.table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.property_menu)
        self.property_help=QtWidgets.QLabel('');self.property_help.setWordWrap(True);self.property_help.setEnabled(False)
        self.property_help.setAlignment(QtCore.Qt.AlignTop);self.property_help.setMinimumHeight(self.fontMetrics().lineSpacing()*3);right.addWidget(self.property_help)
        self.table.setMouseTracking(True);self.table.cellEntered.connect(self.describe_row);self.table.currentCellChanged.connect(lambda row,*_:self.describe_row(row))
        from .material_preview import Panel
        self.material_preview=Panel(self.item,self.preview_draft,self,embedded=True);inspector.addWidget(self.material_preview);inspector.setSizes([420,340])
        self.finished.connect(lambda *_:self.material_preview.shutdown())
        from . import property_notifications
        property_notifications.watchers.append(self.scene_changed)
        self.finished.connect(lambda *_:self.stop_watching())
        footer=QtWidgets.QHBoxLayout();layout.addLayout(footer)
        self.info=QtWidgets.QLabel('Tab or double-click adds a node. Drag between sockets to connect.')
        # A long message is cut short rather than widening the window.
        self.info.setSizePolicy(QtWidgets.QSizePolicy.Ignored,QtWidgets.QSizePolicy.Preferred)
        self.info.setToolTip('Wheel zooms. Middle drag, or Alt and drag, pans. F frames the selection, A everything. Tab or double-click adds a node; drag an input to empty canvas to add the node that feeds it. Ctrl+D duplicates, Delete removes, Ctrl+Z undoes. Right-click a socket or wire to disconnect.')
        footer.addWidget(self.info,1)
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close);footer.addWidget(buttons)
        buttons.button(QtWidgets.QDialogButtonBox.Close).setToolTip('Edits are written to the material as they are made; Ctrl+Z here or in Modo undoes them')
        buttons.rejected.connect(self.reject)
        self.canvas.selectionChanged.connect(self.inspect);self.table.itemChanged.connect(self.edited);self.layers.currentIndexChanged.connect(self.inspect)
        for button in self.findChildren(QtWidgets.QPushButton):
            button.setAutoDefault(False);button.setDefault(False)
        self.rebuild();self.frame_output()
        self.live=True
    def fill_materials(self):
        """List the scene's graph materials, with this one chosen."""
        entries=graph_materials()
        if self.item.id not in [item.id for _,item in entries]:entries.insert(0,(owner_name(self.item)+'  /  '+self.item.name,self.item))
        blocker=QtCore.QSignalBlocker(self.material_picker)
        self.material_picker.clear()
        for label,item in entries:self.material_picker.addItem(label,item.id)
        self.material_picker.setCurrentIndex(max(0,self.material_picker.findData(self.item.id)))
        del blocker
    def changeEvent(self,event):
        # Materials may have been added or renamed while the editor was in the background.
        if event.type()==QtCore.QEvent.ActivationChange and self.isActiveWindow() and hasattr(self,'material_picker'):
            try:self.fill_materials()
            except Exception:pass
        super().changeEvent(event)
    def switch_material(self,index):
        """Move the editor to the material chosen in the list."""
        import modo
        identity=self.material_picker.itemData(index)
        if identity==self.item.id:return
        try:item=modo.Scene().item(identity)
        except LookupError:self.fill_materials();self.info.setText('That material is no longer in the scene.');return
        self.commit_inputs()
        geometry=self.geometry()
        editor=open_editor(item)
        editor.setGeometry(geometry)
        # This window goes once the click that chose the material has been dealt with.
        QtCore.QTimer.singleShot(0,self.reject)
    def keyPressEvent(self,event):
        if event.key() in (QtCore.Qt.Key_Return,QtCore.Qt.Key_Enter):
            self.commit_inputs()
            event.accept();return
        super().keyPressEvent(event)
    def build_node_browser(self,splitter):
        pane=self.library=QtWidgets.QWidget();layout=QtWidgets.QVBoxLayout(pane);layout.setContentsMargins(0,0,0,0);layout.setSpacing(4)
        self.node_search=QtWidgets.QLineEdit();self.node_search.setClearButtonEnabled(True);self.node_search.setPlaceholderText('Search nodes');layout.addWidget(self.node_search)
        self.node_tree=QtWidgets.QTreeWidget();self.node_tree.setHeaderHidden(True);self.node_tree.setIndentation(12);layout.addWidget(self.node_tree,1)
        self.node_tree.setToolTip('Click a node to add it')
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
            if key_of(self.table,row)==key:self.table.setCurrentCell(row,1);return

    @QtCore.Slot(str,str,int,float)
    def numeric_changed(self,identity,key,layer,value):
        self.set_value(identity,key,layer,value)

    @QtCore.Slot(str,str,int,int)
    def choice_changed(self,identity,key,layer,value):
        try:switch=nodes.specs(self.graph['nodes'][identity]['type'])[key]['type']=='Bool'
        except KeyError:return
        self.set_value(identity,key,layer,bool(value) if switch else int(value))

    def describe_row(self,row,*args):
        """Say what the property under the pointer, or the one being edited, is."""
        identity=self.selected()
        if identity is None or not 0<=row<self.table.rowCount():return
        try:self.property_help.setText(describe(key_of(self.table,row),nodes.specs(self.graph['nodes'][identity]['type'])[key_of(self.table,row)]))
        except KeyError:pass

    def eventFilter(self,watched,event):
        # A property control says which row it is in when the pointer or the keyboard reaches it.
        row=getattr(watched,'property_row',None)
        if row is not None and event.type() in (QtCore.QEvent.Enter,QtCore.QEvent.FocusIn):self.describe_row(row)
        return super().eventFilter(watched,event)

    def place_field(self,row,cell,field):
        """Put a control that stays in place into a row of the property list."""
        field.setToolTip('');field.property_row=row;field.installEventFilter(self)
        # The control covers the cell beneath it, swatch and text included.
        field.setAutoFillBackground(True)
        for child in field.findChildren(QtWidgets.QWidget):child.property_row=row;child.installEventFilter(self)
        cell.setFlags(cell.flags() & ~QtCore.Qt.ItemIsEditable)
        # The control shows the value. Left in the cell as well, the old text shows through behind it.
        cell.setText('');cell.setData(QtCore.Qt.DecorationRole,None);cell.setBackground(QtGui.QBrush())
        self.table.setCellWidget(row,1,field)

    def object_changed(self,identity,key,layer,value):
        self.set_value(identity,key,layer,value)

    def set_value(self,identity,key,layer,value):
        """Take a value from one of the property controls that stay in place."""
        if self.busy:return
        before=copy.deepcopy(self.graph)
        try:
            node=self.graph['nodes'][identity];spec=nodes.specs(node['type'])[key]
            value=shader_library.typed(value,spec)
            target=node if layer<0 else self.graph['overrides'][layer]
            if layer>=0 and target['node']!=identity:raise ValueError('Override targets another node')
            target.setdefault('parameters',{})[key]=value;target.setdefault('inputs',{}).pop(key,None)
            if layer<0:
                # One of the material's controls may stand for several nodes, such as one picture read at three scales.
                for control in self.graph.get('controls',[]):
                    if control.get('node')==identity and control.get('key')==key:
                        for other in control.get('also',[]):
                            if other in self.graph['nodes']:self.graph['nodes'][other].setdefault('parameters',{})[key]=copy.deepcopy(value)
            self.validate_draft();self.remember(before)
            # Update backing text without invoking the transient delegate path.
            if self.selected()==identity:
                blocker=QtCore.QSignalBlocker(self.table)
                for row in range(self.table.rowCount()):
                    if key_of(self.table,row)==key:
                        cell=self.table.item(row,1);field=self.table.cellWidget(row,1)
                        font=cell.font();font.setItalic(False);cell.setFont(font)
                        cell.setBackground(QtGui.QBrush())
                        if field is not None:
                            # The control shows the value; the cell beneath it stays empty.
                            cell.setText('');tint_value(field,value,spec,node['type'],key)
                        else:
                            cell.setText(json.dumps(value))
                            self.table.itemDelegateForColumn(1).decorate(cell,spec,value)
                        break
                del blocker
            self.edges()
        except (ValueError,TypeError,KeyError,IndexError) as exc:
            self.graph=before;self.info.setText(str(exc))

    def preview_draft(self):
        self.commit_inputs()
        material=copy.deepcopy(properties.read(self.item))
        material.update(node_graph=copy.deepcopy(self.graph),node_override=True)
        return material
    def fix_camera_ramps(self):
        """Lay every ramp and gradient that follows the camera out on its object instead."""
        found=[key for key,node in self.graph['nodes'].items() if follows_camera(node)]
        if not found:self.info.setText('No ramp or gradient in this graph follows the camera.');return
        before=copy.deepcopy(self.graph)
        for key in found:self.graph['nodes'][key].setdefault('parameters',{})['space']=nodes.SPACE_OBJECT
        self.remember(before);self.rebuild()
        self.info.setText('%d ramp%s now stay%s on the object.'%(len(found),'' if len(found)==1 else 's','s' if len(found)==1 else ''))
    def stop_watching(self):
        from . import property_notifications
        if self.scene_changed in property_notifications.watchers:property_notifications.watchers.remove(self.scene_changed)
    def error(self,exc): QtWidgets.QMessageBox.warning(self,'Node graph',str(exc))
    def selected(self): return next((item.identity for item in self.canvas.selectedItems() if isinstance(item,Node)),None)
    def selected_nodes(self): return [item.identity for item in self.canvas.selectedItems() if isinstance(item,Node)]
    def rebuild(self,*args):
        selected=self.selected()
        if hasattr(self,'view'):self.view.cancel_wire()
        self.busy=True;self.pending=None;self.items={};self.links=[];self.canvas.clear()
        graph=nodes.effective(self.graph)
        self.output_label.setText('Output: '+graph['nodes'][graph['root']]['type'])
        for identity,value in graph['nodes'].items():
            item=Node(self,identity,value);self.items[identity]=item;self.canvas.addItem(item)
        self.edges();old=self.layers.currentIndex();self.layers.clear();self.layers.addItem('Base graph',-1)
        # The layer chooser is only there when there is a layer to choose.
        self.layers.setVisible(bool(self.graph.get('overrides')))
        for index,layer in enumerate(self.graph.get('overrides',[])):
            self.layers.addItem(('On: ' if layer.get('enabled',True) else 'Off: ')+layer.get('name','Override'),index)
        self.layers.setCurrentIndex(min(max(0,old),self.layers.count()-1));self.busy=False
        if selected in self.items:self.items[selected].setSelected(True)
        # Room on every side, so the graph can be panned freely.
        self.canvas.setSceneRect(self.canvas.itemsBoundingRect().adjusted(-3000,-3000,3000,3000));self.inspect()
        moving=sum(1 for node in graph['nodes'].values() if follows_camera(node))
        if moving:self.info.setText('%d ramp%s follow%s the camera. Graph > Fix Ramps That Follow the Camera puts %s on the object.'%(
            moving,'' if moving==1 else 's','s' if moving==1 else '','it' if moving==1 else 'them'))
        self.material_preview.graph_changed(self.graph);self.publish_draft()
    def edges(self):
        if not hasattr(self,'canvas'): return
        for item in self.links:
            if item.scene(): self.canvas.removeItem(item)
        self.links=[]
        graph=nodes.effective(self.graph)
        for identity,node in graph['nodes'].items():
            if identity not in self.items: continue
            for key,source in node.get('inputs',{}).items():
                if source not in self.items: continue
                a=self.items[source].sockets[None].scenePos()
                target=self.items[identity];b=target.sockets[key].scenePos() if key in target.sockets else target.scenePos()+QtCore.QPointF(0,20)
                path=curve(a,b)
                # A wire takes the colour of what it carries.
                pen=QtGui.QPen(QtGui.QColor(COLORS[nodes.category(graph['nodes'][source]['type'])]),2);pen.setCapStyle(QtCore.Qt.RoundCap)
                edge=self.canvas.addPath(path,pen);edge.setZValue(-1);edge.connection=(identity,key);edge.setToolTip('Right-click to disconnect '+key);self.links.append(edge)
    def remember(self,before):
        if before!=self.graph:self.undo_states.append(before);self.undo_states=self.undo_states[-50:];self.redo_states=[]
        self.material_preview.graph_changed(self.graph);self.publish_draft()
    def draft_settings(self):
        """The material's settings with the graph as it stands."""
        settings=copy.deepcopy(properties.read(self.item))
        settings[self.graph_key]=copy.deepcopy(self.graph)
        if self.materialx_override:settings['materialx_override']=True
        else:
            from .material_override import synchronize
            settings=synchronize(settings,settings[self.graph_key])
        return settings
    def stored_graph(self):
        return properties.read(self.item).get(self.graph_key) or nodes.from_material(self.item)
    def publish_draft(self):
        """Write the graph to the material, so the scene and the preview have it as it is edited."""
        if self.writing or not self.live:return
        try:
            if self.graph==self.stored_graph():return
            nodes.validate(self.graph)
            settings=self.draft_settings()
        except (ValueError,KeyError,TypeError,RuntimeError,LookupError):
            # A graph that is not yet valid is not written; the scene keeps the last valid one.
            return
        self.writing=True
        try:lx.eval('moonray.material.applyGraph {%s} %s'%(self.item.id,properties.encode(settings)))
        except (RuntimeError,LookupError) as exc:self.info.setText('Could not update the material: '+str(exc))
        finally:self.writing=False
    def scene_changed(self):
        """The material was written; if not by this window, show what it holds now."""
        from shiboken2 import isValid
        if self.writing or not isValid(self) or self.busy:return
        try:stored=self.stored_graph()
        except (RuntimeError,LookupError):return
        if stored==self.graph:return
        self.undo_states.append(copy.deepcopy(self.graph));self.undo_states=self.undo_states[-50:];self.redo_states=[]
        self.graph=copy.deepcopy(stored)
        self.writing=True
        try:self.rebuild()
        finally:self.writing=False
    def undo(self):
        if self.undo_states:self.redo_states.append(copy.deepcopy(self.graph));self.graph=self.undo_states.pop();self.rebuild()
    def redo(self):
        if self.redo_states:self.undo_states.append(copy.deepcopy(self.graph));self.graph=self.redo_states.pop();self.rebuild()
    def frame(self,everything=False):
        """Fit the selected nodes in the view, or all of them when none is selected."""
        if not self.items:return
        chosen=[] if everything else [self.items[identity] for identity in self.selected_nodes() if identity in self.items]
        bounds=QtCore.QRectF()
        for item in chosen or self.items.values():bounds=bounds.united(item.sceneBoundingRect())
        self.view.fitInView(bounds.adjusted(-60,-60,60,60),QtCore.Qt.KeepAspectRatio)
        # A small graph is not blown up to fill the window.
        scale=self.view.transform().m11()
        if scale>1.0:self.view.scale(1.0/scale,1.0/scale)
    def frame_output(self):
        """Show the graph from its output node, at a size its text can be read at. A small graph is shown whole; a large
        one, such as an imported MaterialX material, is too small to read when all of it is fitted in, so the view opens
        on the output and what feeds it, and the user zooms out from there."""
        if not self.items:return
        self.frame(everything=True)
        if self.view.transform().m11()>=.6:return
        output=self.items.get(self.graph.get('root'))
        if output is None:return
        self.view.resetTransform()
        # The output sits at the right of what feeds it: leave it a third of the way in from that side.
        centre=output.sceneBoundingRect().center()
        self.view.centerOn(centre.x()-self.view.viewport().width()/6.0,centre.y())
    def snap_selected(self):
        """Settle moved nodes onto the grid."""
        if not self.snap.isChecked():return
        for item in self.canvas.selectedItems():
            if isinstance(item,Node):item.setPos(round(item.pos().x()/GRID)*GRID,round(item.pos().y()/GRID)*GRID)
    def toggle_expanded(self,identity):
        if identity in self.expanded:self.expanded.discard(identity)
        else:self.expanded.add(identity)
        self.rebuild()
    def quick_add(self,scene_point=None,global_point=None,connect=None):
        """Open the add-node search at a point; connect names the input the new node will feed."""
        if scene_point is None:
            centre=self.view.viewport().rect().center();scene_point=self.view.mapToScene(centre);global_point=self.view.viewport().mapToGlobal(centre)
        def chosen(kind):
            self.add_at=scene_point
            if connect:self.selected_input=connect
            self.kinds.setCurrentText(kind);self.add(connect=bool(connect))
        self.popup=QuickAdd(self,nodes.kinds(),chosen);self.popup.open_at(global_point)
    def duplicate(self):
        chosen=self.selected_nodes()
        if not chosen:return
        self.commit_inputs();before=copy.deepcopy(self.graph);made=[]
        for identity in chosen:
            copied=copy.deepcopy(self.graph['nodes'][identity]);x,y=copied.get('position',[0,0])
            copied['position']=[x+2*GRID,y+2*GRID]
            new='node_'+uuid.uuid4().hex[:12];self.graph['nodes'][new]=copied;made.append(new)
        try:self.validate_draft()
        except ValueError as exc:self.graph=before;self.error(exc);return
        self.remember(before);self.rebuild();self.canvas.clearSelection()
        for identity in made:self.items[identity].setSelected(True)
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
    def add(self,connect=False):
        self.commit_inputs()
        kind=self.kinds.currentText()
        if kind not in nodes.kinds():self.error('Choose a supported node from the search results');return
        try:defaults=node_defaults.parameters(kind)
        except ValueError as exc:self.error('Cannot initialize node defaults: '+str(exc));return
        if kind in ('RampMap','GradientMap'):
            # MoonRay's own default lays these out in the camera's space, where they slide over
            # the surface as the camera moves; a new one starts fixed to the object instead.
            defaults=dict(defaults,space=nodes.SPACE_OBJECT)
        before=copy.deepcopy(self.graph);identity='node_'+uuid.uuid4().hex[:12]
        visible=self.view.mapToScene(self.view.viewport().rect()).boundingRect()
        ports=sum(1 for key in nodes.specs(kind) if nodes.connectable(kind,key))
        shown=ports if self.show_all.isChecked() else min(ports,SHOWN)
        width=WIDTH; height=HEADER+shown*ROW+(ROW if shown<ports else 0)+8
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
        if self.snap.isChecked():position=QtCore.QPointF(round(position.x()/GRID)*GRID,round(position.y()/GRID)*GRID)
        self.graph['nodes'][identity]={'type':kind,'parameters':defaults,'inputs':{},'position':[position.x(),position.y()]}
        unconnected=copy.deepcopy(self.graph)
        if (connect or self.auto_connect.isChecked()) and self.selected_input:
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
        key=key_of(self.table,row);spec=nodes.specs(self.graph['nodes'][identity]['type'])[key]
        if spec['type']=='SceneObject*':return
        menu=QtWidgets.QMenu(self);menu.setStyleSheet(MENU_STYLE)
        for label,what in ([('Browse Files...','browse')] if file_parameter(spec) else [])+[('Reset to Default','reset')]:
            action=QtWidgets.QAction(label,menu);action.setData(what);menu.addAction(action)
        action=menu.exec_(self.table.viewport().mapToGlobal(point))
        what=action.data() if action is not None else None
        if what=='browse':self.choose_node_file(identity,key)
        elif what=='reset':self.reset_input()
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
        key=key_of(self.table,row);before=copy.deepcopy(self.graph)
        try:
            target=self.target(identity);target.setdefault('parameters',{}).pop(key,None);target.setdefault('inputs',{}).pop(key,None)
            self.validate_draft();self.remember(before);self.rebuild()
        except ValueError as exc:self.graph=before;self.error(exc)
    def filter_properties(self,*args):
        query=self.property_search.text().casefold()
        hidden=getattr(self,'hidden_rows',set())
        for row in range(self.table.rowCount()):self.table.setRowHidden(row,row in hidden or query not in (self.table.item(row,0).text()+' '+key_of(self.table,row)).casefold())
    def edit_ramp(self,identity,key):
        """Open the ramp editor on a ramp's three lists, and write them back together."""
        from .ramp_editor import RampDialog
        if identity not in self.graph['nodes']:return
        self.commit_inputs()
        kind=self.graph['nodes'][identity]['type'];schema=nodes.specs(kind)
        group=ramp_groups(schema).get(key)
        if group is None:return
        title,keys=group[0],group[1:]
        node=nodes.effective(self.graph)['nodes'][identity]
        held=[node.get('parameters',{}).get(k,node_defaults.value(schema[k])) or [] for k in keys]
        if len({len(v) for v in held})!=1:held=[[],[],[]]
        dialog=RampDialog(kind+': '+title,held[0],held[1],held[2],schema[keys[1]]['type']=='RgbVector',self)
        if dialog.exec_()==QtWidgets.QDialog.Accepted:self.set_ramp(identity,key,*dialog.result())
    def set_ramp(self,identity,key,positions,values,modes):
        """Write a ramp's three lists as one change, so that they never disagree in length."""
        schema=nodes.specs(self.graph['nodes'][identity]['type']);keys=ramp_groups(schema)[key][1:]
        before=copy.deepcopy(self.graph)
        try:
            target=self.target(identity)
            for k,value in zip(keys,(positions,values,modes)):
                target.setdefault('parameters',{})[k]=shader_library.typed(value,schema[k])
                target.setdefault('inputs',{}).pop(k,None)
            self.validate_draft();self.remember(before);self.edges();self.inspect()
        except (ValueError,TypeError,KeyError) as exc:
            self.graph=before;self.info.setText(str(exc))
    def remove(self):
        chosen=self.selected_nodes()
        if not chosen: return
        if self.graph['root'] in chosen:
            if len(chosen)==1:self.error('Choose another output before deleting this node');return
            chosen=[identity for identity in chosen if identity!=self.graph['root']]
            self.info.setText('The output node was kept.')
        before=copy.deepcopy(self.graph)
        for identity in chosen:
            self.graph['nodes'].pop(identity);self.expanded.discard(identity)
            if self.graph.get('displacement')==identity:self.graph.pop('displacement')
        for node in self.graph['nodes'].values(): node['inputs']={k:v for k,v in node.get('inputs',{}).items() if v not in chosen}
        self.graph['overrides']=[v for v in self.graph.get('overrides',[]) if v['node'] not in chosen]
        for layer in self.graph['overrides']: layer['inputs']={k:v for k,v in layer.get('inputs',{}).items() if v not in chosen}
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
        # With no node chosen, the material's own controls: what its MaterialX file named for adjusting.
        controls=[] if identity else [c for c in self.graph.get('controls',[]) if c.get('node') in self.graph['nodes'] and c.get('key') in nodes.specs(self.graph['nodes'][c['node']]['type'])]
        self.property_title.setText(self.graph['nodes'][identity].get('label',self.graph['nodes'][identity]['type']) if identity else 'Material Controls' if controls else 'Properties')
        listed=bool(identity or controls)
        for widget,shown in ((self.table,listed),(self.property_search,listed),(self.property_help,listed),(self.property_hint,not listed)):widget.setVisible(shown)
        self.property_help.setText('')
        self.hidden_rows=set()
        if listed:
            effective=nodes.effective(self.graph)['nodes']
            rows=[(identity,key,None,False) for key in nodes.specs(effective[identity]['type'])] if identity else [(c['node'],c['key'],c.get('label'),c.get('kind')=='number') for c in controls]
            for identity,key,title,single in rows:
                node=effective[identity];spec=nodes.specs(node['type'])[key]
                # A control is a row of its own, never one of a ramp's three lists.
                ramps=ramp_groups(nodes.specs(node['type'])) if title is None else {}
                members={member:group for group in ramps.values() for member in group[1:]}
                if spec['type']=='SceneObject*':
                    if spec.get('interface') in ('INTERFACE_CAMERA','INTERFACE_NODE'):
                        import modo
                        row=self.table.rowCount();self.table.insertRow(row)
                        label=QtWidgets.QTableWidgetItem(key.replace('_',' '));label.setData(QtCore.Qt.UserRole,key);label.setFlags(label.flags() & ~QtCore.Qt.ItemIsEditable)
                        label.setForeground(QtGui.QBrush(QtGui.QColor('#000000')));self.table.setItem(row,0,label)
                        pick=QtWidgets.QComboBox();pick.addItem('None',None)
                        for item in sorted(modo.Scene().items('camera' if spec.get('interface')=='INTERFACE_CAMERA' else 'locator'),key=lambda i:i.name.casefold()):pick.addItem(item.name,item.id)
                        chosen=node.get('parameters',{}).get(key) or {};pick.setCurrentIndex(max(0,pick.findData(chosen.get('item'))));self.table.setCellWidget(row,1,pick)
                        tint_value(pick,chosen or None,spec,node['type'],key)
                        pick.currentIndexChanged.connect(lambda _index,n=identity,k=key,w=pick:self.scene_reference(n,k,w.currentData()))
                    continue
                row=self.table.rowCount();self.table.insertRow(row)
                label=QtWidgets.QTableWidgetItem(key.replace('_',' '));label.setData(QtCore.Qt.UserRole,key);label.setFlags(label.flags() & ~QtCore.Qt.ItemIsEditable)
                label.setForeground(QtGui.QBrush(QtGui.QColor('#000000')))
                if title:label.setText(title)
                inherited=key not in node.get('parameters',{})
                value=node.get('parameters',{}).get(key,node_defaults.value(spec))
                cell=QtWidgets.QTableWidgetItem('' if value is None else json.dumps(value))
                if key in node.get('inputs',{}):cell.setBackground(QtGui.QColor('#294757'));label.setToolTip('Connected from '+node['inputs'][key]+'; editing this value replaces the connection')
                if inherited:
                    font=cell.font();font.setItalic(True);cell.setFont(font)
                cell.setToolTip(str(spec.get('comment',''))+' Default: '+str(spec.get('default',spec.get('default_value',''))))
                limits=[str(spec[k]) for k in ('min','max') if k in spec]
                if limits:
                    cell.setToolTip(cell.toolTip()+' Allowed range: '+str(spec.get('min','unbounded'))+' to '+str(spec.get('max','unbounded')))
                if file_parameter(spec):cell.setToolTip(cell.toolTip()+' Click to browse for a file. Press F2 to type or paste a path, including <UDIM> patterns.')
                self.table.setItem(row,0,label);self.table.setItem(row,1,cell)
                self.table.itemDelegateForColumn(1).decorate(cell,spec,value)
                layer=self.layers.currentData() if self.layers.currentData() is not None else -1
                connected=key in node.get('inputs',{})
                if key in members:
                    title,positions_key,values_key,blends_key=members[key]
                    if key!=positions_key:
                        # Its row is the ramp's; the list is not shown on its own.
                        self.hidden_rows.add(row);continue
                    held=[node.get('parameters',{}).get(k,node_defaults.value(nodes.specs(node['type'])[k])) or [] for k in (positions_key,values_key)]
                    label.setText(title);cell.setText('');cell.setData(QtCore.Qt.DecorationRole,None)
                    field=RampField(identity,key,held[0],held[1],self.table)
                    field.edit.connect(self.edit_ramp);self.place_field(row,cell,field)
                    continue
                if single and isinstance(value,list) and value:
                    # One number that the graph holds as three alike: shown and set as the one it is.
                    cell.setText('');cell.setData(QtCore.Qt.DecorationRole,None)
                    field=NumericField(identity,key,layer,{'type':'Float'},value[0],self.table,kind=node['type'],connected=connected)
                    field.changed.connect(lambda i,k,l,v:self.set_value(i,k,l,[v,v,v]));field.focused.connect(self.numeric_focus)
                    self.place_field(row,cell,field);self.numeric_fields.append(field)
                elif spec['type'] in ('Float','Double') and not spec.get('enum'):
                    field=NumericField(identity,key,layer,spec,value,self.table,kind=node['type'],connected=connected)
                    field.changed.connect(self.numeric_changed);field.focused.connect(self.numeric_focus)
                    self.place_field(row,cell,field);self.numeric_fields.append(field)
                elif spec['type']=='Bool' or spec.get('enum') or spec['type'] in ('Int','Long'):
                    # Switches, named choices and whole numbers stay in place too, ready to click.
                    try:
                        made=IntegerField if spec['type'] in ('Int','Long') and not spec.get('enum') else ChoiceField
                        field=made(identity,key,layer,spec,value,self.table,kind=node['type'],connected=connected)
                    except (TypeError,ValueError):field=None
                    if field is not None:
                        field.changed.connect(self.choice_changed);self.place_field(row,cell,field)
                        if isinstance(field,IntegerField):self.numeric_fields.append(field)
                elif spec['type'] in ('Rgb','Vec2f','Vec3f','Vec2d','Vec3d'):
                    field=VectorField(identity,key,layer,spec,value,self.table,kind=node['type'],connected=connected)
                    field.changed.connect(self.object_changed);self.place_field(row,cell,field)
                elif spec['type']=='String' and key=='uv_map':
                    # The UV maps of the meshes this material is on, rather than a name to type.
                    field=NameField(identity,key,layer,spec,value,uv_choices(self.item),self.table,kind=node['type'],connected=connected)
                    field.changed.connect(self.object_changed);self.place_field(row,cell,field)
                elif spec['type']=='String':
                    field=TextField(identity,key,layer,spec,value,hint(key,spec),self.table,kind=node['type'],connected=connected)
                    field.changed.connect(self.object_changed);field.browse.connect(self.choose_node_file);self.place_field(row,cell,field)
                else:
                    # Lists and the like are typed as they are stored; say what that looks like.
                    cell.setToolTip('Double-click to edit. A list is typed in brackets, for example ["a", "b"] or [1.0, 2.0].')
        self.busy=False;self.filter_properties()
    def scene_reference(self,identity,key,value):
        before=copy.deepcopy(self.graph)
        try:
            self.target(identity).setdefault('parameters',{})[key]={'item':value} if value else None
            self.validate_draft();self.remember(before)
            for row in range(self.table.rowCount()):
                if key_of(self.table,row)==key:
                    widget=self.table.cellWidget(row,1)
                    spec=nodes.specs(self.graph['nodes'][identity]['type'])[key]
                    tint_value(widget,{'item':value} if value else None,spec,self.graph['nodes'][identity]['type'],key)
                    break
        except (ValueError,TypeError) as exc:self.graph=before;self.error(exc)

    def edited(self,cell):
        if self.busy or cell.column()!=1: return
        identity=self.selected()
        if not identity: return
        old=copy.deepcopy(self.graph)
        try:
            key=key_of(self.table,cell.row());text=cell.text().strip();target=self.target(identity)
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
            blocker=QtCore.QSignalBlocker(self.table)
            self.table.itemDelegateForColumn(1).decorate(cell,nodes.specs(self.graph['nodes'][identity]['type'])[key],
                nodes.effective(self.graph)['nodes'][identity].get('parameters',{}).get(key,node_defaults.value(nodes.specs(self.graph['nodes'][identity]['type'])[key])))
            del blocker
            # Scalar edits do not change the node layout. Keep the active Qt
            # cell editor alive until its delegate has finished committing.
            self.edges();self.material_preview.graph_changed(self.graph);self.publish_draft()
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
    def arrange_nodes(self):
        """Set the nodes out in columns from the output back, as an imported graph is."""
        before=copy.deepcopy(self.graph)
        nodes.arrange(self.graph);self.remember(before);self.rebuild();self.frame(everything=True)
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
            try: graph=materialx.read(path);before=copy.deepcopy(self.graph);self.graph=graph;self.remember(before);self.rebuild();self.frame_output()
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
            # The window does not block Modo, so the scene is changed through a command, which
            # is what makes the change undoable.
            lx.eval('moonray.material.applyGraph {%s} %s'%(self.item.id,properties.encode(settings)))
            self.info.setText('Applied to '+self.item.name+': '+root['type'])
            if close:self.accept()
        except (ValueError,RuntimeError,LookupError) as exc: self.error(exc)
