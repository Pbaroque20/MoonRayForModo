# python
"""Isolated GUI test: MoonRay > Open MoonShine Graph Editor (moonray.graph.open) with nothing selected: the window opens
with no graph, the line and the list of the scene's materials with a graph; a material chosen in the list is edited
there; the window closed, Modo quits (the exit code says whether it crashed: 1 is clean). report.json in
MOONRAY_PROBE_OUT (else test-results/graph-window)."""
import json
import os
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore

out = pathlib.Path(os.environ.get('MOONRAY_PROBE_OUT') or r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\graph-window')
out.mkdir(parents=True, exist_ok=True)
result = {'errors': []}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def later(call, ms=1500):
    def run():
        try:
            call()
        except Exception:
            result['errors'].append(traceback.format_exc())
            finish()
    QtCore.QTimer.singleShot(ms, run)


def finish():
    save()
    QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))


def material(name):
    from moonray_modo import properties
    scene = modo.Scene()
    mesh = scene.addMesh(name + 'Box')
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('poly.setMaterial %s' % name)
    mask = [i for i in scene.items('mask') if i.name.startswith(name)][0]
    lx.eval('select.item {%s} set' % mask.id)
    lx.eval('shader.create advancedMaterial')
    item = [i for i in scene.selected if i.type == 'advancedMaterial'][-1]
    item.name = name
    settings = properties.read(item)
    settings.update(moonshine_override=True, native_shader='DwaBaseMaterial', shader='DwaBaseMaterial', native_parameters={})
    properties.write(item, settings)
    return item


def opened():
    from moonray_modo import graph_dock
    window = graph_dock._window[0]
    dock = window.dock
    result['opened'] = {'visible': window.isVisible(), 'title': window.windowTitle(), 'editor': dock.editor is not None,
                        'line': dock.placeholder.text(), 'list': [dock.picker.itemText(i) for i in range(dock.picker.count())]}
    index = next(i for i in range(dock.picker.count()) if dock.picker.itemText(i).endswith('/  Wood'))
    dock.picker.setCurrentIndex(index)
    dock.picker.activated.emit(index)
    later(lambda: picked(window), 2500)


def picked(window):
    dock = window.dock
    result['picked'] = {'editor': dock.editor is not None, 'material': dock.editor.item.name if dock.editor else None,
                        'list_hidden': not dock.empty.isVisible()}
    # Modo's selection still empty: the chosen material stays.
    later(lambda: kept(window), 1500)


def kept(window):
    dock = window.dock
    result['kept'] = {'material': dock.editor.item.name if dock.editor else None}
    window.close()
    later(lambda: (result.__setitem__('closed', True), finish()), 1500)


try:
    lx.eval('scene.new')
    material('Wood')
    material('Steel')
    lx.eval('select.drop item')
    lx.eval('moonray.graph.open')
    later(opened, 2500)
except Exception:
    result['errors'].append(traceback.format_exc())
    save()
    lx.eval('!app.quit')
