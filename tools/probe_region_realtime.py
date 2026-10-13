# python
"""Isolated GUI test: the Region tool takes realtime off, so that marking a region forces no render.

Two balls, MoonLightIPR with realtime on. The Region button is pressed: realtime goes off. A region is then drawn as
a drag in the picture draws it: nothing is rendered for it. RT is pressed: the region is rendered."""
import json
import os
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/region-realtime'
out.mkdir(parents=True, exist_ok=True)
result = {'steps': []}
held = {'submits': 0}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def note(name):
    panel = panel_widget()
    result['steps'].append({'step': name, 'following': panel._following, 'button': panel.start.text(), 'renders': held['submits'],
                            'region': panel.preview.region, 'status': panel.status.text()[:80]})
    save()


STEPS = []


def step(wait):
    def register(function):
        STEPS.append((function, wait))
        return function
    return register


@step(9000)
def realtime_on():
    panel = panel_widget()
    panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-04-drain')))
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonlightipr'))
    submit = panel.renderer.submit

    def counted(*a, **k):
        held['submits'] += 1
        return submit(*a, **k)
    panel.renderer.submit = counted
    panel.start.click()


@step(3000)
def region_button():
    note('realtime_on')
    panel_widget().region_enabled.click()


@step(5000)
def draw():
    note('region_button_pressed')
    held['before'] = held['submits']
    panel_widget()._region_drawn(.3, .25, .7, .75)


@step(8000)
def press_rt():
    result['renders_for_marking'] = held['submits'] - held['before']
    note('region_drawn')
    panel_widget().start.click()


@step(500)
def finish_():
    note('rt_pressed')
    panel_widget().stop()
    lx.eval('moonray.render.region_enabled 0')


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
    for x in (-.6, .6):
        lx.eval('select.typeFrom item')
        lx.eval('item.create mesh')
        lx.eval('tool.set prim.sphere on')
        lx.eval('tool.attr prim.sphere cenX %s' % x)
        lx.eval('tool.apply')
        lx.eval('tool.set prim.sphere off')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, lambda: run())
