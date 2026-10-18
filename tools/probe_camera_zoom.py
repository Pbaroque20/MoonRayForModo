# python
"""Isolated GUI test: whether Modo's viewport, looking through a MoonRay camera, follows its lens.

A cube, and a MoonRay perspective camera 4 m from it. The viewport looks through the camera at a focal length of
30 mm and then 120 mm; each is pictured (test-results/camera-gate/zoom_<mm>.png). A view that follows the lens shows
the cube four times as wide at 120 mm."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/camera-gate'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def window_picture(file):
    QtWidgets.QApplication.processEvents()
    shown = sorted((w for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible()), key=lambda w: -w.width() * w.height())
    if shown:
        shown[0].grab().save(str(out / file))


def at(focal):
    def step():
        item = held['camera']
        lx.eval('select.item {%s} set' % item.id)
        lx.eval('item.channel mr_focal %s' % focal)
        lx.eval('select.drop item')
        lx.eval('view3d.projection cam')
        lx.eval('view3d.cameraItem {%s}' % item.id)
        result[str(focal)] = {'focalLen': item.channel('focalLen').get()}
        QtCore.QTimer.singleShot(2500, lambda: window_picture('zoom_%d.png' % focal))
    return step


def run(steps, index=0):
    if index >= len(steps):
        (out / 'zoom.json').write_text(json.dumps(result, indent=1, default=str))
        lx.eval('!app.quit')
        return
    function, wait = steps[index]
    try:
        function()
    except Exception:
        result.setdefault('errors', []).append(traceback.format_exc())
    QtCore.QTimer.singleShot(wait, lambda: run(steps, index + 1))


try:
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('moonray.entity.add PerspectiveCamera')
    held['camera'] = modo.Scene().selected[-1]
    lx.eval('transform.channel pos.Z 4.0')
except Exception:
    result['error'] = traceback.format_exc()
QtCore.QTimer.singleShot(6000, lambda: run([(at(30), 4000), (at(120), 4000)]))
