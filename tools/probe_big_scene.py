# python
"""Isolated GUI test: a MoonRay example scene too large to hand over in shared memory is rendered all the same.

The bedroom example scene (MOONRAY_PROBE_NAME names another) is opened as File > Open opens it, which takes minutes,
and rendered with MoonRay in the preview window. How large the scene is as MoonRay is handed it, and which way it is
handed over (shared memory, or a file where it is over the limit), is written down; so is the status each few
seconds; and the window is pictured as the render gets under way and at the end (MOONRAY_PROBE_LIMIT seconds in)."""
import json
import os
import pathlib
import time
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/big-scene'
out.mkdir(parents=True, exist_ok=True)
name = os.environ.get('MOONRAY_PROBE_NAME', 'bedroom')
source = root / 'downloads/moonray-example-scenes/scenes' / name / 'scene.rdla'
LIMIT = float(os.environ.get('MOONRAY_PROBE_LIMIT', '240'))
# MOONRAY_PROBE_PERSISTENT=0 renders with Keep MoonRay Loaded switched off, as a user of an older version can.
LOADED = os.environ.get('MOONRAY_PROBE_PERSISTENT', '1') != '0'
tag = name if LOADED else name + '-not-loaded'
result = {'scene': str(source), 'handed': [], 'seen': [], 'import_waited': 0}
held = {'shots': 0}


def save():
    (out / (tag + '.json')).write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def imported():
    """Whether the importer has finished bringing the scene in: it says so in its window."""
    from moonray_modo import rdl_import_dialog
    dialog = rdl_import_dialog._dialog
    text = dialog.report.toPlainText() if dialog else ''
    result['import_waited'] += 5
    if ('imported' in text or 'failed' in text or 'stopped' in text) or result['import_waited'] > 1500:
        result['import'] = text[:400]
        if dialog:
            dialog.close()
        save()
        QtCore.QTimer.singleShot(2000, render)
        return
    QtCore.QTimer.singleShot(5000, imported)


def render():
    try:
        scene = modo.Scene()
        result['meshes'] = len(scene.items('mesh'))
        result['polygons'] = sum(len(m.geometry.polygons) for m in scene.items('mesh'))
        lx.eval('moonray.open')
        QtWidgets.QApplication.processEvents()
        from moonray_modo import persistent
        write = persistent.Session._write_scene

        def told(self, request, suffix, text, payload=None):
            value = write(self, request, suffix, text, payload)
            size = len(payload) if payload is not None else len(text.encode('utf-8'))
            result['handed'].append({'kind': suffix, 'megabytes': round(size / 1048576.0, 1),
                                     'by': 'shared memory' if str(value).startswith('modo-memory:') else 'a file'})
            return value
        persistent.Session._write_scene = told
        result['limit_megabytes'] = persistent.SHARED_LIMIT / 1048576.0
        panel = panel_widget()
        panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-04-drain')))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        held['loaded_before'] = panel.preferences.get('persistent_preview')
        panel.preferences.set('persistent_preview', LOADED)
        result['keep_moonray_loaded'] = LOADED
        QtWidgets.QApplication.processEvents()
        held['began'] = time.monotonic()
        panel.start.click()
    except Exception:
        result['error'] = traceback.format_exc()
        save()
        lx.eval('!app.quit')
        return
    QtCore.QTimer.singleShot(3000, watch)


def shoot(kind):
    held['shots'] += 1
    panel_widget().window().grab().save(str(out / ('%s_%d_%s.png' % (tag, held['shots'], kind))))


def watch():
    panel = panel_widget()
    now = time.monotonic() - held['began']
    status = panel.status.text()
    result['seen'].append([round(now, 1), panel.render_timing.text(), status[:120], panel._rendering])
    if 'unavailable' in status.lower() and 'failed_at' not in result:
        result['failed_at'] = round(now, 1)
        shoot('failed')
    # Once there is a picture, and again as it goes on.
    if not panel.preview.image.isNull() and panel._rendering and held['shots'] == 0 and now > 20:
        shoot('rendering')
    if (not panel._rendering and now > 15) or now > LIMIT:
        result['ended'] = {'at': round(now, 1), 'rendering': panel._rendering, 'status': status, 'buffer': panel.buffer.currentData()}
        shoot('end')
        save()
        panel.stop()
        panel.preferences.set('persistent_preview', held.get('loaded_before', True))
        QtCore.QTimer.singleShot(3000, lambda: lx.eval('!app.quit'))
        return
    if len(result['seen']) % 10 == 0:
        save()
    QtCore.QTimer.singleShot(3000, watch)


try:
    lx.eval('scene.open {%s} normal' % source)
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(15000, imported)
