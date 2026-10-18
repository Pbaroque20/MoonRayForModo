# python
"""Isolated GUI test: the preview's button while a MoonRay render stops. A ball is rendered with MoonRay, realtime off;
once the render is under way Stop is pressed. The button should be greyed and say Stopping until the render has
finished with what it has, then be pressable again (Render or Continue). Its state is noted every quarter second."""
import json
import pathlib
import time
import traceback
import lx
from PySide2 import QtCore, QtWidgets

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\stop-button')
out.mkdir(parents=True, exist_ok=True)
result = {'states': []}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def note(label):
    panel = panel_widget()
    result['states'].append([label, round(time.perf_counter() - held.get('t', time.perf_counter()), 2), panel.start.text(),
                             panel.start.isEnabled(), panel._rendering, panel.status.text()])


try:
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()


def begin():
    try:
        panel = panel_widget()
        held['engine'] = panel.preview_engine.currentData()
        held['live'] = panel.ipr_mode.isChecked()
        panel.ipr_mode.setChecked(False)
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        QtWidgets.QApplication.processEvents()
        panel.start.click()
        held['t'] = time.perf_counter()
        note('started')
    except Exception:
        result['begin_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(6000, press_stop)


def press_stop():
    try:
        panel = panel_widget()
        note('before stop')
        panel.start.click()
        note('stop pressed')
        held['pressed'] = time.perf_counter()
    except Exception:
        result['stop_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(250, watch)


def watch():
    try:
        panel = panel_widget()
        note('watching')
        if panel.start.isEnabled() and not panel._rendering or time.perf_counter() - held['pressed'] > 40:
            result['back_after_seconds'] = round(time.perf_counter() - held['pressed'], 2)
            panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(held['engine']))
            panel.ipr_mode.setChecked(held['live'])
            save()
            QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))
            return
    except Exception:
        result['watch_error'] = traceback.format_exc()
        save()
        QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))
        return
    save()
    QtCore.QTimer.singleShot(250, watch)


QtCore.QTimer.singleShot(5000, begin)
