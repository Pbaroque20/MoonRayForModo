# python
"""Isolated GUI test: the preview window's camera list after Convert to MoonRay Camera.

The preview is opened and its camera list noted; the render camera is converted to a MoonRay perspective camera, and
after the preview's poll has had time to run, its list is noted again, with the cameras the plugin finds and any
error in finding them."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/camera-list'
out.mkdir(parents=True, exist_ok=True)
result = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def listed(label):
    panel = panel_widget()
    result[label] = {'entries': [(panel.camera.itemText(i), panel.camera.itemData(i)) for i in range(panel.camera.count())],
                     'chosen': panel.camera.currentText()}
    try:
        from moonray_modo import camera_choice
        result[label]['choices'] = camera_choice.choices()
        result[label]['current'] = camera_choice.current()
    except Exception:
        result[label]['choices_error'] = traceback.format_exc()
    save()


def convert():
    camera = modo.Scene().renderCamera
    lx.eval('select.item {%s} set' % camera.id)
    lx.eval('moonray.camera.convert 0')
    result['converted'] = camera.id
    save()


def run(steps, index=0):
    if index >= len(steps):
        lx.eval('!app.quit')
        return
    function, wait = steps[index]
    try:
        function()
    except Exception:
        result.setdefault('errors', []).append(traceback.format_exc())
    save()
    QtCore.QTimer.singleShot(wait, lambda: run(steps, index + 1))


lx.eval('moonray.open')
QtCore.QTimer.singleShot(4000, lambda: run([(lambda: listed('before'), 300), (convert, 2500), (lambda: listed('after'), 300)]))
