# python
"""Isolated GUI test: Draft, with the engine changed while it is on, and rendering afterwards.

With Live off: a render, Draft on, the engine changed, Render pressed, Draft off, Render pressed. After each step the
window is pictured and what it holds written down."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/draft-first'
out.mkdir(parents=True, exist_ok=True)
result = {'steps': []}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def note(name):
    panel = panel_widget()
    image = panel.preview.image
    corner = QtGui.QColor(image.pixel(2, 2)) if not image.isNull() else None
    result['steps'].append({'step': name, 'status': panel.status.text(), 'info': panel.image_info.text(), 'button': panel.start.text(), 'draft': panel.draft.isChecked(),
                            'engine': panel.preview_engine.currentData(), 'size': [image.width(), image.height()], 'format': int(image.format()),
                            'corner': [corner.red(), corner.green(), corner.blue(), corner.alpha()] if corner else None, 'paper': bool(panel.preview.paper),
                            'held': panel._held, 'rendering': panel._rendering})
    panel.window().grab().save(str(out / ('%02d_%s.png' % (len(result['steps']), name))))
    save()


try:
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()

STEPS = []


def step(wait):
    def register(function):
        STEPS.append((function, wait))
        return function
    return register


@step(3000)
def start():
    panel = panel_widget()
    held['stored'] = panel.preferences.store.value('runtime', '')
    held['engine'] = panel.preview_engine.currentData()
    held['live'] = panel.ipr_mode.isChecked()
    panel.preferences.set('runtime', str(root / 'runtime/steady-0350-pool'))
    panel.ipr_mode.setChecked(False)
    if panel.start.text() == 'Stop':
        panel.start.click()
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonlightipr'))
    QtWidgets.QApplication.processEvents()


@step(8000)
def draft_on():
    note('nothing_rendered')
    panel_widget().draft.click()


@step(8000)
def engine_to_moonray():
    note('draft_on')
    panel = panel_widget()
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))


@step(4000)
def draft_off():
    note('engine_changed_to_moonray')
    panel_widget().draft.click()


@step(6000)
def engine_back():
    note('draft_off')
    panel = panel_widget()
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonlightipr'))


@step(12000)
def render_plain():
    note('engine_changed_back')
    panel_widget().start.click()


@step(1000)
def finish():
    note('rendered_after_draft')
    panel = panel_widget()
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(held['engine']))
    panel.preferences.store.setValue('runtime', held['stored'])
    panel.ipr_mode.setChecked(held['live'])


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


QtCore.QTimer.singleShot(5000, run)
