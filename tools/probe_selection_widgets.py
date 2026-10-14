# python
"""Isolated GUI test: do Qt widgets and the plugin's popups pile up as items are selected?

Selecting an item has Modo build its Properties panel again; a mesh's has the plugin's MoonRay settings in it, a
camera's and a light's have none of the plugin's popups. Each kind is selected back and forth twenty times, and the
Qt widgets, the plugin's ObjectPopup objects and Python's objects are counted after each kind."""
import gc
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/selection-widgets'
out.mkdir(parents=True, exist_ok=True)
result = {'counts': []}
held = {}


def count(name):
    gc.collect()
    popups = sum(1 for o in gc.get_objects() if type(o).__name__ == 'ObjectPopup')
    result['counts'].append({'after': name, 'qt_widgets': len(QtWidgets.QApplication.allWidgets()), 'object_popups': popups,
                             'python_objects': len(gc.get_objects())})
    (out / 'report.json').write_text(json.dumps(result, indent=1))


def toggle(kind, left, right, then):
    def go(n=0):
        if n >= 20:
            count(kind)
            QtCore.QTimer.singleShot(500, then)
            return
        lx.eval('!select.item {%s} set' % (left if n % 2 else right))
        QtCore.QTimer.singleShot(250, lambda: go(n + 1))
    go()


def finish():
    (out / 'report.json').write_text(json.dumps(result, indent=1))
    lx.eval('!!app.quit')


try:
    scene = modo.Scene()
    for x in (-.6, .6):
        lx.eval('select.typeFrom item')
        lx.eval('item.create mesh')
        lx.eval('tool.set prim.sphere on')
        lx.eval('tool.attr prim.sphere cenX %s' % x)
        lx.eval('tool.apply')
        lx.eval('tool.set prim.sphere off')
    meshes = [m.id for m in scene.items('mesh')][-2:]
    lx.eval('item.create camera')
    cameras = [c.id for c in scene.items('camera')][-2:]
    lx.eval('item.create pointLight')
    lights = [l.id for l in scene.items('light')][-2:]
    result['items'] = {'meshes': meshes, 'cameras': cameras, 'lights': lights}

    def start():
        count('start')
        toggle('lights', lights[0], lights[-1], lambda: toggle('cameras', cameras[0], cameras[-1],
               lambda: toggle('meshes', meshes[0], meshes[-1], lambda: toggle('meshes_again', meshes[0], meshes[-1], finish))))
    QtCore.QTimer.singleShot(6000, start)
except Exception:
    result['error'] = traceback.format_exc()
    (out / 'report.json').write_text(json.dumps(result, indent=1))
