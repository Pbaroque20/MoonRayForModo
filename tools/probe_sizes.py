# python
"""Isolated GUI test: the size each engine renders at.

MoonRay renders at the scene's resolution, or the camera's where the camera overrides it. MoonLightIPR, a realtime
preview, renders at the preview size. Going from one to the other and back leaves each at its own."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/sizes'
out.mkdir(parents=True, exist_ok=True)
result = {'steps': []}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def note(name):
    panel = panel_widget()
    image = panel.preview.image
    result['steps'].append({'step': name, 'engine': panel.preview_engine.currentText(), 'picture': [image.width(), image.height()], 'info': panel.image_info.text(), 'status': panel.status.text()})
    save()


def choose(engine):
    panel = panel_widget()
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(engine))


STEPS = []


def step(wait):
    def register(function):
        STEPS.append((function, wait))
        return function
    return register


@step(25000)
def moonray():
    panel = panel_widget()
    panel.preferences.set('runtime', str(root / 'runtime/steady-0351-tiles'))
    result['preview_size'] = panel.preferences.get('preview_size')
    choose('moonray')
    panel.start.click()


@step(8000)
def realtime():
    note('moonray')
    choose('moonlightipr')
    panel_widget().start.click()


@step(25000)
def moonray_again():
    note('moonlightipr')
    choose('moonray')
    panel_widget().start.click()


@step(25000)
def camera_override():
    note('moonray_after_moonlightipr')
    camera = modo.Scene().renderCamera
    lx.eval('select.item {%s} set' % camera.id)
    lx.eval('item.channel resOverride true')
    lx.eval('item.channel resX 800')
    lx.eval('item.channel resY 400')
    panel_widget().start.click()


@step(8000)
def realtime_override():
    note('moonray_camera_800x400')
    choose('moonlightipr')
    panel_widget().start.click()


@step(500)
def finish():
    note('moonlightipr_camera_800x400')
    panel_widget().stop()


def run(index=0):
    if index >= len(STEPS):
        save()
        lx.eval('!app.quit')
        return
    function, wait = STEPS[index]
    try:
        function()
    except Exception:
        result.setdefault('errors', []).append([function.__name__, traceback.format_exc()])
        save()
    QtCore.QTimer.singleShot(wait, lambda: run(index + 1))


try:
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('moonray.render.samples 2')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, run)
