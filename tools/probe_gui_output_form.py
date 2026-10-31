# python
"""Isolated GUI test: a material's graph output changes from DwaBaseMaterial to DwaMetalMaterial as the graph editor writes it. Does
Modo's form follow? For an assigned material and for an Add Layer one: which packages it holds, whether the commands of each
shader's form are enabled, and a picture of the window before and after. Writes test-results/output-form/."""
import json
import pathlib
import sys
import time
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/output-form'
out.mkdir(parents=True, exist_ok=True)
result = {}


def shot(name):
    """The screen once Modo has drawn: its forms are not Qt's, so a grab of the window alone can miss them."""
    started = time.time()
    while time.time() - started < 1.5:
        QtWidgets.QApplication.processEvents()
        time.sleep(.02)
    QtWidgets.QApplication.primaryScreen().grabWindow(0).save(str(out / (name + '.png')))


def state(item):
    from moonray_modo import properties, shader_library
    packages = [name for name in shader_library.catalog() if item.internalItem.PackageTest('moonray.shader.' + name)]
    settings = properties.read(item)
    return {'packages': packages, 'native_shader': settings.get('native_shader'), 'root': (settings.get('node_graph') or {}).get('root'),
            'colour': (settings.get('native_parameters') or {}).get('albedo') or (settings.get('native_parameters') or {}).get('metallic_color'),
            'diffuse': [item.channel('diffCol.' + a).get() for a in 'RGB'],
            'selected': any(chosen.id == item.id for chosen in modo.Scene().selected)}


def change(item, name):
    from moonray_modo import material_override, nodes, properties
    lx.eval('select.item {%s} set' % item.id)
    graph = {'version': 1, 'root': 'first', 'nodes': {
        'first': {'type': 'DwaBaseMaterial', 'parameters': {'albedo': [1.0, 0.0, 0.0]}, 'inputs': {}},
        'second': {'type': 'DwaMetalMaterial', 'parameters': {}, 'inputs': {}}}}
    settings = material_override.synchronize(properties.read(item), graph)
    lx.eval('moonray.material.applyGraph {%s} %s' % (item.id, properties.encode(settings)))
    report = {'before': state(item)}
    shot(name + '-before')
    settings = material_override.synchronize(properties.read(item), dict(graph, root='second'))
    lx.eval('moonray.material.applyGraph {%s} %s' % (item.id, properties.encode(settings)))
    report['after'] = state(item)
    shot(name + '-after')
    return report


def write_report():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def undo_steps(item, name):
    """Modo refuses undo inside a script, so these run on timers once the script is over."""
    def step(command, key):
        def run():
            try:
                lx.eval(command)
                result[name + '-' + key] = state(item)
                write_report()
                QtCore.QTimer.singleShot(1200, lambda: QtWidgets.QApplication.primaryScreen().grabWindow(0).save(str(out / ('%s-%s.png' % (name, key)))))
            except Exception:
                result[name + '-' + key + '-error'] = traceback.format_exc()
                write_report()
        return run
    return step('app.undo', 'undone'), step('app.redo', 'redone')


try:
    lx.eval('scene.new')
    scene = modo.Scene()
    assigned = scene.addItem('advancedMaterial', name='Assigned')
    assigned.setParent(scene.renderItem, 0)
    layer = scene.addItem('material.dw.DwaBaseMaterial', name='Layer')
    layer.setParent(scene.renderItem, 0)
    shot('marked')
    result['layer_as_made'] = state(layer)
    # The layer, then the scene from before layers had a package; last, on timers, undo and redo on what is then the scene.
    result['assigned'] = change(assigned, 'assigned')
    result['layer'] = change(layer, 'layer')
    old = scene.addItem('material.dw.DwaRefractiveMaterial', name='Old layer')
    old.setParent(scene.renderItem, 0)
    shot('old-made')
    old.internalItem.PackageRemove('moonray.shader.DwaRefractiveMaterial')
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'old.lxo'))
    lx.eval('!scene.close')
    lx.eval('!scene.open {%s} normal' % (out / 'old.lxo'))
    shot('old-open')
    scene = modo.Scene()
    old = next(iter(scene.items('material.dw.DwaRefractiveMaterial')))
    lx.eval('select.item {%s} set' % old.id)
    shot('old-selected')
    result['old_layer'] = state(old)
    lx.eval('scene.new')
    scene = modo.Scene()
    fresh = scene.addItem('advancedMaterial', name='Fresh')
    fresh.setParent(scene.renderItem, 0)
    fresh_report = change(fresh, 'fresh')
    result['fresh'] = fresh_report
    sys._probe_shots = []
    undo, redo = undo_steps(fresh, 'fresh')
    sys._probe_steps = (undo, redo)
    QtCore.QTimer.singleShot(2000, undo)
    QtCore.QTimer.singleShot(5000, redo)
except Exception:
    result['error'] = traceback.format_exc()
write_report()
