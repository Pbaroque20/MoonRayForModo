# python
"""Isolated GUI test: a scene (MOONRAY_PROBE_LXO) rendered by XPU2 in XPU mode, and everything its session says of memory:
what its geometry and textures take on the card, the fine-detail texture cache, whether it went into texture overflow mode
and why. Writes test-results/texture-overflow/report.json (the session's lines kept in full in session.log)."""
import json
import os
import pathlib
import time
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/texture-overflow'
out.mkdir(parents=True, exist_ok=True)
source = os.environ.get('MOONRAY_PROBE_LXO', r'C:\Users\Raphael Tobar\Downloads\Grass\wildGreen_Patches_bundled.lxo')
LIMIT = float(os.environ.get('MOONRAY_PROBE_LIMIT', '300'))
result = {'scene': source, 'status': []}
held = {}
WORDS = ('memory', 'texture', 'overflow', 'MB', 'GB', 'prepared', 'FALLBACK', 'NOTICE', 'tiles', 'instance', 'triangles', 'card')


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def lines():
    from moonray_modo import terminal
    found = []
    # (serial, time, kind, source, text)
    for entry in terminal.entries():
        found.extend(str(entry[4]).splitlines())
    return found


def begin():
    try:
        lx.eval('moonray.open')
        QtWidgets.QApplication.processEvents()
        panel = held['panel'] = panel_widget()
        panel.preferences.set('xpu2/renderer', 'xpu2')
        panel._store(execution_mode='xpu')
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        held['began'] = time.monotonic()
        panel.start.click()
        QtCore.QTimer.singleShot(2000, watch)
    except Exception:
        result['error'] = traceback.format_exc();save()
        QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))


def watch():
    panel = held['panel']
    now = round(time.monotonic() - held['began'], 1)
    said = panel.status.text()
    if said and (not result['status'] or result['status'][-1][1] != said):result['status'].append([now, said])
    if (panel._rendering or now < 10) and now < LIMIT:
        QtCore.QTimer.singleShot(2000, watch);return
    try:
        session = getattr(panel.renderer, 'session', None)
        result.update(seconds=now, info=panel.image_info.text(), xpu2_active=getattr(session, 'xpu2_active', None),
                      xpu2_refused=getattr(session, 'xpu2_refused', None))
        everything = lines()
        (out / 'session.log').write_text('\n'.join(everything), encoding='utf-8')
        result['memory_lines'] = [l for l in everything if any(w in l for w in WORDS)][:120]
        panel.window().grab().save(str(out / 'window.png'))
        if panel._rendering:panel.stop()
    except Exception:
        result['watch_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(3000, lambda: lx.eval('!app.quit'))


try:
    lx.eval('scene.open {%s} normal' % source)
    result['opened'] = True
except Exception:
    result['open_error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(20000, begin)
