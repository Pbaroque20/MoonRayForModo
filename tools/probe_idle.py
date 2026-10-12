# python
"""Isolated GUI test: what the preview costs while nothing changes.

A small scene is previewed with each engine in turn and then left alone. The times at which each stretch of idleness
begins and ends are written to marks.json, so that a sampler outside Modo (tools/sample_idle.ps1) can say how much
processor and graphics card each process used in it: MoonRay with realtime off after a finished render, MoonRay LS
with realtime on, MoonLightIPR with realtime on, and MoonLightIPR with realtime off."""
import json
import os
import pathlib
import time
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/idle'
out.mkdir(parents=True, exist_ok=True)
marks = {'stretches': []}
held = {}
SETTLE, IDLE = 45000, 20000


def save():
    (out / 'marks.json').write_text(json.dumps(marks, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def choose(engine):
    panel = panel_widget()
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(engine))


try:
    for x in (-.7, .7):
        lx.eval('select.typeFrom item')
        lx.eval('item.create mesh')
        lx.eval('tool.set prim.sphere on')
        lx.eval('tool.attr prim.sphere cenX %s' % x)
        lx.eval('tool.apply')
        lx.eval('tool.set prim.sphere off')
    lx.eval('moonray.open')
except Exception:
    marks['error'] = traceback.format_exc()
save()

STEPS = []


def step(wait):
    def register(function):
        STEPS.append((function, wait))
        return function
    return register


def begin(name):
    panel = panel_widget()
    held['stretch'] = {'name': name, 'begin': time.time(), 'button': panel.start.text(), 'status': panel.status.text(), 'rendering': panel._rendering, 'following': panel._following}


def end():
    panel = panel_widget()
    stretch = held.pop('stretch')
    stretch.update(end=time.time(), rendering_at_end=panel._rendering, timing=panel.render_timing.text())
    marks['stretches'].append(stretch)
    save()


@step(SETTLE)
def start():
    panel = panel_widget()
    held['stored'] = [panel.preferences.store.value(key, None) for key in ('runtime', 'preview_engine', 'ipr')]
    panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-0350-pool')))
    choose('moonray')
    panel.start.click()


@step(IDLE)
def moonray_done():
    begin('MoonRay, render finished')


@step(SETTLE)
def low_sample():
    end()
    choose('moonray_ls')


@step(IDLE)
def low_sample_idle():
    begin('MoonRay LS, realtime on, nothing changing')


@step(SETTLE)
def moonlightipr():
    end()
    choose('moonlightipr')


@step(IDLE)
def moonlightipr_idle():
    begin('MoonLightIPR, realtime on, nothing changing')


@step(4000)
def moonlightipr_off():
    end()
    panel_widget().start.click()


@step(IDLE)
def moonlightipr_off_idle():
    begin('MoonLightIPR, realtime off')


@step(500)
def finish():
    end()
    panel = panel_widget()
    if panel._rendering or panel._following:
        panel.stop()
    for key, value in zip(('runtime', 'preview_engine', 'ipr'), held['stored']):
        if value is None:
            panel.preferences.store.remove(key)
        else:
            panel.preferences.store.setValue(key, value)


def run(index=0):
    if index >= len(STEPS):
        save()
        lx.eval('!app.quit')
        return
    function, wait = STEPS[index]
    try:
        function()
    except Exception:
        marks.setdefault('errors', []).append([function.__name__, traceback.format_exc()])
        save()
    QtCore.QTimer.singleShot(wait, lambda: run(index + 1))


QtCore.QTimer.singleShot(8000, run)
