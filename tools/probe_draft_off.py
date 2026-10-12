# python
"""Isolated GUI test: switching Draft off never leaves the draft standing as though it were a render.

Two balls are rendered with MoonRay. Draft is switched on, then off: the render is back. Then, while a new render is
still going, Draft is switched on and off again. Last, an item is moved under Draft and Draft switched off: the old
render is of another scene and is not put back. At each step what the window shows and says is written down."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/draft-off'
out.mkdir(parents=True, exist_ok=True)
result = {'steps': []}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def look():
    """What kind of picture is up: nothing, lines (few colours, mostly one of them) or a render."""
    image = panel_widget().preview.image
    if image.isNull():
        return 'nothing'
    small = image.convertToFormat(QtGui.QImage.Format_RGB888).scaled(96, 54)
    data = bytes(small.constBits())[:96 * 54 * 3]
    greys = [data[i + 1] for i in range(0, len(data), 3)]
    commonest = max(set(greys), key=greys.count)
    return 'lines' if greys.count(commonest) > .7 * len(greys) else 'render'


def note(name):
    panel = panel_widget()
    result['steps'].append({'step': name, 'shows': look(), 'draft': panel.draft.isChecked(), 'rendering': panel._rendering,
                            'status': panel.status.text()[:90], 'info': panel.image_info.text(), 'button': panel.start.text()})
    panel.preview.grab().save(str(out / ('%02d_%s.png' % (len(result['steps']), name))))
    save()


STEPS = []


def step(wait):
    def register(function):
        STEPS.append((function, wait))
        return function
    return register


@step(45000)
def render():
    panel = panel_widget()
    panel.preferences.set('runtime', str(root / 'runtime/steady-0351-tiles'))
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
    # A mesh with something in it: the scene's first mesh is empty.
    held['item'] = [m.id for m in modo.Scene().items('mesh') if len(m.geometry.polygons)][-1]
    panel.start.click()


@step(8000)
def draft_on():
    note('rendered')
    panel_widget().draft.click()


@step(3000)
def draft_off():
    note('draft_on')
    panel_widget().draft.click()


@step(6000)
def render_again():
    note('draft_off_after_a_finished_render')
    panel = panel_widget()
    lx.eval('moonray.render.samples 60')
    panel.start.click()


@step(6000)
def draft_on_mid_render():
    note('a_render_going')
    panel_widget().draft.click()


@step(3000)
def draft_off_mid_render():
    note('draft_on_while_it_was_going')
    panel_widget().draft.click()


@step(8000)
def move_under_draft():
    note('draft_off_while_it_was_going')
    panel = panel_widget()
    if panel._rendering:
        panel.start.click()


@step(8000)
def draft_then_move():
    note('stopped')
    panel_widget().draft.click()


@step(6000)
def moved():
    lx.eval('select.item {%s} set' % held['item'])
    lx.eval('transform.channel pos.X 0.4')


@step(3000)
def draft_off_after_move():
    note('moved_under_draft')
    panel_widget().draft.click()


@step(500)
def finish():
    note('draft_off_after_the_scene_changed')
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
    lx.eval('moonray.render.denoiser 0')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, lambda: run())
