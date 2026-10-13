# python
"""Isolated GUI test: with Important Parts First on, a MoonRay render takes the buckets with the most in them first.

Three balls stand in a corner of the picture, away from where the spiral order begins, over a plain floor. The scene
is rendered with MoonRay at many samples, with Important Parts First off or on (MOONRAY_PROBE_IMPORTANT). The window
is pictured every two seconds as it renders, how long the render took is written down, and its finished picture is
saved, for the two to be laid side by side: the same picture, come by in another order."""
import json
import os
import pathlib
import time
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
ON = os.environ.get('MOONRAY_PROBE_IMPORTANT', '1') != '0'
tag = 'on' if ON else 'off'
out = root / 'test-results/important-first'
out.mkdir(parents=True, exist_ok=True)
result = {'important': ON, 'seen': []}
held = {'shots': 0}


def save():
    (out / (tag + '.json')).write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def begin():
    try:
        panel = panel_widget()
        runtime = root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-04-drain')
        panel.preferences.set('runtime', str(runtime))
        from moonray_modo import persistent
        result['runtime_can'] = persistent.important(runtime)
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        lx.eval('moonray.render.samples %s' % os.environ.get('MOONRAY_PROBE_SAMPLES', '8'))
        lx.eval('moonray.render.important_first %d' % (1 if ON else 0))
        result['setting'] = panel._settings_values()['render'].get('important_first')
        held['began'] = time.monotonic()
        panel.start.click()
    except Exception:
        result['error'] = traceback.format_exc()
        save()
        lx.eval('!app.quit')
        return
    QtCore.QTimer.singleShot(2000, watch)


def watch():
    panel = panel_widget()
    now = time.monotonic() - held['began']
    result['seen'].append([round(now, 1), panel.render_timing.text(), panel.status.text()[:70]])
    if panel._rendering and now < 240:
        held['shots'] += 1
        if held['shots'] <= 12:
            panel.preview.grab().save(str(out / ('%s_%02d.png' % (tag, held['shots']))))
        QtCore.QTimer.singleShot(2000, watch)
        return
    result['took'] = round(now, 1)
    result['timing'] = panel.render_timing.text()
    panel.preview.image.save(str(out / (tag + '_final.png')))
    lx.eval('moonray.render.important_first 0')
    save()
    QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))


try:
    for x, y in ((-1.6, 1.0), (-1.2, 0.75), (-1.75, 0.6)):
        lx.eval('select.typeFrom item')
        lx.eval('item.create mesh')
        lx.eval('tool.set prim.sphere on')
        lx.eval('tool.attr prim.sphere cenX %s' % x)
        lx.eval('tool.attr prim.sphere cenY %s' % y)
        for axis in 'XYZ':
            lx.eval('tool.attr prim.sphere size%s 0.2' % axis)
        lx.eval('tool.apply')
        lx.eval('tool.set prim.sphere off')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, begin)
