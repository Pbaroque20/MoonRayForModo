# python
"""Isolated GUI test: a scene closed under the graph editor. A first scene with a material; a second scene made, its
material's graph open in an editor window and in the dock (moonray.graph.dock); the second scene closed. The window
must close and the dock let go of the material, nothing written; then the first scene's material, selected, shows in
the dock. Run with --show. Writes test-results/scene-close/report.json."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\scene-close')
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def later(call, ms=1500):
    def run():
        try:
            call()
        except Exception:
            result.setdefault('errors', []).append(traceback.format_exc())
            save()
            QtCore.QTimer.singleShot(300, lambda: lx.eval('!app.quit'))
    QtCore.QTimer.singleShot(ms, run)


def made(name):
    """A MoonShine material made by Modo's commands (an item added from a timer, outside a command, is refused)."""
    from moonray_modo import nodes, properties
    before = {i.id for i in modo.Scene().items('advancedMaterial')}
    lx.eval('shader.create advancedMaterial')
    item = next(i for i in modo.Scene().items('advancedMaterial') if i.id not in before)
    lx.eval('!item.name {%s} item:{%s}' % (name, item.id))
    settings = {'node_graph': nodes.new(), 'node_override': True, 'moonshine_override': True, 'native_shader': 'DwaBaseMaterial'}
    lx.eval('moonray.material.applyGraph {%s} %s' % (item.id, properties.encode(settings)))
    return item


def docks():
    return [w for w in QtWidgets.QApplication.allWidgets() if type(w).__name__ == 'GraphDock']


def first():
    held['first'] = made('In the first scene')
    lx.eval('scene.new')
    later(second, 1500)


def second():
    from moonray_modo.node_editor import open_editor
    held['second'] = made('In the second scene')
    held['window'] = open_editor(held['second'])
    lx.eval('moonray.graph.dock')
    lx.eval('select.item {%s} set' % held['second'].id)
    later(before, 1500)


def before():
    from shiboken2 import isValid
    dock = docks()[0]
    result['dock before'] = dock.editor.item.name if dock.editor is not None else None
    result['window before'] = isValid(held['window']) and held['window'].isVisible()
    result['closing scene with'] = [i.name for i in modo.Scene().items('advancedMaterial')]
    lx.eval('!scene.close')
    later(after, 1500)


def after():
    from shiboken2 import isValid
    dock = docks()[0] if docks() else None
    result['window after'] = isValid(held['window']) and held['window'].isVisible()
    result['dock after'] = dock.editor.item.name if dock is not None and dock.editor is not None else None
    result['current scene materials'] = [i.name for i in modo.Scene().items('advancedMaterial')]
    first_material = next((i for i in modo.Scene().items('advancedMaterial') if i.name == 'In the first scene'), None)
    if first_material is not None:
        lx.eval('select.item {%s} set' % first_material.id)
    later(followed, 1500)


def followed():
    dock = docks()[0] if docks() else None
    result['dock follows'] = dock.editor.item.name if dock is not None and dock.editor is not None else None
    result['ok'] = bool(result.get('window before') and not result.get('window after') and result.get('dock after') is None
                        and result.get('dock follows') == 'In the first scene')
    save()
    later(lambda: lx.eval('!app.quit'), 300)


later(first, 2500)
