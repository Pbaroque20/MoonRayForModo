# python
"""Isolated GUI test: MoonLightIPR rests on the graphics card when realtime is switched off.

A ball, MoonLightIPR at 1024 samples a pixel, realtime switched on and the render begun. Part way, the graphics card's
load is sampled (nvidia-smi) and realtime is switched off in the window's options, as the IPR toggle does. The card's
load is sampled again over the seconds after, with whether the window is still rendering and whether the picture is
kept. The preferences of the test Modo are put back."""
import json
import pathlib
import subprocess
import time
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/rt-rest'
out.mkdir(parents=True, exist_ok=True)
runtime = pathlib.Path.home() / 'AppData/Roaming/Luxology/Kits/MoonRayForModo/runtime'
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def load(count=6):
    """The graphics card's load in percent, sampled a few times a little apart."""
    found = []
    for _ in range(count):
        done = subprocess.run(['nvidia-smi', '--query-gpu=utilization.gpu', '--format=csv,noheader,nounits'], stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            found.append(int(done.stdout.decode().strip().splitlines()[0]))
        except (ValueError, IndexError):
            pass
        time.sleep(0.25)
    return found


def start():
    panel = panel_widget()
    held['before'] = {key: panel.preferences.store.value(key) for key in ('runtime', 'moonlightipr/samples', 'ipr')}
    panel.preferences.set('runtime', str(runtime))
    panel.preferences.set('moonlightipr/samples', 1024)
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonlightipr'))
    panel.ipr_mode.setChecked(True)
    panel.start.click()


def during():
    """Waits for the first picture of the pass, which says MoonLightIPR is sampling, then notes the card's load and
    switches realtime off at once, while the pass is still under way."""
    panel = panel_widget()
    held['tries'] = held.get('tries', 0) + 1
    if not (panel._rendering and not panel.preview.image.isNull()) and held['tries'] < 400:
        QtCore.QTimer.singleShot(50, during)
        return
    result['during'] = {'rendering': panel._rendering, 'following': panel._following, 'load': load(2), 'waited_ms': held['tries'] * 50}
    switch_off()
    QtCore.QTimer.singleShot(3000, finish)


def finish():
    try:
        after()
    except Exception:
        result.setdefault('errors', []).append(traceback.format_exc())
    save()
    lx.eval('!app.quit')


def switch_off():
    panel = panel_widget()
    panel.ipr_mode.setChecked(False)
    QtWidgets.QApplication.processEvents()
    result['switched_off'] = {'status': panel.status.text()}


def after():
    panel = panel_widget()
    session = panel.renderer.moonlightipr
    result['after'] = {'rendering': panel._rendering, 'following': panel._following, 'picture': not panel.preview.image.isNull(),
                       'session_running': session.running(), 'session_current': session.current, 'load': load(10),
                       'status': panel.status.text()}
    for key, value in held['before'].items():
        if value is None:
            panel.preferences.store.remove(key)
        else:
            panel.preferences.store.setValue(key, value)


def run(steps, index=0):
    if index >= len(steps):
        save()
        lx.eval('!app.quit')
        return
    function, wait = steps[index]
    try:
        function()
    except Exception:
        result.setdefault('errors', []).append(traceback.format_exc())
    save()
    QtCore.QTimer.singleShot(wait, lambda: run(steps, index + 1))


try:
    # A scene heavy enough that a pass of 1024 samples is still under way when realtime goes off: the one in
    # MOONRAY_PROBE_SCENE, else a ball.
    import os
    scene = os.environ.get('MOONRAY_PROBE_SCENE', '')
    if scene:
        lx.eval('scene.open {%s} normal' % scene)
    else:
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
        start()
    except Exception:
        result.setdefault('errors', []).append(traceback.format_exc())
    QtCore.QTimer.singleShot(400, during)


QtCore.QTimer.singleShot(15000, begin)
