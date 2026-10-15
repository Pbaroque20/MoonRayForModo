# python
"""Isolated GUI test: the Properties form of one MoonRay material, by its shader (MOONRAY_PROBE_SHADER, default
DwaSwitchMaterial). A cube is given a new material of that shader, which is selected, and Modo's window pictured."""
import json
import os
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
SHADER = os.environ.get('MOONRAY_PROBE_SHADER', 'DwaSwitchMaterial')
out = root / 'test-results/material-shader-form'
out.mkdir(parents=True, exist_ok=True)
result = {'shader': SHADER}


def shot():
    shown = [w for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible()]
    max(shown, key=lambda w: w.width() * w.height()).grab().save(str(out / ('%s.png' % SHADER)))


def finish():
    try:
        shot()
    except Exception:
        result['shot_error'] = traceback.format_exc()
    (out / ('%s.json' % SHADER)).write_text(json.dumps(result, indent=2, default=str))
    QtCore.QTimer.singleShot(500, lambda: lx.eval('app.quit'))


try:
    from moonray_modo import properties
    scene = modo.Scene()
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('moonray.library.assign %s' % properties.encode({'shader': SHADER, 'parameters': {}}))
    result['selected'] = [(item.name, item.type) for item in scene.selected]
except Exception:
    result['error'] = traceback.format_exc()
QtCore.QTimer.singleShot(7000, finish)
