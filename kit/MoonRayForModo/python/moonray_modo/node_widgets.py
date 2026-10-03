"""Mouse graph navigation and schema-driven property editors for Modo Qt."""
import copy,json,re
from PySide2 import QtCore,QtGui,QtWidgets
from . import nodes

COLORS={'map':'#77bce8','material':'#89ce94','normal':'#c6a0e9'}

def curve(a,b):
    distance=max(65,abs(b.x()-a.x())*.5)
    path=QtGui.QPainterPath(a);path.cubicTo(a+QtCore.QPointF(distance,0),b-QtCore.QPointF(distance,0),b)
    return path

class GraphView(QtWidgets.QGraphicsView):
    def __init__(self,editor,scene):
        super().__init__(scene);self.editor=editor;self.start_socket=None;self.rubber=None;self.pan=None;self.move_before=None
        self.setRenderHint(QtGui.QPainter.Antialiasing);self.setDragMode(self.RubberBandDrag)
        self.setTransformationAnchor(self.AnchorUnderMouse);self.setBackgroundBrush(QtGui.QColor('#1c2128'))
    def socket_at(self,point):
        for item in self.items(point):
            if getattr(item,'is_socket',False):return item
    def cancel_wire(self):
        if self.rubber and self.rubber.scene():self.scene().removeItem(self.rubber)
        self.rubber=None;self.start_socket=None
    def wheelEvent(self,event):
        factor=1.15 if event.angleDelta().y()>0 else 1/1.15
        if .15<=self.transform().m11()*factor<=3.5:self.scale(factor,factor)
        event.accept()
    def mousePressEvent(self,event):
        if event.button()==QtCore.Qt.MiddleButton:
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
        if event.button()==QtCore.Qt.MiddleButton and self.pan is not None:
            self.pan=None;self.unsetCursor();event.accept();return
        if self.start_socket and event.button()==QtCore.Qt.LeftButton:
            start=self.start_socket;end=self.socket_at(event.pos());self.cancel_wire()
            if end and end is not start and ((end.key is None)!=(start.key is None)):
                source,target=(start,end) if start.key is None else (end,start)
                self.editor.connect_nodes(source.identity,target.identity,target.key)
            elif end is start:self.editor.socket(start.identity,start.key)
            else:self.editor.info.setText('Connection cancelled. Drop on a compatible socket; the existing connection is preserved.')
            event.accept();return
        super().mouseReleaseEvent(event)
        if self.move_before is not None:self.editor.remember(self.move_before);self.move_before=None
    def keyPressEvent(self,event):
        if event.key()==QtCore.Qt.Key_Escape:
            self.cancel_wire();self.editor.pending=None;event.accept();return
        if event.matches(QtGui.QKeySequence.Undo):self.editor.undo();event.accept();return
        if event.matches(QtGui.QKeySequence.Redo):self.editor.redo();event.accept();return
        if event.key() in (QtCore.Qt.Key_Delete,QtCore.Qt.Key_Backspace):self.editor.remove();event.accept();return
        if event.key()==QtCore.Qt.Key_F:self.editor.frame();event.accept();return
        super().keyPressEvent(event)
    def contextMenuEvent(self,event):
        socket=self.socket_at(event.pos())
        if socket and socket.key is not None:
            menu=QtWidgets.QMenu(self);action=menu.addAction('Disconnect '+socket.key)
            if menu.exec_(event.globalPos())==action:self.editor.unlink(socket.identity,socket.key)
            return
        item=self.itemAt(event.pos())
        if item and getattr(item,'connection',None):
            menu=QtWidgets.QMenu(self);action=menu.addAction('Disconnect')
            if menu.exec_(event.globalPos())==action:self.editor.unlink(*item.connection)
            return
        menu=QtWidgets.QMenu(self);add=menu.addAction('Add node…');frame=menu.addAction('Frame all (F)');chosen=menu.exec_(event.globalPos())
        if chosen==add:self.editor.add_at=self.mapToScene(event.pos());self.editor.kinds.setFocus();self.editor.kinds.lineEdit().selectAll()
        elif chosen==frame:self.editor.frame()

class VectorEdit(QtWidgets.QWidget):
    def __init__(self,count,color,parent):
        super().__init__(parent);layout=QtWidgets.QHBoxLayout(self);layout.setContentsMargins(0,0,0,0);self.spins=[]
        for _ in range(count):
            spin=QtWidgets.QDoubleSpinBox();spin.setRange(-1e12,1e12);spin.setDecimals(6);spin.setSingleStep(.1);layout.addWidget(spin);self.spins.append(spin)
        if color:
            button=QtWidgets.QPushButton('Color');layout.addWidget(button);button.clicked.connect(self.choose)
    def choose(self):
        initial=QtGui.QColor.fromRgbF(*[max(0,min(1,s.value())) for s in self.spins[:3]])
        color=QtWidgets.QColorDialog.getColor(initial,self)
        if color.isValid():
            for spin,value in zip(self.spins,(color.redF(),color.greenF(),color.blueF())):spin.setValue(value)

def default_value(spec):
    if 'default_value' in spec:return spec['default_value']
    raw=str(spec.get('default','')).strip();kind=spec['type']
    if kind=='Bool':return raw.lower()=='true'
    if kind in ('Rgb','Vec2f','Vec3f','Vec2d','Vec3d'):
        values=re.findall(r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?',raw[raw.find('(')+1:])
        count=2 if kind in ('Vec2f','Vec2d') else 3
        parsed=[float(v) for v in values]
        return (parsed*count if len(parsed)==1 else parsed)[:count] if parsed else [0.]*count
    if kind in ('Int','Long','Float','Double'):
        match=re.search(r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?',raw)
        return float(match.group()) if match else 0
    if kind=='String':
        try:return json.loads(raw)
        except ValueError:return ''
    return None

class ParameterDelegate(QtWidgets.QStyledItemDelegate):
    def __init__(self,editor):super().__init__(editor.table);self.editor=editor
    def schema(self,index):
        identity=self.editor.selected();key=self.editor.table.item(index.row(),0).text()
        return nodes.specs(self.editor.graph['nodes'][identity]['type'])[key]
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
        return widget
    def setEditorData(self,widget,index):
        spec=self.schema(index);raw=index.data();value=json.loads(raw) if raw else default_value(spec)
        if isinstance(widget,QtWidgets.QComboBox):widget.setCurrentIndex(max(0,widget.findData(value)))
        elif isinstance(widget,(QtWidgets.QSpinBox,QtWidgets.QDoubleSpinBox)):widget.setValue(float(value or 0) if isinstance(widget,QtWidgets.QDoubleSpinBox) else int(value or 0))
        elif isinstance(widget,VectorEdit):
            for spin,v in zip(widget.spins,value if isinstance(value,list) else [0]*len(widget.spins)):spin.setValue(v)
        else:widget.setText(str(value or '') if spec['type']=='String' else (raw or ''))
    def setModelData(self,widget,model,index):
        if isinstance(widget,QtWidgets.QComboBox):value=widget.currentData()
        elif isinstance(widget,(QtWidgets.QSpinBox,QtWidgets.QDoubleSpinBox)):value=widget.value()
        elif isinstance(widget,VectorEdit):value=[spin.value() for spin in widget.spins]
        else:
            if self.schema(index)['type']=='String':value=widget.text()
            else:
                model.setData(index,widget.text());return
        model.setData(index,json.dumps(value))
