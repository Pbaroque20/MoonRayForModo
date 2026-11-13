# python
"""Isolated GUI test: the docked graph editor and the preview window's Solo menu. Two MoonShine materials; MoonRay >
Use Graph Editor in Current Viewport (moonray.graph.dock) puts the editor in the viewport; selecting each material
in turn shows its graph there. Then the MoonRay preview window (moonray.open): its Solo menu's entries, Solo Selected
Meshes with a mesh selected, and Stop Solo. Each step on a timer, Modo's own events run between them (the views are
made there). Run with --show: a minimized Modo shows no viewport. Writes test-results/graph-dock/report.json."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\graph-dock')
out.mkdir(parents=True, exist_ok=True)
result = {'shown after selecting': []}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def find(kind_name):
    return [w for w in QtWidgets.QApplication.allWidgets() if type(w).__name__ == kind_name]


def later(call, ms=1500):
    def run():
        try:
            call()
        except Exception:
            result.setdefault('errors', []).append(traceback.format_exc())
            save()
            QtCore.QTimer.singleShot(300, lambda: lx.eval('!app.quit'))
    QtCore.QTimer.singleShot(ms, run)


def dock_open():
    lx.eval('moonray.graph.dock')
    later(lambda: select(0))


def select(index):
    docks = find('GraphDock')
    result['docks'] = len(docks)
    if docks:
        result['dock visible'] = docks[0].isVisible()
    if index >= len(held['materials']):
        result['dock ok'] = result['shown after selecting'] == [m.name for m in held['materials']]
        save()
        later(panel_open, 300)
        return
    lx.eval('select.item {%s} set' % held['materials'][index].id)
    from moonray_modo.graph_dock import chosen_material
    result.setdefault('chosen', []).append(getattr(chosen_material(), 'name', None))
    result.setdefault('selected', []).append([(i.name, i.type) for i in modo.Scene().selected])

    def look():
        dock = find('GraphDock')[0] if find('GraphDock') else None
        result['shown after selecting'].append(dock.editor.item.name if dock is not None and dock.editor is not None else None)
        if dock is not None and dock.editor is not None:
            editor = dock.editor
            result['lean'] = {'library shown': editor.library.isVisible(), 'widget': type(editor.material_preview).__name__,
                              'footer shown': editor.info.isVisible(), 'properties shown': editor.table.isVisible(), 'canvas width': editor.view.width(), 'dock width': dock.width()}
            # Node Inputs on, then off again (its stored choice left off, as it starts).
            editor.show_inputs.setChecked(True)
            QtWidgets.QApplication.instance().processEvents()
            result['inputs on'] = {'shown': editor.property_title.isVisible(), 'canvas width': editor.view.width()}
            editor.show_inputs.setChecked(False)
            QtWidgets.QApplication.instance().processEvents()
            result['inputs off'] = {'shown': editor.property_title.isVisible(), 'canvas width': editor.view.width()}
        select(index + 1)
    later(look, 1500)


def panel_open():
    lx.eval('moonray.open')
    later(panel_check, 12000)


def panel_check():
    from moonray_modo import solo
    panels = [w for w in QtWidgets.QApplication.allWidgets() if hasattr(w, 'solo_menu') and hasattr(w, '_solo_meshes')]
    result['panels'] = len(panels)
    result['windows'] = [w.windowTitle() for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible()][:20]
    result['panel-like'] = sorted({type(w).__module__ + '.' + type(w).__name__ for w in QtWidgets.QApplication.allWidgets() if 'moonray' in type(w).__module__})[:30]
    if not panels:
        # Made here where the window made none, to see whether it can be made at all.
        from moonray_modo.panel import Panel
        held['panel'] = Panel(None)
        panels = [held['panel']]
        result['panel made by the probe'] = True
    panel = panels[0]
    result['solo menu'] = [a.text() for a in panel.solo_menu.actions()]
    lx.eval('select.item {%s} set' % held['mesh'].id)
    panel._solo_meshes()
    result['soloed'] = solo.current()
    result['menu title while soloed'] = panel.solo_menu.title()
    panel._solo_stop()
    result['after stop'] = solo.current()
    result['panel ok'] = ((result['soloed'] or {}).get('meshes') == [held['mesh'].id] and result['after stop'] is None
                          and panel.solo_menu.title() == 'Solo')
    save()
    later(lambda: lx.eval('!app.quit'), 300)


try:
    from moonray_modo import nodes, properties
    scene = modo.Scene()
    held['materials'] = []
    for name in ('Dock test A', 'Dock test B'):
        item = scene.addMaterial(name=name)
        properties.write(item, {'node_graph': nodes.new(), 'node_override': True, 'moonshine_override': True,
                                'native_shader': 'DwaBaseMaterial'})
        held['materials'].append(item)
    held['mesh'] = scene.addMesh('Solo test mesh')
    later(dock_open, 2500)
except Exception:
    result['error'] = traceback.format_exc()
    save()
