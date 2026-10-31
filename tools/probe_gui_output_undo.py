# python
"""Isolated GUI test: undo and redo of a graph's output changing, an assigned material and a layer one, the form on the screen each
time, and whether marking a layer of an older scene leaves the undo history (MOONRAY_PROBE_OLD_SCENE names a scene holding an
unmarked DwaRefractiveMaterial layer). Runs on timers: Modo refuses undo inside a script, and groups a
script's commands as one. Writes test-results/output-undo/."""
import json
import os
import pathlib
import sys
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/output-undo'
out.mkdir(parents=True, exist_ok=True)
result = {}
GRAPH = {'version': 1, 'root': 'first', 'nodes': {
    'first': {'type': 'DwaBaseMaterial', 'parameters': {'albedo': [1.0, 0.0, 0.0]}, 'inputs': {}},
    'second': {'type': 'DwaMetalMaterial', 'parameters': {}, 'inputs': {}}}}


def state(item):
    from moonray_modo import properties, shader_library
    settings = properties.read(item)
    return {'packages': [name for name in shader_library.catalog() if item.internalItem.PackageTest('moonray.shader.' + name)],
            'native_shader': settings.get('native_shader'), 'diffuse': [item.channel('diffCol.' + a).get() for a in 'RGB'],
            'selected': any(chosen.id == item.id for chosen in modo.Scene().selected)}


def apply(item, root_node):
    from moonray_modo import material_override, properties
    settings = material_override.synchronize(properties.read(item), dict(GRAPH, root=root_node))
    lx.eval('moonray.material.applyGraph {%s} %s' % (item.id, properties.encode(settings)))


lx.eval('!scene.open {%s} normal' % os.environ['MOONRAY_PROBE_OLD_SCENE'])
scene = modo.Scene()
old = next(iter(scene.items('material.dw.DwaRefractiveMaterial')))
result['old_as_loaded'] = state(old)
assigned = scene.addItem('advancedMaterial', name='Assigned')
assigned.setParent(scene.renderItem, 0)
layer = scene.addItem('material.dw.DwaBaseMaterial', name='Layer')
layer.setParent(scene.renderItem, 0)


def steps_for(item, name):
    return [(name + '-select', lambda: lx.eval('select.item {%s} set' % item.id)),
            (name + '-first', lambda: apply(item, 'first')),
            (name + '-second', lambda: apply(item, 'second')),
            (name + '-undo', lambda: lx.eval('app.undo')),
            (name + '-redo', lambda: lx.eval('app.redo'))]


STEPS = steps_for(assigned, 'assigned') + steps_for(layer, 'layer') + [
    ('assigned-again', lambda: lx.eval('select.item {%s} set' % assigned.id)),
    ('assigned-third', lambda: apply(assigned, 'first')),
    ('select-old', lambda: lx.eval('select.item {%s} set' % old.id)),
    ('undo-select-old', lambda: lx.eval('app.undo')),
    ('made-layer', lambda: lx.eval('item.create material.dw.DwaSkinMaterial')),
    ('undo-made-layer', lambda: lx.eval('app.undo')),
    ('undo-third', lambda: lx.eval('app.undo')),
    ('redo-third', lambda: lx.eval('app.redo')),
    ('redo-made-layer', lambda: lx.eval('app.redo'))]
WATCHED = {'assigned': assigned, 'layer': layer, 'old': old}


def run(index=0):
    if index == len(STEPS):
        result['done'] = True
        (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
        return
    name, action = STEPS[index]
    try:
        action()
    except Exception:
        result[name + '-error'] = traceback.format_exc()

    def record():
        try:
            result[name] = {k: state(v) for k, v in WATCHED.items()}
            result[name]['skin'] = [state(v) for v in modo.Scene().items('material.dw.DwaSkinMaterial')]
        except Exception:
            result[name + '-state-error'] = traceback.format_exc()
        QtWidgets.QApplication.primaryScreen().grabWindow(0).save(str(out / (name + '.png')))
        (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
        QtCore.QTimer.singleShot(50, lambda: run(index + 1))
    QtCore.QTimer.singleShot(1000, record)


sys._probe_run = run
QtCore.QTimer.singleShot(2500, run)
