# python
"""Isolated GUI test: a material's smoothing is changed from its properties after it is assigned, and a direction of
the material is number fields.

A DwaFabricMaterial goes on a cube. Its smoothing is read as assigned, set to flat, to an angle and back to Modo's
own, and what the material holds and how many normals the cube is given are written down each time. Then the parts of
its warp thread direction are set one at a time, and back to MoonRay's own."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/material-smoothing'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def normals():
    """How many different normals the cube is given: 6 where its faces are flat, 8 where it is smoothed all over."""
    from moonray_modo import host, geometry
    taken = host.snapshot(refresh_materials=True)
    mesh = next(m for m in taken['meshes'] if m.get('faces'))
    values = geometry.prepare(mesh).get('normals')
    if not values:
        return 'none of its own'
    flat = [float(v) for n in values for v in (n if isinstance(n, (list, tuple)) else [n])]
    return len({tuple(round(v, 3) for v in flat[k:k + 3]) for k in range(0, len(flat), 3)})


def state(name):
    from moonray_modo import properties
    settings = properties.read(held['item'])
    entry = {'smoothing': settings.get('smoothing', 'absent'), 'angle': settings.get('smoothing_angle', 'absent')}
    for key, command in (('popup', 'moonray.material.smoothing ?'), ('field', 'moonray.material.smoothing_angle ?')):
        try:
            entry[key] = lx.eval(command)
        except RuntimeError as exc:
            entry[key] = 'refused: %s' % exc
    try:
        entry['normals'] = normals()
    except Exception as exc:
        entry['normals'] = 'not counted: %s' % exc
    result[name] = entry


try:
    from moonray_modo import properties, shader_library
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('moonray.library.assign %s' % properties.encode({'shader': 'DwaFabricMaterial', 'parameters': {}}))
    held['item'] = modo.Scene().selected[0]
    form = (root / 'kit/MoonRayForModo/material_forms.cfg').read_text(encoding='utf-8')
    state('as_assigned')
    lx.eval('moonray.material.smoothing 1')
    state('flat')
    lx.eval('moonray.material.smoothing 2')
    lx.eval('moonray.material.smoothing_angle 120')
    state('within_120')
    lx.eval('moonray.material.smoothing_angle 30')
    state('within_30')
    lx.eval('moonray.material.smoothing 0')
    state('as_modo_says')
    kinds = [''] + sorted(shader_library.catalog())
    i = kinds.index('DwaFabricMaterial')
    j = sorted(shader_library.catalog()['DwaFabricMaterial']['attributes']).index('warp_thread_direction')
    names = ['moonray.material.attr%d_%d_%d' % (i, j, part) for part in range(3)]
    result['in_the_form'] = [name + ' ?' in form for name in names]
    result['typed_row_gone'] = ('moonray.material.attr%d_%d ?' % (i, j)) not in form

    def direction():
        return [[lx.eval(name + ' ?') for name in names], properties.read(held['item']).get('native_parameters', {}).get('warp_thread_direction', 'absent')]
    result['direction_first'] = direction()
    lx.eval(names[0] + ' 0.25')
    lx.eval(names[2] + ' 0.5')
    result['direction_set'] = direction()
    graph = properties.read(held['item']).get('node_graph')
    if graph:
        result['graph_holds'] = graph['nodes'][graph['root']].get('parameters', {}).get('warp_thread_direction', 'absent')
    lx.eval(names[0] + ' 1.0')
    lx.eval(names[2] + ' 0.0')
    result['direction_back'] = direction()
    lx.eval(names[1] + ' 0.0')
    modo.Scene().select(held['item'])
except Exception:
    result['error'] = traceback.format_exc()
save()


def picture():
    try:
        window = max((w for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible()), key=lambda w: w.width() * w.height())
        window.grab().save(str(out / 'modo.png'))
    except Exception:
        result['picture_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))


QtCore.QTimer.singleShot(4000, picture)
