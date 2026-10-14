# python
"""Isolated GUI test: MoonRay LS offers and renders the beauty alone.

Two balls. With MoonRay chosen the buffer list is as long as it is; with MoonRay LS it holds Beauty only. An LS render
is made: the picture comes, and the render kept holds no buffer but the beauty. Back on MoonRay the list is whole."""
import json
import os
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/ls-beauty-only'
out.mkdir(parents=True, exist_ok=True)
result = {'steps': []}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def note(name):
    panel = panel_widget()
    frame = panel.renderer.buffers.frame or {}
    shown = [panel.buffer.itemText(i) for i in range(panel.buffer.count()) if not panel.buffer.view().isRowHidden(i)]
    result['steps'].append({'step': name, 'engine': panel.preview_engine.currentData(), 'listed': shown, 'buffer': panel.buffer.currentData(),
                            'kept': sorted(frame.get('files', {})), 'picture': not panel.preview.image.isNull(), 'rendering': panel._rendering,
                            'status': panel.status.text()[:90]})
    panel.window().grab().save(str(out / ('%d_%s.png' % (len(result['steps']), name))))
    save()


STEPS = []


def step(wait):
    def register(function):
        STEPS.append((function, wait))
        return function
    return register


@step(1500)
def low():
    panel = panel_widget()
    panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-04-drain')))
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
    note('moonray_chosen')
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray_ls'))


@step(30000)
def render():
    note('ls_chosen')
    panel_widget().start.click()


@step(1500)
def back():
    note('ls_rendered')
    panel = panel_widget()
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))


@step(500)
def finish_():
    note('moonray_again')


def run(index=0):
    if index >= len(STEPS):
        save()
        lx.eval('!!app.quit')
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
