# python
"""Isolated GUI test: what Modo hides is hidden in MoonLightIPR as it is in MoonRay.

Four cubes stand in a row: one plain, one with its eye off (Visible: No), one with Render: No, and one whose eye is off
but which is told to render (Render: Yes). The scene is previewed with MoonRay and then with MoonLightIPR, with the
evaluated surface path and without, and each picture is saved with a note of which meshes the scene handed over."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/visibility'
out.mkdir(parents=True, exist_ok=True)
result = {'steps': []}
held = {}
CUBES = [('plain', None, None), ('eye_off', 'off', None), ('render_off', None, 'off'), ('eye_off_render_on', 'off', 'on')]


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def columns(image):
    """How much of each quarter of the picture's width is not background: where a cube stands, a good deal."""
    w, h = image.width(), image.height()
    if not w:
        return None
    corner = image.pixelColor(2, 2)
    counts = [0, 0, 0, 0]
    for y in range(h // 4, 3 * h // 4, 4):
        for x in range(0, w, 4):
            c = image.pixelColor(x, y)
            if abs(c.red() - corner.red()) + abs(c.green() - corner.green()) + abs(c.blue() - corner.blue()) > 24:
                counts[min(3, x * 4 // w)] += 1
    return counts


def note(name):
    panel = panel_widget()
    image = panel.preview.image
    scene = getattr(panel, '_ipr_refine_scene', None) or {}
    result['steps'].append({'step': name, 'status': panel.status.text(), 'engine': panel.preview_engine.currentData(), 'columns': columns(image),
                            'meshes': sorted(str(m.get('name')) for m in scene.get('meshes', [])),
                            'bounds': [[str(m.get('name')), [round(min(v[i] for v in m['vertices']), 2) for i in range(3)], [round(max(v[i] for v in m['vertices']), 2) for i in range(3)],
                                        [round(v, 2) for v in (m.get('matrix') or [])[12:15]]] for m in scene.get('meshes', []) if m.get('vertices')],
                            'camera': [round(v, 2) for v in (scene.get('camera', {}).get('matrix') or [])[12:15]],
                            'visibility': sorted({str(m.get('visibility')) for m in scene.get('meshes', [])})})
    image.save(str(out / (name + '.png')))
    save()


try:
    scene = modo.Scene()
    for index, (name, visible, render) in enumerate(CUBES):
        lx.eval('select.typeFrom item')
        lx.eval('item.create mesh')
        lx.eval('item.name {%s} mesh' % name)
        lx.eval('tool.set prim.cube on')
        lx.eval('tool.attr prim.cube cenX %s' % (-1.2 + 0.8 * index))
        lx.eval('tool.attr prim.cube sizeX 0.6')
        lx.eval('tool.attr prim.cube sizeY 0.6')
        lx.eval('tool.attr prim.cube sizeZ 0.6')
        lx.eval('tool.apply')
        lx.eval('tool.set prim.cube off')
        if visible:
            lx.eval('item.channel visible %s' % visible)
        if render:
            lx.eval('item.channel render %s' % render)
    result['items'] = [[m.name, m.channel('visible').get(), m.channel('render').get()] for m in scene.items('mesh')]
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


def render(engine):
    panel = panel_widget()
    if panel.start.text() == 'Stop':
        panel.start.click()
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(engine))
    QtWidgets.QApplication.processEvents()
    panel.start.click()


@step(45000)
def start():
    panel = panel_widget()
    held['stored'] = panel.preferences.store.value('runtime', '')
    held['engine'] = panel.preview_engine.currentData()
    held['live'] = panel.ipr_mode.isChecked()
    panel.preferences.set('runtime', str(root / 'runtime/steady-0350-pool'))
    panel.ipr_mode.setChecked(False)
    result['surface'] = panel._settings_values().get('surface')
    render('moonray')


@step(15000)
def moonlightipr():
    note('moonray')
    render('moonlightipr')


@step(4000)
def other_surface():
    note('moonlightipr')
    # The other way of reading surfaces: as Modo evaluates them, or straight from the meshes.
    lx.eval('moonray.render.surface %d' % (0 if result.get('surface') == 2 else 2))
    result['surface_then'] = panel_widget()._settings_values().get('surface')


@step(45000)
def moonray_again():
    render('moonray')


@step(15000)
def moonlightipr_again():
    note('moonray_other_surface')
    render('moonlightipr')


@step(1000)
def finish():
    note('moonlightipr_other_surface')
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


QtCore.QTimer.singleShot(6000, run)
