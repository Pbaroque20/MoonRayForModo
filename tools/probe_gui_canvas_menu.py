# python
"""Isolated GUI test: the graph editor's right-click menu. A graph with an Ocean node: right-clicked, its menu offers Set as
Displacement Output, which adds a Vector Displacement fed by it as the output; right-clicked again, Clear Displacement Output;
the surface node offers Set as Material Output; empty canvas offers Add Node. Each menu's entries are recorded and one
chosen by name (QMenu.exec_ answered here, as the menu reads the chosen entry's data). Writes test-results/canvas-menu/report.json."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtGui, QtWidgets

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\canvas-menu')
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def right_click(view, point, choose):
    """The menu at point: its entries, and the one named choose triggered."""
    seen = {}
    original = QtWidgets.QMenu

    class Answered(original):
        """The menu, answered here: its entries recorded and the one named choose picked, as a click would."""
        def exec_(self, *args, **kwargs):
            actions = [a for a in self.actions() if not a.isSeparator()]
            seen['entries'] = [a.text() for a in actions]
            return next((a for a in actions if a.text().split('	')[0] == choose), None)
    QtWidgets.QMenu = Answered
    try:
        event = QtGui.QContextMenuEvent(QtGui.QContextMenuEvent.Mouse, point, view.viewport().mapToGlobal(point))
        QtWidgets.QApplication.sendEvent(view.viewport(), event)
    finally:
        QtWidgets.QMenu = original
    QtWidgets.QApplication.instance().processEvents()
    return seen.get('entries')


def centre(editor, identity):
    item = editor.items[identity]
    return editor.view.mapFromScene(item.sceneBoundingRect().center())


def run():
    try:
        editor = held['editor']
        view = editor.view
        result['ocean menu'] = right_click(view, centre(editor, 'sea'), 'Set as Displacement Output')
        shown = editor.graph.get('displacement')
        result['output after set'] = editor.graph['nodes'].get(shown, {}).get('type')
        result['fed by ocean'] = (editor.graph['nodes'].get(shown, {}).get('inputs') or {}).get('vector') == 'sea'
        result['ocean menu again'] = right_click(view, centre(editor, 'sea'), 'Clear Displacement Output')
        result['output after clear'] = editor.graph.get('displacement')
        result['surface menu'] = right_click(view, centre(editor, 'surface'), None)
        corner = QtCore.QPoint(view.viewport().width() - 10, view.viewport().height() - 10)
        result['canvas menu'] = right_click(view, corner, None)
        result['ok'] = (result['output after set'] == 'VectorDisplacement' and result['fed by ocean']
                        and result['output after clear'] is None and any('Material Output' in entry for entry in (result['surface menu'] or []))
                        and result['canvas menu'][0].startswith('Add Node'))
    except Exception:
        result['error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(200, lambda: lx.eval('!app.quit'))


try:
    from moonray_modo import nodes, properties
    from moonray_modo.node_editor import Editor
    graph = nodes.new()
    graph['nodes']['sea'] = {'type': 'ocean', 'parameters': {}, 'inputs': {}, 'position': [-400, 0]}
    item = modo.Scene().addMaterial(name='Canvas menu test')
    properties.write(item, {'node_graph': graph, 'node_override': True})
    editor = Editor(item)
    held['editor'] = editor
    editor.show()
    QtCore.QTimer.singleShot(1500, run)
except Exception:
    result['error'] = traceback.format_exc()
    save()
