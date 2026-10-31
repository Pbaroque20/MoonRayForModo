# python
"""Isolated GUI test: which Properties tab Modo brings to the front for a material, as a layer or assigned material is selected and
as a graph's output changes. Runs on timers. Writes test-results/output-tabs/<step>.png, Modo's right side."""
import json
import pathlib
import sys
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/output-tabs'
out.mkdir(parents=True, exist_ok=True)
result = {}
GRAPH = {'version': 1, 'root': 'first', 'nodes': {
    'first': {'type': 'DwaBaseMaterial', 'parameters': {'albedo': [1.0, 0.0, 0.0]}, 'inputs': {}},
    'second': {'type': 'DwaMetalMaterial', 'parameters': {}, 'inputs': {}}}}


def apply(item, root_node):
    from moonray_modo import material_override, properties
    settings = material_override.synchronize(properties.read(item), dict(GRAPH, root=root_node))
    lx.eval('moonray.material.applyGraph {%s} %s' % (item.id, properties.encode(settings)))


def select(item):
    lx.eval('select.item {%s} set' % item.id)


def drop():
    lx.eval('select.drop item')


lx.eval('scene.new')
scene = modo.Scene()
assigned = scene.addItem('advancedMaterial', name='Assigned')
assigned.setParent(scene.renderItem, 0)
layer = scene.addItem('material.dw.DwaBaseMaterial', name='Layer')
layer.setParent(scene.renderItem, 0)
apply(assigned, 'first')
apply(layer, 'first')
STEPS = [('1-assigned', lambda: select(assigned)),
         ('2-assigned-second', lambda: apply(assigned, 'second')),
         ('3-assigned-first', lambda: apply(assigned, 'first')),
         ('4-assigned-undo', lambda: lx.eval('app.undo')),
         ('5-layer', lambda: select(layer)),
         ('6-layer-second', lambda: apply(layer, 'second')),
         ('7-layer-undo', lambda: lx.eval('app.undo'))]


def on_top():
    """Modo's window over everything, without asking for the focus: another window in front spoils the picture."""
    import ctypes
    import os
    user32 = ctypes.windll.user32
    found = []
    callback = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def each(window, _):
        owner = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(ctypes.c_void_p(window), ctypes.byref(owner))
        text = ctypes.create_unicode_buffer(200)
        user32.GetWindowTextW(ctypes.c_void_p(window), text, 200)
        if owner.value == os.getpid() and text.value.endswith('- Modo'):
            found.append(window)
        return True
    user32.EnumWindows(callback(each), None)
    for window in found:
        user32.SetWindowPos(ctypes.c_void_p(window), ctypes.c_void_p(-1), 0, 0, 0, 0, 3)


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
            on_top()
        except Exception:
            result[name + '-top-error'] = traceback.format_exc()

        def grab():
            whole = QtWidgets.QApplication.primaryScreen().grabWindow(0)
            whole.copy(1600, 225, 320, 215).save(str(out / (name + '.png')))
            (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
            QtCore.QTimer.singleShot(50, lambda: run(index + 1))
        QtCore.QTimer.singleShot(400, grab)
    QtCore.QTimer.singleShot(900, record)


sys._probe_run = run
QtCore.QTimer.singleShot(2500, run)
