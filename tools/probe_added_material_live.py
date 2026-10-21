# python
"""Isolated GUI test: the hang an artist met in MoonLightIPR (2026-10-21). A scene (MOONRAY_PROBE_SCENE) is followed
in realtime; realtime goes off, a sphere is added, realtime on again; off, the sphere is given a MoonRay material,
realtime on, and the material's colour is changed as a colour picker changes it. Written down: each reading and
update the preview makes, how long it took and why it was made, and every time Modo's main thread was held up for
more than half a second. Written to test-results/added-material-live."""
import json
import os
import pathlib
import time
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/added-material-live'
out.mkdir(parents=True, exist_ok=True)
result = {'calls': [], 'stalls': [], 'phases': []}
held = {'last': time.time(), 'began': time.time()}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def at():
    return round(time.time() - held['began'], 2)


def heartbeat():
    now = time.time()
    if now - held['last'] > 0.5:
        result['stalls'].append({'at': at(), 'held_up': round(now - held['last'], 2), 'phase': held.get('phase')})
        save()
    held['last'] = now


def watch(panel, name):
    original = getattr(panel, name)

    def timed(*a, **k):
        began = time.time()
        try:
            return original(*a, **k)
        finally:
            result['calls'].append({'call': name, 'at': at(), 'seconds': round(time.time() - began, 2), 'phase': held.get('phase'),
                                    'args': repr(a)[:80], 'from': [f'{f.name}:{f.lineno}' for f in traceback.extract_stack()[-5:-1]]})
    setattr(panel, name, timed)


def phase(name):
    held['phase'] = name
    result['phases'].append((at(), name))
    save()


def realtime(on):
    panel = held['panel']
    if on:
        panel.ipr_mode.setChecked(True)
        if not (panel._rendering or panel._following):
            panel.start.click()
    else:
        panel.ipr_mode.setChecked(False)
        panel.stop()


def plan():
    steps = [
        (0, lambda: (phase('realtime on'), realtime(True))),
        (30, lambda: (phase('realtime off'), realtime(False))),
        (33, lambda: (phase('sphere added'), add_sphere())),
        (36, lambda: (phase('realtime on with sphere'), realtime(True))),
        (66, lambda: (phase('realtime off again'), realtime(False))),
        (69, lambda: (phase('material assigned'), assign())),
        (72, lambda: (phase('realtime on with material'), realtime(True))),
        (102, lambda: (phase('colour dragged'), drag(0))),
        (190, lambda: (phase('done'), finish())),
    ]
    for seconds, step in steps:
        QtCore.QTimer.singleShot(int(seconds * 1000), lambda step=step: guarded(step))


def guarded(step):
    try:
        step()
    except Exception:
        result.setdefault('errors', []).append((held.get('phase'), traceback.format_exc()))
    save()


def add_sphere():
    lx.eval('layer.new')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.doApply')
    lx.eval('tool.set prim.sphere off')
    held['sphere'] = modo.Scene().selected[-1]
    result['sphere'] = held['sphere'].name


def assign():
    lx.eval('select.item {%s} set' % held['sphere'].id)
    lx.eval('@{%s}' % (root / 'tools/probe_assign_material_step.py'))


def drag(n):
    # As Modo's colour picker sends a dragged colour: a change every 30 ms, the last sent twice.
    if n < 16:
        lx.eval('moonray.material.attr2_0 {%f 0.3 0.2}' % (0.6 + n * 0.0125))
        QtCore.QTimer.singleShot(30, lambda: guarded(lambda: drag(n + 1)))
    else:
        lx.eval('moonray.material.attr2_0 {0.8 0.3 0.2}')
        phase('colour let go')


def finish():
    try:
        held['panel'].preview.grab().save(str(out / 'last.png'))
        result['status'] = held['panel'].status.text()
        result['notices'] = [w for w in getattr(held['panel'], '_notices', [])][:10] if isinstance(getattr(held['panel'], '_notices', None), list) else None
        held['panel'].stop()
    except Exception:
        result['finish_error'] = traceback.format_exc()
    save()
    faulthandler.cancel_dump_traceback_later()
    QtCore.QTimer.singleShot(1000, lambda: lx.eval('!app.quit'))


def begin():
    try:
        from moonray_modo.panel import Panel
        panel = held['panel'] = next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))
        panel.preferences.set('runtime', 'C:/Users/Raphael Tobar/AppData/Roaming/Luxology/Kits/MoonRayForModo/runtime')
        panel.preferences.set('preview_motion', True)
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonlightipr'))
        QtWidgets.QApplication.processEvents()
        for name in ('_capture', '_capture_preview', '_live_tick'):
            if hasattr(panel, name):
                watch(panel, name)
        submit = panel.renderer.submit

        def submitted(*a, **k):
            began = time.time()
            try:
                return submit(*a, **k)
            finally:
                result['calls'].append({'call': 'submit', 'at': at(), 'seconds': round(time.time() - began, 2), 'phase': held.get('phase')})
        panel.renderer.submit = submitted
        result['surface'] = panel._settings_values().get('surface')
        timer = held['heartbeat'] = QtCore.QTimer()
        timer.timeout.connect(heartbeat)
        timer.start(100)
        held['began'] = held['last'] = time.time()
        plan()
    except Exception:
        result['error'] = traceback.format_exc()
    save()


# Where every thread stands, written down every ten seconds, which shows where a held up main thread is held.
import faulthandler
held['stacks'] = (out / 'stacks.txt').open('w')
faulthandler.dump_traceback_later(10, repeat=True, file=held['stacks'])

try:
    lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
except Exception:
    result['open_error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, begin)
