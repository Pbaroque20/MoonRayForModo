# python
"""Isolated GUI test: the Composite buffer is always in the buffer list.

Two balls, rendered with MoonRay at a small size. The Composite is in the list although the scene's compositor has no
graph. Chosen, the status says where to make one, and the picture stays as it was. A graph that grades the beauty is
then stored: the Composite is shown."""
import json
import os
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/composite-listed'
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
    listed = [panel.buffer.itemText(i) for i in range(panel.buffer.count())]
    result['steps'].append({'step': name, 'listed': listed, 'buffer': panel.buffer.currentData(), 'rendering': panel._rendering,
                            'composite_file': 'composite' in frame.get('files', {}), 'status': panel.status.text()})
    panel.window().grab().save(str(out / ('%02d_%s.png' % (len(result['steps']), name))))
    save()


STEPS = []


def step(wait):
    def register(function):
        STEPS.append((function, wait))
        return function
    return register


@step(60000)
def render():
    panel = panel_widget()
    panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-04-drain')))
    note('opened')
    panel.render_once()


@step(4000)
def choose():
    note('rendered')
    panel = panel_widget()
    panel.buffer.setCurrentIndex(panel.buffer.findData('composite'))


@step(15000)
def grade():
    note('composite_chosen_without_a_graph')
    from moonray_modo import compositor
    graph = compositor.new()
    graph['nodes']['grade'] = {'type': 'grade', 'parameters': {'exposure': 1.5}, 'inputs': {'image': 'beauty'}, 'position': [130, 0]}
    graph['nodes']['out']['inputs']['image'] = 'grade'
    result['stored'] = panel_widget()._store(compositor=compositor.validate(graph))


@step(500)
def finish_():
    note('graph_stored')


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
