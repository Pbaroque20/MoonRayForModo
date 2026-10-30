# python
"""Isolated GUI test (tools/launch_gui_probe.py, a test profile): the preview window with its memory meter in the
picture (Memory in the picture, Preview Preferences), grabbed whole into MOONRAY_PROBE_OUT/panel.png, with where the
meter stands and what it says in report.json."""
import json
import os
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

out = pathlib.Path(os.environ['MOONRAY_PROBE_OUT'])
out.mkdir(parents=True, exist_ok=True)
result = {}


def grab():
    try:
        from moonray_modo.panel import Panel
        view = next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))
        view.window().resize(1000, 700)
        QtWidgets.QApplication.processEvents()
        meter = view.memory_meter
        result.update(parent=type(meter.parentWidget()).__name__, visible=meter.isVisible(), text=meter.text(),
                      at=[meter.x(), meter.y(), meter.width(), meter.height()], picture=[view.preview.width(), view.preview.height()])
        view.grab().save(str(out / 'panel.png'))
    except Exception:
        result['error'] = traceback.format_exc()
    (out / 'report.json').write_text(json.dumps(result, indent=1), encoding='utf-8')
    QtCore.QTimer.singleShot(300, lambda: lx.eval('!app.quit'))


try:
    lx.eval('moonray.open')
except Exception:
    result['error_open'] = traceback.format_exc()
QtCore.QTimer.singleShot(7000, grab)
