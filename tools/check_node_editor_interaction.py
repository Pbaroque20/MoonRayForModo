"""Deferred Modo Qt test. Opens a temporary editor; never saves to a scene item.
Run inside Modo 16.1v9 using @ followed by this script path.
"""
import copy
from PySide2 import QtCore,QtWidgets,QtTest
from moonray_modo import nodes,properties
from moonray_modo.node_editor import Editor
from moonray_modo.node_widgets import default_value
class Fixture:
    name='Node editor interaction check'
graph=nodes.new();graph['nodes']['image']={'type':'constant','parameters':{'value':[.4,.2,.1]},'inputs':{},'position':[-200,50]}
old_read=properties.read
properties.read=lambda item:{'node_graph':copy.deepcopy(graph)} if isinstance(item,Fixture) else old_read(item)
editor=None
try:
    editor=Editor(Fixture());editor.show();QtWidgets.QApplication.processEvents()
    editor.frame();QtWidgets.QApplication.processEvents()
    source=editor.items['image'].sockets[None];target=editor.items['surface'].sockets['albedo']
    start=editor.view.mapFromScene(source.scenePos());end=editor.view.mapFromScene(target.scenePos())
    QtTest.QTest.mousePress(editor.view.viewport(),QtCore.Qt.LeftButton,QtCore.Qt.NoModifier,start)
    QtTest.QTest.mouseMove(editor.view.viewport(),end,100)
    QtTest.QTest.mouseRelease(editor.view.viewport(),QtCore.Qt.LeftButton,QtCore.Qt.NoModifier,end)
    QtWidgets.QApplication.processEvents()
    assert editor.graph['nodes']['surface']['inputs']['albedo']=='image'
    editor.undo();assert 'albedo' not in editor.graph['nodes']['surface']['inputs']
    editor.redo();assert editor.graph['nodes']['surface']['inputs']['albedo']=='image'
    assert not editor.can_connect('surface','image','value')
    editor.unlink('surface','albedo');assert 'albedo' not in editor.graph['nodes']['surface']['inputs']
    assert default_value({'type':'Float','default':'0.35f'})==.35
    assert default_value({'type':'Bool','default':'false'}) is False
    assert default_value({'type':'Rgb','default':'Rgb(0.5f, 0.2f, 1.0f)'})==[.5,.2,1.]
    print('Node editor drag, undo/redo, disconnection and defaults passed')
finally:
    properties.read=old_read
    if editor:editor.reject();editor.deleteLater()
