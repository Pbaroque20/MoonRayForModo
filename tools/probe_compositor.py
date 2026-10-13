# python
"""Isolated GUI test: the compositor's Composite buffer after a MoonRay render.

Two balls are rendered with MoonRay and a denoiser. With no graph the buffer list has no Composite. A graph is then
stored with the scene (the beauty graded two stops up): Composite comes into the list, is made without rendering, and
chosen shows a brighter picture than the beauty. The graph is changed (to the denoised beauty with a glow) and the
composite is made again. Last the graph is emptied and Composite leaves the list."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/compositor'
out.mkdir(parents=True, exist_ok=True)
result = {'steps': []}
held = {'submits': 0}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def mean():
    image = panel_widget().preview.image
    if image.isNull():
        return None
    small = image.convertToFormat(QtGui.QImage.Format_RGB888).scaled(64, 36)
    data = bytes(small.constBits())[:64 * 36 * 3]
    return round(sum(data) / len(data), 1)


def note(name):
    panel = panel_widget()
    frame = panel.renderer.buffers.frame or {}
    listed = [panel.buffer.itemData(i) for i in range(panel.buffer.count())]
    result['steps'].append({'step': name, 'composite_listed': 'composite' in listed, 'buffer': panel.buffer.currentData(), 'brightness': mean(),
                            'composite_file': 'composite' in frame.get('files', {}), 'renders': held['submits'], 'rendering': panel._rendering,
                            'status': panel.status.text()[:70], 'notices': [str(n)[:70] for n in getattr(panel, '_notices', [])][-3:]})
    panel.preview.grab().save(str(out / ('%02d_%s.png' % (len(result['steps']), name))))
    save()


STEPS = []


def step(wait):
    def register(function):
        STEPS.append((function, wait))
        return function
    return register


def graph(*nodes):
    built = {identity: {'type': kind, 'parameters': values, 'inputs': inputs, 'position': [200 * index, 0]} for index, (identity, kind, values, inputs) in enumerate(nodes)}
    built['out'] = {'type': 'output', 'parameters': {}, 'inputs': {'image': nodes[-1][0]}, 'position': [200 * len(nodes), 0]}
    return {'nodes': built, 'root': 'out'}


@step(70000)
def render():
    panel = panel_widget()
    panel.preferences.set('runtime', str(root / __import__('os').environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-0351-tiles')))
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
    submit = panel.renderer.submit

    def counted(*a, **k):
        held['submits'] += 1
        return submit(*a, **k)
    panel.renderer.submit = counted
    panel.start.click()


@step(6000)
def store_grade():
    note('rendered_no_graph')
    panel = panel_widget()
    panel.buffer.setCurrentIndex(panel.buffer.findData('beauty'))
    held['beauty'] = None
    result['stored'] = panel._store(compositor=graph(('a', 'input', {'buffer': 'beauty'}, {}), ('g', 'grade', {'exposure': 2.0}, {'image': 'a'})))


@step(4000)
def choose_composite():
    note('graph_stored_beauty_shown')
    panel = panel_widget()
    index = panel.buffer.findData('composite')
    result['composite_index'] = index
    if index >= 0:
        panel.buffer.setCurrentIndex(index)
        panel._buffer_picked = 'composite'


@step(8000)
def store_glow():
    note('composite_two_stops_up')
    panel_widget()._store(compositor=graph(('a', 'input', {'buffer': 'denoised_beauty'}, {}), ('g', 'glow', {'threshold': .2, 'radius': 20.0, 'strength': 1.0}, {'image': 'a'}),
                                           ('d', 'grade', {'saturation': 0.0, 'tint': [1.0, .6, .3]}, {'image': 'g'})))


@step(6000)
def empty():
    note('composite_glow_of_the_denoised')
    panel_widget()._store(compositor={})


@step(500)
def finish():
    note('graph_emptied')
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
    lx.eval('moonray.render.denoiser 2')
    lx.eval('moonray.render.denoise_preview 1')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, lambda: run())
