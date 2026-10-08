"""Mouse graph navigation and schema-driven property editors for Modo Qt."""
import copy,json,re,weakref
from pathlib import Path
from PySide2 import QtCore,QtGui,QtWidgets
from shiboken2 import isValid
from . import nodes,parameter_state

from .file_inputs import file_parameter

COLORS={'map':'#77bce8','material':'#89ce94','normal':'#c6a0e9','displacement':'#e4b367'}

def tint_value(widget,value,spec,kind=None,key=None,connected=False):
    """Use native palette roles; do not add Python paint/style callbacks."""
    color=QtGui.QColor(parameter_state.color(value,spec,kind,key,connected))
    palette=widget.palette()
    for role in (QtGui.QPalette.Text,QtGui.QPalette.ButtonText,QtGui.QPalette.WindowText):
        palette.setColor(role,color)
    widget.setPalette(palette)


# The canvas and what is drawn on it. Everything is made of Qt's own items and brushes: in
# Modo a painter handed to a Python paint callback can outlive its wrapper, so nothing here
# paints from Python.
CANVAS='#1d1f23';GRID_MINOR='#24272c';GRID_MAJOR='#2d3138'
NODE_BODY='#2a2d32';NODE_EDGE='#131518';ACCENT='#f5a623'
TEXT='#e8eaed';TEXT_PORT='#c5cad1';TEXT_DIM='#8b929c'
HEADERS={'map':'#35627f','material':'#3d7449','normal':'#65548a','displacement':'#86682f'}
GRID=20
MENU_STYLE='QMenu::item { padding: 5px 24px 5px 24px; } QMenu::separator { height: 1px; margin: 4px 10px; }'


def grid_brush():
    """The canvas background: a tile of fine lines with a stronger one every fifth."""
    size=GRID*5;tile=QtGui.QPixmap(size,size);tile.fill(QtGui.QColor(CANVAS))
    painter=QtGui.QPainter(tile)
    painter.setPen(QtGui.QPen(QtGui.QColor(GRID_MINOR),1))
    for step in range(GRID,size,GRID):painter.drawLine(step,0,step,size);painter.drawLine(0,step,size,step)
    painter.setPen(QtGui.QPen(QtGui.QColor(GRID_MAJOR),1))
    painter.drawLine(0,0,0,size);painter.drawLine(0,0,size,0)
    painter.end()
    return QtGui.QBrush(tile)


def curve(a,b):
    distance=max(50,abs(b.x()-a.x())*.5)
    path=QtGui.QPainterPath(a);path.cubicTo(a+QtCore.QPointF(distance,0),b-QtCore.QPointF(distance,0),b)
    return path


class QuickAdd(QtWidgets.QFrame):
    """A search box that opens at the pointer: type part of a node's name, Enter adds it."""
    def __init__(self,parent,kinds,chosen):
        super().__init__(parent,QtCore.Qt.Popup)
        self.chosen=chosen;self.kinds=sorted(kinds,key=str.casefold)
        layout=QtWidgets.QVBoxLayout(self);layout.setContentsMargins(6,6,6,6);layout.setSpacing(4)
        self.search=QtWidgets.QLineEdit();self.search.setPlaceholderText('Add node');layout.addWidget(self.search)
        self.results=QtWidgets.QListWidget();self.results.setMinimumSize(240,260);layout.addWidget(self.results)
        self.search.textChanged.connect(self.fill);self.search.returnPressed.connect(self.accept)
        self.results.itemClicked.connect(lambda item:self.accept())
        self.search.installEventFilter(self)
        self.fill('')
    def fill(self,text):
        query=text.casefold().strip();self.results.clear()
        # Names that begin with what was typed come before names that only contain it.
        first=[kind for kind in self.kinds if kind.casefold().startswith(query)]
        rest=[kind for kind in self.kinds if query in kind.casefold() and kind not in first]
        from .node_descriptions import tooltip
        for kind in first+rest:
            row=QtWidgets.QListWidgetItem(kind);row.setToolTip(tooltip(kind));self.results.addItem(row)
        if self.results.count():self.results.setCurrentRow(0)
    def eventFilter(self,watched,event):
        # The arrow keys move through the list while the text stays in the search box.
        if event.type()==QtCore.QEvent.KeyPress and event.key() in (QtCore.Qt.Key_Down,QtCore.Qt.Key_Up) and self.results.count():
            step=1 if event.key()==QtCore.Qt.Key_Down else -1
            self.results.setCurrentRow(max(0,min(self.results.count()-1,self.results.currentRow()+step)));return True
        return super().eventFilter(watched,event)
    def accept(self):
        item=self.results.currentItem()
        self.close()
        if item is not None:self.chosen(item.text())
    def open_at(self,point):
        self.move(point);self.show();self.search.setFocus()


class GraphView(QtWidgets.QGraphicsView):
    def __init__(self,editor,scene):
        super().__init__(scene);self.editor=editor;self.start_socket=None;self.rubber=None;self.pan=None;self.move_before=None
        self.setRenderHint(QtGui.QPainter.Antialiasing);self.setDragMode(self.RubberBandDrag)
        self.setTransformationAnchor(self.AnchorUnderMouse);self.setBackgroundBrush(grid_brush())
        # Panning is by dragging; the canvas has no edges to scroll to.
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff);self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setToolTip('')
    def socket_at(self,point):
        for item in self.items(point):
            if getattr(item,'is_socket',False):return item
    def node_at(self,point):
        owner=self.itemAt(point)
        while owner is not None and not hasattr(owner,'identity'):owner=owner.parentItem()
        return owner
    def cancel_wire(self):
        if self.rubber and self.rubber.scene():self.scene().removeItem(self.rubber)
        self.rubber=None;self.start_socket=None
    def wheelEvent(self,event):
        factor=1.15 if event.angleDelta().y()>0 else 1/1.15
        if .2<=self.transform().m11()*factor<=3.0:self.scale(factor,factor)
        event.accept()
    def mousePressEvent(self,event):
        # Middle drag pans, and so does Alt with the left button.
        if event.button()==QtCore.Qt.MiddleButton or (event.button()==QtCore.Qt.LeftButton and event.modifiers()&QtCore.Qt.AltModifier):
            self.pan=event.pos();self.setCursor(QtCore.Qt.ClosedHandCursor);event.accept();return
        socket=self.socket_at(event.pos())
        if socket and event.button()==QtCore.Qt.LeftButton:
            self.cancel_wire();self.start_socket=socket
            self.rubber=self.scene().addPath(curve(socket.scenePos(),socket.scenePos()),QtGui.QPen(QtGui.QColor('#a9d7ff'),2,QtCore.Qt.DashLine));self.rubber.setZValue(10)
            self.editor.focus_socket(socket.identity,socket.key)
            event.accept();return
        if event.button()==QtCore.Qt.LeftButton:self.move_before=copy.deepcopy(self.editor.graph)
        super().mousePressEvent(event)
    def mouseMoveEvent(self,event):
        if self.pan is not None:
            delta=event.pos()-self.pan;self.pan=event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value()-delta.x());self.verticalScrollBar().setValue(self.verticalScrollBar().value()-delta.y());event.accept();return
        if self.start_socket:
            start=self.start_socket;end=self.socket_at(event.pos());point=self.mapToScene(event.pos())
            a,b=(start.scenePos(),point) if start.key is None else (point,start.scenePos())
            self.rubber.setPath(curve(a,b));valid=end and end.key is not start.key and ((end.key is None)!=(start.key is None))
            if valid:
                source,target=(start,end) if start.key is None else (end,start)
                valid=self.editor.can_connect(source.identity,target.identity,target.key)
            self.rubber.setPen(QtGui.QPen(QtGui.QColor('#89ce94' if valid else '#a9d7ff' if end is None else '#f08a84'),2,QtCore.Qt.DashLine));event.accept();return
        super().mouseMoveEvent(event)
    def mouseReleaseEvent(self,event):
        if self.pan is not None and event.button() in (QtCore.Qt.MiddleButton,QtCore.Qt.LeftButton):
            self.pan=None;self.unsetCursor();event.accept();return
        if self.start_socket and event.button()==QtCore.Qt.LeftButton:
            start=self.start_socket;end=self.socket_at(event.pos());self.cancel_wire()
            if end and end is not start and ((end.key is None)!=(start.key is None)):
                source,target=(start,end) if start.key is None else (end,start)
                self.editor.connect_nodes(source.identity,target.identity,target.key)
            elif end is start:self.editor.socket(start.identity,start.key)
            elif end is None and start.key is not None and self.node_at(event.pos()) is None:
                # An input's wire let go over empty canvas: choose the node to feed it.
                self.editor.quick_add(self.mapToScene(event.pos()),event.globalPos(),(start.identity,start.key))
            else:self.editor.info.setText('Connection cancelled.')
            event.accept();return
        super().mouseReleaseEvent(event)
        if self.move_before is not None:
            self.editor.snap_selected()
            self.editor.remember(self.move_before);self.move_before=None
    def mouseDoubleClickEvent(self,event):
        if event.button()==QtCore.Qt.LeftButton and self.itemAt(event.pos()) is None:
            self.editor.quick_add(self.mapToScene(event.pos()),event.globalPos());event.accept();return
        super().mouseDoubleClickEvent(event)
    def keyPressEvent(self,event):
        key=event.key()
        if key==QtCore.Qt.Key_Escape:
            self.cancel_wire();self.editor.pending=None;event.accept();return
        if event.matches(QtGui.QKeySequence.Undo):self.editor.undo();event.accept();return
        if event.matches(QtGui.QKeySequence.Redo):self.editor.redo();event.accept();return
        if key==QtCore.Qt.Key_D and event.modifiers()&QtCore.Qt.ControlModifier:self.editor.duplicate();event.accept();return
        if key in (QtCore.Qt.Key_Delete,QtCore.Qt.Key_Backspace):self.editor.remove();event.accept();return
        if key==QtCore.Qt.Key_F:self.editor.frame();event.accept();return
        if key in (QtCore.Qt.Key_A,QtCore.Qt.Key_Home):self.editor.frame(everything=True);event.accept();return
        if key==QtCore.Qt.Key_Tab:
            point=self.mapFromGlobal(QtGui.QCursor.pos())
            if not self.rect().contains(point):point=self.rect().center()
            self.editor.quick_add(self.mapToScene(point),self.mapToGlobal(point));event.accept();return
        super().keyPressEvent(event)
    def focusNextPrevChild(self,forward):
        # Tab opens the add-node search here rather than leaving the canvas.
        return False
    def contextMenuEvent(self,event):
        socket=self.socket_at(event.pos());item=self.itemAt(event.pos())
        owner=self.node_at(event.pos())
        identity=getattr(owner,'identity',None)
        graph=self.editor.graph
        menu=QtWidgets.QMenu(self);menu.setStyleSheet(MENU_STYLE);connection=None
        def entry(label,what,enabled=True):
            # Made first and then added; each says what it does through its data.
            action=QtWidgets.QAction(label,menu);action.setData(what);action.setEnabled(enabled);menu.addAction(action)
        if socket and socket.key is not None:
            connection=(socket.identity,socket.key);entry('Disconnect '+socket.key.replace('_',' '),'disconnect')
        elif item and getattr(item,'connection',None):
            connection=item.connection;entry('Disconnect','disconnect')
        if identity in graph['nodes']:
            if owner is not None and not owner.isSelected():
                self.scene().clearSelection();owner.setSelected(True)
            if connection:menu.addSeparator()
            if nodes.category(graph['nodes'][identity]['type'])=='material':
                entry('Material Output (current)' if identity==graph['root'] else 'Set as Material Output','output',identity!=graph['root'])
            if getattr(owner,'hidden_ports',0) or identity in self.editor.expanded:
                entry('Show Fewer Inputs' if identity in self.editor.expanded else 'Show All Inputs','expand')
            entry('Duplicate\tCtrl+D','duplicate')
            entry('Delete\tDel','delete')
        if not menu.isEmpty():menu.addSeparator()
        entry('Add Node...\tTab','add');entry('Frame Selected\tF','frame');entry('Frame All\tA','frame_all')
        chosen=menu.exec_(event.globalPos())
        what=chosen.data() if chosen is not None else None
        if what=='output':self.editor.output(identity)
        elif what=='disconnect':self.editor.unlink(*connection)
        elif what=='expand':self.editor.toggle_expanded(identity)
        elif what=='duplicate':self.editor.duplicate()
        elif what=='delete':self.editor.remove()
        elif what=='add':self.editor.quick_add(self.mapToScene(event.pos()),event.globalPos())
        elif what=='frame':self.editor.frame()
        elif what=='frame_all':self.editor.frame(everything=True)


class VectorEdit(QtWidgets.QWidget):
    color_accepted=QtCore.Signal()
    def __init__(self,count,color,parent):
        super().__init__(parent);layout=QtWidgets.QHBoxLayout(self);layout.setContentsMargins(0,0,0,0);self.spins=[];self.choosing_color=False
        for _ in range(count):
            spin=QtWidgets.QDoubleSpinBox();spin.setRange(-1e12,1e12);spin.setDecimals(6);spin.setSingleStep(.1);layout.addWidget(spin);self.spins.append(spin)
        if color:
            self.swatch=QtWidgets.QPushButton();self.swatch.setFixedSize(40,24);self.swatch.setAutoDefault(False);self.swatch.setDefault(False);self.swatch.setAccessibleName('Choose color');layout.addWidget(self.swatch);self.swatch.clicked.connect(self.choose)
            for spin in self.spins:spin.valueChanged.connect(self.update_swatch)
            self.update_swatch()
    def update_swatch(self,*args):
        color=QtGui.QColor.fromRgbF(*[max(0,min(1,s.value())) for s in self.spins[:3]])
        self.swatch.setStyleSheet('background-color: '+color.name()+'; border: 1px solid #888; border-radius: 3px;')
        self.swatch.setToolTip('Choose color — RGB '+', '.join(format(s.value(),'.4g') for s in self.spins[:3]))
    def choose(self):
        initial=QtGui.QColor.fromRgbF(*[max(0,min(1,s.value())) for s in self.spins[:3]])
        self.choosing_color=True
        try:color=QtWidgets.QColorDialog.getColor(initial,self)
        finally:self.choosing_color=False
        if color.isValid():
            for spin,value in zip(self.spins,(color.redF(),color.greenF(),color.blueF())):spin.setValue(value)
            self.color_accepted.emit()

from .node_defaults import value as default_value

class NumericField(QtWidgets.QDoubleSpinBox):
    """A persistent property control; entering a value never destroys its widget."""
    changed=QtCore.Signal(str,str,int,float)
    focused=QtCore.Signal(str,str)
    def __init__(self,identity,key,layer,spec,value,parent=None,kind=None,connected=False):
        super().__init__(parent)
        self.identity,self.key,self.layer=identity,key,layer
        self.spec,self.kind=spec,kind
        self.setDecimals(6);self.setSingleStep(.1);self.setKeyboardTracking(False)
        self.setRange(float(str(spec.get('min',-1e12)).rstrip('f')),
                      float(str(spec.get('max',1e12)).rstrip('f')))
        self.setValue(float(value or 0));self.setFrame(False)
        self.setAccessibleName(key)
        tint_value(self,value,spec,kind,key,connected)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.valueChanged.connect(self.publish)
    def focusInEvent(self,event):
        super().focusInEvent(event);self.focused.emit(self.identity,self.key)
    def wheelEvent(self,event):
        # Scrolling the list of properties must not change the ones the pointer passes over.
        if self.hasFocus():super().wheelEvent(event)
        else:event.ignore()
    @QtCore.Slot(float)
    def publish(self,value):
        tint_value(self,value,self.spec,self.kind,self.key)
        self.changed.emit(self.identity,self.key,self.layer,value)


# The spaces a ramp or gradient can be laid out in, said plainly and with the usual ones first.
SPACE_LABELS={'object':'Object (stays on the object)','world':'World (fixed in the scene)','texture':'Texture (follows the UVs)',
              'render':'Render (follows the camera)','camera':'Camera (follows the camera)','screen':'Screen (follows the picture)',
              'reference':'Reference (a rest position)'}
SPACE_ORDER=(4,2,6,0,1,3,5)


class ChoiceField(QtWidgets.QComboBox):
    """A switch or a list of named values that is always there to click. As a cell editor made
    on demand it lost the click that opened its list and had to be nudged with an arrow key."""
    changed=QtCore.Signal(str,str,int,int)
    def __init__(self,identity,key,layer,spec,value,parent=None,kind=None,connected=False):
        super().__init__(parent)
        self.identity,self.key,self.layer=identity,key,layer
        self.spec,self.kind=spec,kind
        if spec['type']=='Bool':entries=[('Off',0),('On',1)]
        else:entries=[(' '.join(word.capitalize() for word in str(label).replace('_',' ').split()),int(number)) for label,number in sorted(spec['enum'].items(),key=lambda entry:int(entry[1]))]
        if key=='space':
            # Say what each space means for where the pattern sits; MoonRay's names alone do not.
            entries=[(SPACE_LABELS.get(label.casefold(),label),number) for label,number in entries]
            entries.sort(key=lambda entry:SPACE_ORDER.index(entry[1]) if entry[1] in SPACE_ORDER else len(SPACE_ORDER))
        for label,number in entries:self.addItem(label,number)
        self.setCurrentIndex(max(0,self.findData(int(value or 0))))
        self.setFrame(False);self.setAccessibleName(key);self.setFocusPolicy(QtCore.Qt.StrongFocus)
        tint_value(self,value,spec,kind,key,connected)
        # Only a choice made by hand counts, not the value being set from the graph.
        self.activated.connect(self.publish)
    def wheelEvent(self,event):
        # Scrolling the list of properties must not change the ones the pointer passes over.
        if self.hasFocus():super().wheelEvent(event)
        else:event.ignore()
    @QtCore.Slot(int)
    def publish(self,index):
        self.changed.emit(self.identity,self.key,self.layer,int(self.itemData(index)))


class IntegerField(QtWidgets.QSpinBox):
    """A whole number that is always there to edit."""
    changed=QtCore.Signal(str,str,int,int)
    def __init__(self,identity,key,layer,spec,value,parent=None,kind=None,connected=False):
        super().__init__(parent)
        self.identity,self.key,self.layer=identity,key,layer
        self.spec,self.kind=spec,kind
        self.setKeyboardTracking(False)
        self.setRange(int(float(str(spec.get('min',-2147483647)).rstrip('f'))),int(float(str(spec.get('max',2147483647)).rstrip('f'))))
        self.setValue(int(value or 0));self.setFrame(False);self.setAccessibleName(key);self.setFocusPolicy(QtCore.Qt.StrongFocus)
        tint_value(self,value,spec,kind,key,connected)
        self.valueChanged.connect(self.publish)
    def wheelEvent(self,event):
        if self.hasFocus():super().wheelEvent(event)
        else:event.ignore()
    @QtCore.Slot(int)
    def publish(self,value):
        self.changed.emit(self.identity,self.key,self.layer,int(value))


class VectorField(QtWidgets.QWidget):
    """Two or three numbers side by side; a colour also has a swatch that opens the picker."""
    changed=QtCore.Signal(str,str,int,object)
    def __init__(self,identity,key,layer,spec,value,parent=None,kind=None,connected=False):
        super().__init__(parent)
        self.identity,self.key,self.layer=identity,key,layer
        self.spec,self.kind=spec,kind
        count=2 if spec['type'] in ('Vec2f','Vec2d') else 3
        self.is_color=spec['type']=='Rgb'
        layout=QtWidgets.QHBoxLayout(self);layout.setContentsMargins(2,0,2,0);layout.setSpacing(2)
        self.swatch=None
        if self.is_color:
            self.swatch=QtWidgets.QPushButton();self.swatch.setFixedSize(28,20);self.swatch.setAutoDefault(False);self.swatch.setDefault(False)
            self.swatch.setToolTip('Choose a colour');self.swatch.clicked.connect(self.choose);layout.addWidget(self.swatch)
        self.spins=[]
        values=list(value) if isinstance(value,(list,tuple)) else []
        low=float(str(spec['min']).rstrip('f')) if 'min' in spec else -1e12
        high=float(str(spec['max']).rstrip('f')) if 'max' in spec else 1e12
        for index in range(count):
            spin=QtWidgets.QDoubleSpinBox();spin.setRange(low,high);spin.setDecimals(3);spin.setSingleStep(.05 if self.is_color else .1)
            spin.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons);spin.setKeyboardTracking(False);spin.setFrame(False)
            spin.setFocusPolicy(QtCore.Qt.StrongFocus);spin.setToolTip(('Red','Green','Blue')[index] if self.is_color else 'XYZ'[index])
            spin.setValue(float(values[index]) if index<len(values) else 0.0)
            spin.installEventFilter(self)
            spin.valueChanged.connect(self.publish);layout.addWidget(spin,1);self.spins.append(spin)
            tint_value(spin,value,spec,kind,key,connected)
        self.paint_swatch()
    def eventFilter(self,watched,event):
        # Scrolling the list of properties must not change the numbers the pointer passes over.
        if event.type()==QtCore.QEvent.Wheel and not watched.hasFocus():
            event.ignore();return True
        return False
    def value(self):return [spin.value() for spin in self.spins]
    def paint_swatch(self):
        if self.swatch is None:return
        color=QtGui.QColor.fromRgbF(*[max(0.0,min(1.0,v)) for v in self.value()])
        self.swatch.setStyleSheet('background-color: '+color.name()+'; border: 1px solid #15171a; border-radius: 3px;')
    def choose(self):
        color=QtWidgets.QColorDialog.getColor(QtGui.QColor.fromRgbF(*[max(0.0,min(1.0,v)) for v in self.value()]),self,'Choose '+self.key.replace('_',' '))
        if not color.isValid():return
        for spin,part in zip(self.spins,(color.redF(),color.greenF(),color.blueF())):
            blocker=QtCore.QSignalBlocker(spin);spin.setValue(part);del blocker
        self.publish()
    def publish(self,*args):
        self.paint_swatch()
        for spin in self.spins:tint_value(spin,self.value(),self.spec,self.kind,self.key)
        self.changed.emit(self.identity,self.key,self.layer,self.value())


class TextField(QtWidgets.QWidget):
    """A line of text that says what belongs in it while it is empty; a file also has a button
    that opens the file browser."""
    changed=QtCore.Signal(str,str,int,object)
    browse=QtCore.Signal(str,str)
    def __init__(self,identity,key,layer,spec,value,hint,parent=None,kind=None,connected=False):
        super().__init__(parent)
        self.identity,self.key,self.layer=identity,key,layer
        self.spec,self.kind=spec,kind
        layout=QtWidgets.QHBoxLayout(self);layout.setContentsMargins(2,0,2,0);layout.setSpacing(2)
        self.line=QtWidgets.QLineEdit(str(value or ''));self.line.setFrame(False);self.line.setPlaceholderText(hint)
        self.held=self.line.text()
        self.line.editingFinished.connect(self.publish);layout.addWidget(self.line,1)
        tint_value(self.line,value,spec,kind,key,connected)
        if file_parameter(spec):
            button=QtWidgets.QToolButton();button.setText('...');button.setToolTip('Browse for a file');button.setAutoRaise(True)
            # The property list is rebuilt after a file is chosen; let this click finish first.
            button.clicked.connect(lambda:QtCore.QTimer.singleShot(0,lambda:self.browse.emit(self.identity,self.key)));layout.addWidget(button)
    def publish(self):
        if self.line.text()==self.held:return
        self.held=self.line.text()
        tint_value(self.line,self.held,self.spec,self.kind,self.key)
        self.changed.emit(self.identity,self.key,self.layer,self.held)


class NameField(QtWidgets.QComboBox):
    """A choice among names found in the scene, such as the UV maps of the meshes a material is
    on, in place of typing one."""
    changed=QtCore.Signal(str,str,int,object)
    def __init__(self,identity,key,layer,spec,value,entries,parent=None,kind=None,connected=False):
        super().__init__(parent)
        self.identity,self.key,self.layer=identity,key,layer
        self.spec,self.kind=spec,kind
        for label,name in entries:self.addItem(label,name)
        value=str(value or '')
        if self.findData(value)<0:
            # A name the scene no longer has is kept, and shown for what it is.
            self.addItem(value+'  (not found)',value)
        self.setCurrentIndex(self.findData(value))
        self.setFrame(False);self.setAccessibleName(key);self.setFocusPolicy(QtCore.Qt.StrongFocus)
        tint_value(self,value,spec,kind,key,connected)
        self.activated.connect(self.publish)
    def wheelEvent(self,event):
        if self.hasFocus():super().wheelEvent(event)
        else:event.ignore()
    @QtCore.Slot(int)
    def publish(self,index):
        self.changed.emit(self.identity,self.key,self.layer,str(self.itemData(index)))


def key_of(table,row):
    """The attribute a row of the property list is for; the row shows its name in plain words."""
    item=table.item(row,0)
    return item.data(QtCore.Qt.UserRole) or item.text()


def describe(key,spec):
    """What a property is, the values it takes and what it starts at, in a few lines."""
    words=' '.join(str(spec.get('comment','')).split())
    parts=[words] if words else []
    kind=spec['type']
    if spec.get('enum'):pass
    elif 'min' in spec or 'max' in spec:
        parts.append('Range: %s to %s.'%(str(spec.get('min','any')).rstrip('f'),str(spec.get('max','any')).rstrip('f')))
    default=spec.get('default',spec.get('default_value'))
    if default not in (None,'') and not spec.get('enum') and kind!='Bool':
        shown=str(default)
        # MoonRay writes its numbers as C++ does.
        if kind in ('Float','Double') and shown.endswith('f'):shown=shown[:-1]
        parts.append('Default: %s.'%shown)
    if file_parameter(spec):parts.append('A file path; <UDIM> stands for the tile number.')
    return (key.replace('_',' ')+': ' if parts else key.replace('_',' '))+' '.join(parts)


def hint(key,spec):
    """What to type into an empty text property."""
    if file_parameter(spec):return 'Path to a file'
    name=key.casefold()
    if 'primitive_attribute' in name or 'attribute_name' in name or name.endswith('attribute'):return 'Name of a mesh attribute'
    if 'uv' in name:return 'Name of a UV map'
    if 'label' in name:return 'A name of your choice'
    words=' '.join(str(spec.get('comment','')).split())
    first=re.match(r'(.+?[.!?])(?=\s|$)',words)
    words=(first.group(1) if first else words).rstrip('.')
    return words[:60]+('...' if len(words)>60 else '') if words else 'Text'


class ParameterDelegate(QtWidgets.QStyledItemDelegate):
    def __init__(self,editor):
        super().__init__(editor.table);self.editor=editor;self.active_editor=None
        self.pending_focus=None
        self.focus_timer=QtCore.QTimer(self);self.focus_timer.setSingleShot(True)
        self.focus_timer.timeout.connect(self.commit_focus)
    def detach_editor(self,widget):
        if self.pending_focus is not None and self.pending_focus() is widget:
            self.focus_timer.stop();self.pending_focus=None
        if self.active_editor is widget:self.active_editor=None
        if isValid(widget):
            widget.removeEventFilter(self)
            for child in widget.findChildren(QtWidgets.QWidget):child.removeEventFilter(self)
    def destroyEditor(self,widget,index):
        # Drop Python callbacks/filters before Qt destroys the cell editor.
        # Never capture the dying widget in its own destroyed signal.
        self.detach_editor(widget)
        super().destroyEditor(widget,index)
    @QtCore.Slot()
    def commit_focus(self):
        reference=self.pending_focus;self.pending_focus=None
        widget=reference() if reference else None
        if widget is not None:self.commit_if_left(widget)
    def schema(self,index):
        identity=self.editor.selected();key=key_of(self.editor.table,index.row())
        return nodes.specs(self.editor.graph['nodes'][identity]['type'])[key]
    def decorate(self,cell,spec,value):
        identity=self.editor.selected()
        node=nodes.effective(self.editor.graph)['nodes'].get(identity,{})
        label=self.editor.table.item(cell.row(),0)
        key=(label.data(QtCore.Qt.UserRole) or label.text()) if label else None
        cell.setForeground(QtGui.QBrush(QtGui.QColor(parameter_state.color(value,spec,node.get('type'),key,key in node.get('inputs',{})))))
        # Use Qt's native delegate painting. Borrowed QPainter/style-option
        # wrappers must not cross a Python paint callback in the Modo host.
        decoration=None
        if file_parameter(spec):
            decoration=QtGui.QIcon(str(Path(__file__).resolve().parents[2]/'assets/folder.svg'))
        elif spec['type']=='Rgb' and isinstance(value,(list,tuple)) and len(value)==3:
            decoration=QtGui.QColor.fromRgbF(*[max(0,min(1,float(v))) for v in value])
        cell.setData(QtCore.Qt.DecorationRole,decoration)
    def editorEvent(self,event,model,option,index):
        if index.column()==1 and file_parameter(self.schema(index)):
            if event.type()==QtCore.QEvent.MouseButtonRelease and event.button()==QtCore.Qt.LeftButton:
                identity=self.editor.selected();key=key_of(self.editor.table,index.row())
                self.editor.choose_node_file(identity,key);return True
            if event.type()==QtCore.QEvent.MouseButtonDblClick:return True
        if event.type()==QtCore.QEvent.MouseButtonRelease and event.button()==QtCore.Qt.LeftButton and event.pos().x()<option.rect.left()+29:
            try:
                if index.column()==1 and self.schema(index)['type']=='Rgb':
                    identity=self.editor.selected();key=key_of(self.editor.table,index.row())
                    self.editor.choose_node_color(identity,key);return True
            except (ValueError,TypeError,KeyError):pass
        return super().editorEvent(event,model,option,index)
    def createEditor(self,parent,option,index):
        if index.column()!=1:return None
        spec=self.schema(index);kind=spec['type'];enum=spec.get('enum')
        if kind=='Bool' or enum:
            widget=QtWidgets.QComboBox(parent)
            for label,value in ([('Off',False),('On',True)] if kind=='Bool' else [(k,int(v)) for k,v in enum.items()]):widget.addItem(label,value)
        elif kind in ('Int','Long'):
            widget=QtWidgets.QSpinBox(parent);widget.setRange(-2147483647,2147483647)
        elif kind in ('Float','Double'):
            widget=QtWidgets.QDoubleSpinBox(parent);widget.setRange(-1e12,1e12);widget.setDecimals(6);widget.setSingleStep(.1)
        elif kind in ('Rgb','Vec2f','Vec3f','Vec2d','Vec3d'):widget=VectorEdit(2 if kind in ('Vec2f','Vec2d') else 3,kind=='Rgb',parent)
        else:widget=QtWidgets.QLineEdit(parent)
        # Apply schema bounds before the editor receives its initial value.
        spins=widget.spins if isinstance(widget,VectorEdit) else ([widget] if isinstance(widget,QtWidgets.QAbstractSpinBox) else [])
        for spin in spins:
            for key,setter in (('min',spin.setMinimum),('max',spin.setMaximum)):
                if key in spec:
                    limit=float(str(spec[key]).rstrip('f'))
                    setter(int(limit) if isinstance(spin,QtWidgets.QSpinBox) else limit)
        self.active_editor=widget
        identity=self.editor.selected();key=key_of(self.editor.table,index.row())
        widget.parameter_tint=(spec,self.editor.graph['nodes'][identity]['type'],key)
        if isinstance(widget,VectorEdit):
            for spin in widget.spins:spin.valueChanged.connect(self.refresh_tint)
        elif isinstance(widget,QtWidgets.QComboBox):widget.currentIndexChanged.connect(self.refresh_tint)
        elif isinstance(widget,QtWidgets.QAbstractSpinBox):widget.valueChanged.connect(self.refresh_tint)
        elif isinstance(widget,QtWidgets.QLineEdit):widget.textChanged.connect(self.refresh_tint)
        widget.installEventFilter(self)
        for child in widget.findChildren(QtWidgets.QWidget):child.installEventFilter(self)
        if isinstance(widget,VectorEdit):widget.color_accepted.connect(self.commit_pending)
        return widget
    def refresh_tint(self,*args):
        widget=self.active_editor
        if widget is None or not isValid(widget):return
        spec,kind,key=widget.parameter_tint
        if isinstance(widget,VectorEdit):value=[spin.value() for spin in widget.spins]
        elif isinstance(widget,QtWidgets.QComboBox):value=widget.currentData()
        elif isinstance(widget,QtWidgets.QAbstractSpinBox):value=widget.value()
        else:
            try:value=widget.text() if spec['type']=='String' else json.loads(widget.text())
            except (TypeError,ValueError):return
        tint_value(widget,value,spec,kind,key)
        if isinstance(widget,VectorEdit):
            for spin in widget.spins:tint_value(spin,value,spec,kind,key)

    def eventFilter(self,watched,event):
        widget=self.active_editor
        if widget is not None and not isValid(widget):
            self.active_editor=None;widget=None
        if widget is None or not isValid(watched):return False
        belongs=widget is not None and (watched is widget or widget.isAncestorOf(watched))
        if not belongs:return False
        if belongs:
            if event.type()==QtCore.QEvent.KeyPress:
                if event.key() in (QtCore.Qt.Key_Return,QtCore.Qt.Key_Enter):
                    self.commit_pending();event.accept();return True
                if event.key()==QtCore.Qt.Key_Escape:
                    self.detach_editor(widget)
                    self.closeEditor.emit(widget,QtWidgets.QAbstractItemDelegate.RevertModelCache)
                    event.accept();return True
            if event.type()==QtCore.QEvent.FocusOut:
                # Moving between RGB components or into the color picker is not
                # leaving this composite editor. Check once focus has settled.
                self.pending_focus=weakref.ref(widget);self.focus_timer.start(0)
                return False
            if watched is not widget:return False
        return super().eventFilter(watched,event)
    def commit_if_left(self,widget):
        if self.active_editor is not widget or not isValid(widget) or getattr(widget,'choosing_color',False):return
        focus=QtWidgets.QApplication.focusWidget()
        if focus is widget or (focus is not None and widget.isAncestorOf(focus)):return
        self.commit_pending()
    def commit_pending(self):
        widget=self.active_editor
        if widget is None:return
        self.detach_editor(widget)
        if not isValid(widget):return
        try:
            if isinstance(widget,QtWidgets.QAbstractSpinBox):widget.interpretText()
            if isinstance(widget,VectorEdit):
                for spin in widget.spins:spin.interpretText()
            self.commitData.emit(widget)
            if isValid(widget):self.closeEditor.emit(widget,QtWidgets.QAbstractItemDelegate.NoHint)
        except RuntimeError:pass  # Qt may have already destroyed a closed cell editor.
    def setEditorData(self,widget,index):
        spec=self.schema(index);raw=index.data();value=json.loads(raw) if raw else default_value(spec)
        if isinstance(widget,QtWidgets.QComboBox):widget.setCurrentIndex(max(0,widget.findData(value)))
        elif isinstance(widget,(QtWidgets.QSpinBox,QtWidgets.QDoubleSpinBox)):widget.setValue(float(value or 0) if isinstance(widget,QtWidgets.QDoubleSpinBox) else int(value or 0))
        elif isinstance(widget,VectorEdit):
            for spin,v in zip(widget.spins,value if isinstance(value,list) else [0]*len(widget.spins)):spin.setValue(v)
        else:widget.setText(str(value or '') if spec['type']=='String' else (raw or ''))
        self.refresh_tint()
    def setModelData(self,widget,model,index):
        if isinstance(widget,QtWidgets.QComboBox):value=widget.currentData()
        elif isinstance(widget,(QtWidgets.QSpinBox,QtWidgets.QDoubleSpinBox)):value=widget.value()
        elif isinstance(widget,VectorEdit):value=[spin.value() for spin in widget.spins]
        else:
            if self.schema(index)['type']=='String':value=widget.text()
            else:
                model.setData(index,widget.text());return
        model.setData(index,json.dumps(value))
