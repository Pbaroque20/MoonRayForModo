# python
"""Isolated GUI test: a region is marked with a moving dotted outline, and is rendered only when asked for.

Two balls, MoonRay chosen, Draft on.
1. A region is drawn as a drag in the picture draws it: nothing is rendered for it, the status says how to render it,
   and its outline is dotted and moves (two pictures of it a moment apart differ along the outline).
2. Render is pressed: Draft goes off and the region is rendered, its outline still moving round it."""
import json
import os
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/region-outline'
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
    result['steps'].append({'step': name, 'draft': panel.draft.isChecked(), 'following': panel._following, 'button': panel.start.text(),
                            'rendering': panel._rendering, 'renders': held['submits'], 'region': panel.preview.region,
                            'outline_moving': panel.preview._ants_timer.isActive(), 'status': panel.status.text()[:80]})
    panel.window().grab().save(str(out / ('%02d_%s.png' % (len(result['steps']), name))))
    save()


def differ(first, second):
    """How many pixels of two pictures of the view differ."""
    a = first.convertToFormat(QtGui.QImage.Format_RGB888)
    b = second.convertToFormat(QtGui.QImage.Format_RGB888)
    return sum(1 for x, y in zip(bytes(a.constBits())[::3], bytes(b.constBits())[::3]) if x != y)


STEPS = []


def step(wait):
    def register(function):
        STEPS.append((function, wait))
        return function
    return register


@step(5000)
def draft_on():
    panel = panel_widget()
    panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-04-drain')))
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
    submit = panel.renderer.submit

    def counted(*a, **k):
        held['submits'] += 1
        return submit(*a, **k)
    panel.renderer.submit = counted
    panel.draft.click()


@step(3000)
def mark():
    note('draft_on')
    held['before'] = held['submits']
    # As a rectangle dragged in the picture with the Region button down.
    panel_widget()._region_drawn(.3, .25, .7, .75)


@step(400)
def first_look():
    result['renders_for_marking'] = held['submits'] - held['before']
    note('region_marked_on_the_draft')
    held['first'] = panel_widget().preview.grab().toImage()


@step(1500)
def second_look():
    result['outline_pixels_changed'] = differ(held['first'], panel_widget().preview.grab().toImage())
    panel_widget().start.click()


@step(40000)
def rendering():
    note('render_pressed')


@step(500)
def finish_():
    note('region_rendered')
    panel = panel_widget()
    held['first'] = panel.preview.grab().toImage()
    QtWidgets.QApplication.processEvents()
    QtCore.QThread.msleep(250)
    QtWidgets.QApplication.processEvents()
    result['outline_pixels_changed_after_render'] = differ(held['first'], panel.preview.grab().toImage())
    panel.stop()
    # The region is the scene's: put back as it was, for nothing else in the test copy to meet it.
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
    lx.eval('moonray.render.samples 3')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, lambda: run())
