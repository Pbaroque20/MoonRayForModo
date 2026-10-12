# python
"""Isolated GUI test: a finished preview stays finished.

A scene (MOONRAY_PROBE_SCENE, else two balls) is previewed with the denoiser on, with each engine in turn
(MOONRAY_PROBE_ENGINES), realtime on for the engines that have it. Nothing in the scene is touched. For a minute after
the first render is asked for, every render handed to the renderer is counted, with when and why."""
import json
import os
import pathlib
import time
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/restarts'
out.mkdir(parents=True, exist_ok=True)
ENGINES = os.environ.get('MOONRAY_PROBE_ENGINES', 'moonray,moonray_ls,moonlightipr').split(',')
WATCH = int(os.environ.get('MOONRAY_PROBE_WATCH', '60'))
result = {'engines': {}}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def begin(index=0):
    try:
        panel = panel_widget()
        if index == 0:
            if not os.environ.get('MOONRAY_PROBE_OLD'):
                panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-0351-tiles')))
            submit = panel.renderer.submit

            def counted(*a, **k):
                held['run']['submits'].append([round(time.time() - held['began'], 1), ''.join(traceback.format_stack(limit=5)[:-1]).count('_live_tick') and 'following' or 'asked'])
                return submit(*a, **k)
            panel.renderer.submit = counted
            panel.renderer.finished.connect(lambda *a: held['run']['finished'].append(round(time.time() - held['began'], 1)))
        if index >= len(ENGINES):
            panel.stop()
            save()
            lx.eval('!app.quit')
            return
        # An engine may be followed by +live: the Live box of 0.3.51.3 and earlier, where there is one to be seen.
        engine, _, live = ENGINES[index].partition('+')
        if panel._rendering or panel._following:
            panel.stop()
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(engine))
        if live or os.environ.get('MOONRAY_PROBE_OLD'):
            panel.ipr_mode.setChecked(bool(live))
        engine = ENGINES[index]
        QtWidgets.QApplication.processEvents()
        held['run'] = result['engines'][engine] = {'submits': [], 'finished': [], 'button': panel.start.text()}
        held['began'] = time.time()
        panel.start.click()
    except Exception:
        result.setdefault('errors', []).append(traceback.format_exc())
        save()
        lx.eval('!app.quit')
        return
    QtCore.QTimer.singleShot(WATCH * 1000, lambda: end(index))


def end(index):
    try:
        panel = panel_widget()
        held['run'].update(status=panel.status.text()[:80], buffer=panel.buffer.currentText(), following=panel._following, rendering=panel._rendering, button_after=panel.start.text())
    except Exception:
        result.setdefault('errors', []).append(traceback.format_exc())
    save()
    begin(index + 1)


try:
    if os.environ.get('MOONRAY_PROBE_SCENE'):
        lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    else:
        for x in (-.6, .6):
            lx.eval('select.typeFrom item')
            lx.eval('item.create mesh')
            lx.eval('tool.set prim.sphere on')
            lx.eval('tool.attr prim.sphere cenX %s' % x)
            lx.eval('tool.apply')
            lx.eval('tool.set prim.sphere off')
    lx.eval('moonray.render.samples %s' % os.environ.get('MOONRAY_PROBE_SAMPLES', '4'))
    lx.eval('moonray.render.denoiser 2')
    lx.eval('moonray.render.denoise_preview 1')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, begin)
