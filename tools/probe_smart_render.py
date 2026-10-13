# python
"""Isolated GUI test: Smart Render stops a MoonRay render once its picture is clean enough, and denoises it.

A MoonRay example scene (MOONRAY_PROBE_NAME, the coffee maker unless named) is opened as File > Open opens it. Smart
Render is set to a level (MOONRAY_PROBE_LEVEL: 1 draft, 2 medium, 3 fine; 0 leaves it off, to see how long the render
takes by itself) with the command the render settings form uses, and the scene is rendered with MoonRay. With
MOONRAY_PROBE_STOP_AT, Stop is pressed that many seconds in, to see what a render stopped by hand keeps. Each second
what the picture's noise reads, what the foot of the picture says and the status are written down; at the end, when it
stopped, what it then showed, and the picture."""
import json
import os
import pathlib
import time
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/smart-render'
out.mkdir(parents=True, exist_ok=True)
name = os.environ.get('MOONRAY_PROBE_NAME', 'coffee_maker')
level = int(os.environ.get('MOONRAY_PROBE_LEVEL', '2'))
source = root / 'downloads/moonray-example-scenes/scenes' / name / 'scene.rdla'
LIMIT = float(os.environ.get('MOONRAY_PROBE_LIMIT', '300'))
STOP_AT = float(os.environ.get('MOONRAY_PROBE_STOP_AT', '0'))
tag = '%s-%d%s' % (name, level, '-stop%d' % STOP_AT if STOP_AT else '')
result = {'scene': str(source), 'level': level, 'seen': []}
held = {}


def save():
    (out / (tag + '.json')).write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def opened():
    try:
        from moonray_modo import rdl_import_dialog
        dialog = rdl_import_dialog._dialog
        if dialog:
            dialog.close()
        width = int(os.environ.get('MOONRAY_PROBE_WIDTH', '640'))
        item = modo.Scene().renderItem
        was = (item.channel('resX').get(), item.channel('resY').get())
        lx.eval('render.res 0 %d' % width)
        lx.eval('render.res 1 %d' % max(16, round(width * was[1] / max(1, was[0]))))
        lx.eval('moonray.render.smart_render %d' % level)
        result['setting'] = lx.eval('moonray.render.smart_render ?')
        lx.eval('moonray.open')
        QtWidgets.QApplication.processEvents()
        panel = panel_widget()
        panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-0351-tiles')))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        QtWidgets.QApplication.processEvents()
        result['menu'] = None
        panel._image_menu()
        result['menu'] = [(a.text(), a.isChecked()) for a in panel._smart_menu.actions()]
        result['denoiser_in_scene'] = panel._settings_values()['denoising']
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
    watching = getattr(panel.renderer, 'smart', None)
    result['seen'].append([round(now, 1), round(watching.noise, 4) if watching is not None and watching.noise is not None else None,
                           panel.hud.text() if panel.hud.isVisible() else None, panel.render_timing.text(), panel.status.text()[:80]])
    if STOP_AT and 'pressed' not in held and now >= STOP_AT and panel._rendering:
        held['pressed'] = now
        result['pressed_stop_at'] = round(now, 1)
        panel.start.click()
    if 'stopped' not in held and not panel._rendering and now > 5:
        held['stopped'] = now
        result['render_ended_at'] = round(now, 1)
        result['status_at_end'] = panel.status.text()
    if ('stopped' in held and now - held['stopped'] > 12) or now > LIMIT:
        frame = panel.renderer.buffers.frame or {}
        result['after'] = {'status': panel.status.text(), 'buffer': panel.buffer.currentData(), 'denoised_file': 'denoised_beauty' in frame.get('files', {}),
                           'buffers_kept': len(frame.get('files', {})),
                           'denoise_engine': frame.get('denoise_engine'), 'rendering': panel._rendering, 'hud': panel.hud.text() if panel.hud.isVisible() else None}
        panel.preview.grab().save(str(out / (tag + '.png')))
        save()
        panel.stop()
        QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))
        return
    if len(result['seen']) % 15 == 0:
        save()
    QtCore.QTimer.singleShot(1000, watch)


try:
    lx.eval('scene.open {%s} normal' % source)
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(int(float(os.environ.get('MOONRAY_PROBE_IMPORT', '60')) * 1000), opened)
