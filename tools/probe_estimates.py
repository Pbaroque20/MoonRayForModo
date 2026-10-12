# python
"""Isolated GUI test: what the time-left estimate says through a real render, against what turned out to be true.

A MoonRay example scene (MOONRAY_PROBE_RDL, the coffee maker unless named) is opened as File > Open opens it and
rendered with MoonRay. Every progress report MoonRay makes is kept with its time, and once a second what the window
shows. tools/check_estimates.py then replays the reports through the estimate and sets it beside the time that was
really left. MOONRAY_PROBE_WIDTH narrows the picture so that the render ends in minutes; MOONRAY_PROBE_LIMIT is how
long to go on, in seconds."""
import json
import os
import pathlib
import time
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/estimates'
out.mkdir(parents=True, exist_ok=True)
name = os.environ.get('MOONRAY_PROBE_NAME', 'coffee_maker')
source = pathlib.Path(os.environ.get('MOONRAY_PROBE_RDL', str(root / 'downloads/moonray-example-scenes/scenes' / name / 'scene.rdla')))
LIMIT = float(os.environ.get('MOONRAY_PROBE_LIMIT', '420'))
result = {'scene': str(source), 'fed': [], 'shown': [], 'passes': []}
held = {}


def save():
    (out / ('%s.json' % name)).write_text(json.dumps(result, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def opened():
    try:
        from moonray_modo import rdl_import_dialog, progress
        dialog = rdl_import_dialog._dialog
        result['import'] = dialog.report.toPlainText()[:200] if dialog else None
        if dialog:
            dialog.close()
        scene = modo.Scene()
        width = int(os.environ.get('MOONRAY_PROBE_WIDTH', '0'))
        if width:
            item = scene.renderItem
            was = (item.channel('resX').get(), item.channel('resY').get())
            lx.eval('render.res 0 %d' % width)
            lx.eval('render.res 1 %d' % max(16, round(width * was[1] / max(1, was[0]))))
        result['size'] = [scene.renderItem.channel('resX').get(), scene.renderItem.channel('resY').get()]
        lx.eval('moonray.open')
        QtWidgets.QApplication.processEvents()
        feed, reset = progress.Progress.feed, progress.Progress.reset_pass

        def fed(self, text):
            if '@@MODO_PROGRESS' in text or 'Rendering' in text:
                result['fed'].append([round(time.monotonic() - held['began'], 3), text])
            return feed(self, text)

        def passed(self):
            if 'began' in held:
                result['passes'].append(round(time.monotonic() - held['began'], 3))
            return reset(self)
        plan = progress.Progress.plan

        def planned(self, units, adaptive=False):
            result['plan'] = list(units or [])
            result['adaptive'] = bool(adaptive)
            return plan(self, units, adaptive)
        progress.Progress.feed, progress.Progress.reset_pass, progress.Progress.plan = fed, passed, planned
        QtCore.QTimer.singleShot(3000, render)
    except Exception:
        result['error'] = traceback.format_exc()
        save()
        lx.eval('!app.quit')


def render():
    try:
        panel = panel_widget()
        panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-0351-tiles')))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        QtWidgets.QApplication.processEvents()
        held['began'] = time.monotonic()
        panel.start.click()
    except Exception:
        result['error'] = traceback.format_exc()
        save()
        lx.eval('!app.quit')
        return
    QtCore.QTimer.singleShot(1000, watch)


def watch():
    panel = panel_widget()
    now = time.monotonic() - held['began']
    result['shown'].append([round(now, 2), panel.render_timing.text(), panel.status.text()[:60]])
    if (panel._rendering or now < 5) and now < LIMIT:
        if len(result['shown']) % 20 == 0:
            save()
        QtCore.QTimer.singleShot(1000, watch)
        return
    result['finished'] = not panel._rendering
    result['took'] = round(now, 1)
    save()
    panel.stop()
    QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))


try:
    lx.eval('scene.open {%s} normal' % source)
except Exception:
    result['error'] = traceback.format_exc()
save()
# The importer fills the scene by itself once it has read the file.
QtCore.QTimer.singleShot(int(float(os.environ.get('MOONRAY_PROBE_IMPORT', '45')) * 1000), opened)
