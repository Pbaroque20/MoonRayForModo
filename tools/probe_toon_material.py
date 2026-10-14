# python
"""Isolated GUI test: MoonRay's toon material, added from the Shader Tree's Add Layer list, in a MoonRay render.

A ball with a DwaToonMaterial layer is rendered as the material comes, and again with its diffuse model set to ramp
and its specular model to Toon. What the plugin reads of the material, the notices and each picture are kept."""
import json
import os
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/toon'
out.mkdir(parents=True, exist_ok=True)
result = {'steps': []}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def note(name):
    from moonray_modo import host, properties
    panel = panel_widget()
    snapshot = host.snapshot()
    material = snapshot['materials'].get('toon', {})
    result['steps'].append({'step': name, 'stored': properties.read(held['item']),
                            'read': {key: material.get(key) for key in ('name', 'native_shader', 'native_parameters')},
                            'warnings': [w for w in snapshot.get('warnings', []) if 'renderOutput' not in w],
                            'rendering': panel._rendering, 'status': panel.status.text()[:120],
                            'error': getattr(panel, '_failure', None) and str(panel._failure)[:300]})
    panel.preview.grab().save(str(out / ('modo_%s.png' % name)))
    save()


STEPS = []


def step(wait):
    def register(function):
        STEPS.append((function, wait))
        return function
    return register


@step(45000)
def begin():
    panel = panel_widget()
    panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-04-drain')))
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
    panel.start.click()


@step(45000)
def toon_on():
    note('as_added')
    # As choosing them in the material's form: diffuse model ramp, specular model Toon.
    lx.eval('!select.drop item')
    lx.eval('!select.subItem {%s} set textureLayer' % held['item'].id)
    from moonray_modo import material_override, properties
    result['selected'] = [(i.name, i.type, properties.is_material(i)) for i in modo.Scene().selected]
    read = properties.read(held['item'])
    result['override'] = [material_override.enabled(read), material_override.effective(read).get('native_shader')]
    save()
    lx.eval('!moonray.material.attr13_17 1')
    lx.eval('!moonray.material.attr13_102 2')
    panel_widget().start.click()


@step(500)
def finish_():
    note('toon_switched_on')


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
    from moonray_modo import materials, properties
    lx.eval('select.typeFrom item')
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    scene = modo.Scene()
    mesh = scene.selected[0]
    with mesh.geometry as g:
        for index in range(len(g.polygons)):
            g.polygons[index].materialTag = 'toon'
    mask = scene.addItem('mask', name='Toon mask')
    mask.setParent(scene.renderItem, materials.above_base(scene, mask))
    mask.channel('ptyp').set('Material')
    mask.channel('ptag').set('toon')
    held['item'] = scene.addItem(properties.LAYER_PREFIX + 'DwaToonMaterial', name='DwaToonMaterial')
    held['item'].setParent(mask, 0)
    lx.eval('moonray.render.samples 3')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, lambda: run())
