# python
"""Isolated GUI test: the MoonRay section of a camera's right-click menu, shown on its own (attr.formPopover) and
pictured for a Modo camera (Convert to MoonRay Camera only) and for a MoonRay camera (Change to Modo Camera only)."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\camera-context')
out.mkdir(parents=True, exist_ok=True)
result = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def pop(label, then):
    try:
        lx.eval('select.item {%s} set' % modo.Scene().renderCamera.id)
        lx.eval('attr.formPopover {MoonRayCameraContext:sheet}')
    except Exception:
        result[label + '_error'] = traceback.format_exc()
    QtCore.QTimer.singleShot(2500, lambda: shoot(label, then))


def shoot(label, then):
    try:
        windows = sorted((w for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible()), key=lambda w: w.width() * w.height())
        result[label] = [(w.windowTitle(), w.width(), w.height()) for w in windows[:2]]
        windows[0].grab().save(str(out / (label + '.png')))
        windows[0].close()
    except Exception:
        result[label + '_shot_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(1000, then)


def convert():
    try:
        lx.eval('select.item {%s} set' % modo.Scene().renderCamera.id)
        lx.eval('moonray.camera.convert 0')
    except Exception:
        result['convert_error'] = traceback.format_exc()
    pop('moonray_camera', lambda: lx.eval('!app.quit'))


QtCore.QTimer.singleShot(4000, lambda: pop('modo_camera', convert))
