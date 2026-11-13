# python
"""GUI: a scene in MoonLightIPR as a user meets it. PROBE_SCENE is opened, the preview opened on MoonLightIPR, a Render
pressed and, once it is done, realtime switched on for a while. The status line is written down every half second, with
the session's state; a session that fails says so there. Writes test-results/moonlightipr-scene-gui/report.json and the
last picture."""
import json
import os
import pathlib
import time
import traceback
import lx
from PySide2 import QtCore

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\moonlightipr-scene-gui'))
out.mkdir(parents=True, exist_ok=True)
report = {'statuses': []}
state = {}


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))


def panel():
    from moonray_modo.panel import live_panels
    return live_panels()[0]


def later(fn, wait):
    def run():
        try:
            fn()
        except Exception:
            report.setdefault('errors', []).append(traceback.format_exc())
            finish()
    QtCore.QTimer.singleShot(wait, run)


def note(stage):
    p = panel()
    text = p.status.text()
    if not report['statuses'] or report['statuses'][-1][2] != text:
        report['statuses'].append([round(time.monotonic() - state['t0'], 1), stage, text])
    save()


def begin():
    state['t0'] = time.monotonic()
    p = panel()
    p.preview_engine.setCurrentIndex(p.preview_engine.findData('moonlightipr'))
    if p.ipr_mode.isChecked():
        p.ipr_mode.setChecked(False)
    state['began'] = time.monotonic()
    p.start.click()
    later(watch_render, 500)


def watch_render():
    note('render')
    p = panel()
    if getattr(p, '_rendering', False) and time.monotonic() - state['began'] < 120:
        later(watch_render, 500)
        return
    p.preview.image.save(str(out / 'render.png'))
    state['began'] = time.monotonic()
    p.rt.click()
    later(watch_realtime, 500)


def watch_realtime():
    note('realtime')
    if time.monotonic() - state['began'] < 25:
        later(watch_realtime, 500)
        return
    panel().preview.image.save(str(out / 'realtime.png'))
    finish()


def finish():
    save()
    QtCore.QTimer.singleShot(2000, lambda: lx.eval('!app.quit'))


try:
    lx.eval('!scene.open {%s} normal' % os.environ['PROBE_SCENE'])
    lx.eval('moonray.open')
except Exception:
    report['error'] = traceback.format_exc()
save()
later(begin, 8000)
