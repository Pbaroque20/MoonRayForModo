# python
"""Isolated GUI test: Draft and realtime are one or the other, and choosing an engine switches realtime on for neither.

Two balls, Draft on with MoonRay chosen.
1. A realtime engine is chosen at once, while the draft's lines are still being drawn, and then the other: realtime
   stays off and Draft on each time.
2. RT is pressed: realtime is on and Draft off.
3. Draft is pressed with realtime on: Draft is on and realtime off.
4. With Draft on and a region set, MoonRay LS is chosen: realtime stays off, and the region is rendered among the lines."""
import json
import os
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/draft-realtime'
out.mkdir(parents=True, exist_ok=True)
result = {'steps': []}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def note(name):
    panel = panel_widget()
    result['steps'].append({'step': name, 'engine': panel.preview_engine.currentText(), 'draft': panel.draft.isChecked(), 'following': panel._following,
                            'button': panel.start.text(), 'rendering': panel._rendering, 'status': panel.status.text()[:70]})
    panel.window().grab().save(str(out / ('%02d_%s.png' % (len(result['steps']), name))))
    save()


STEPS = []


def step(wait):
    def register(function):
        STEPS.append((function, wait))
        return function
    return register


def choose(engine):
    panel = panel_widget()
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(engine))
    QtWidgets.QApplication.processEvents()


@step(300)
def draft_on():
    panel = panel_widget()
    panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-04-drain')))
    choose('moonray')
    panel.draft.click()


@step(4000)
def ls_at_once():
    # While the lines are still being drawn.
    choose('moonray_ls')
    result['just_after_choosing_ls'] = {'following': panel_widget()._following, 'draft': panel_widget().draft.isChecked(), 'button': panel_widget().start.text()}


@step(300)
def ipr_at_once():
    note('moonray_ls_chosen_with_draft_on')
    choose('moonray')
    panel_widget().draft.click()
    panel_widget().draft.click()
    choose('moonlightipr')


@step(4000)
def press_rt():
    note('moonlightipr_chosen_with_draft_on')
    panel_widget().start.click()


@step(4000)
def press_draft():
    note('rt_pressed')
    panel_widget().draft.click()


@step(4000)
def region_and_ls():
    note('draft_pressed_with_rt_on')
    lx.eval('moonray.render.region_enabled 1')
    for key, value in (('region_left', 30), ('region_top', 25), ('region_right', 70), ('region_bottom', 75)):
        try:
            lx.eval('moonray.render.%s %s' % (key, value))
        except Exception:
            result.setdefault('region_errors', []).append(key)
    choose('moonray_ls')


@step(25000)
def wait_region():
    note('draft_region_ls_chosen')


@step(500)
def finish_():
    note('draft_region_ls_settled')
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
    for x in (-.6, .6):
        lx.eval('select.typeFrom item')
        lx.eval('item.create mesh')
        lx.eval('tool.set prim.sphere on')
        lx.eval('tool.attr prim.sphere cenX %s' % x)
        lx.eval('tool.apply')
        lx.eval('tool.set prim.sphere off')
    lx.eval('moonray.render.samples 3')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, lambda: run())
