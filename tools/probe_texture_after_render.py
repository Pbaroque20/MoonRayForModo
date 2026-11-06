# python
"""Isolated GUI test, the artist's order of 2026-10-30: a sphere with a Dwa material is rendered in the preview window
(MoonRay, standard XPU), an image is then wired into the material's albedo in its graph, and the scene rendered again.
Records how much each picture varies (a texture that does not reach the render leaves the sphere one colour).
Writes test-results/texture-after-render/report.json and the window's pictures."""
import json
import os
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
RENDERER = os.environ.get('MOONRAY_PROBE_RENDERER', 'xpu')    # xpu: MoonRay XPU; xpu2: XPU2
REALTIME = os.environ.get('MOONRAY_PROBE_RT') == '1'
out = root / 'test-results/texture-after-render' / (RENDERER + ('-rt' if REALTIME else '') + os.environ.get('MOONRAY_PROBE_TAG', ''))
out.mkdir(parents=True, exist_ok=True)
image = os.environ.get('MOONRAY_PROBE_IMAGE') or str(root / 'downloads/moonray-example-scenes/scenes/bedroom/scene.png')
result = {'steps': []}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def spread(picture):
    """How much the middle of the picture varies, in hue and lightness."""
    if picture.isNull():
        return None
    w, h = picture.width(), picture.height()
    values, hues = [], []
    for y in range(h // 4, 3 * h // 4, 3):
        for x in range(w // 4, 3 * w // 4, 3):
            c = QtGui.QColor(picture.pixel(x, y))
            values.append(c.lightness()); hues.append(c.hslSaturation())
    m = sum(values) / len(values)
    return {'size': [w, h], 'mean': round(m, 1), 'spread': round((sum((v - m) ** 2 for v in values) / len(values)) ** .5, 1),
            'saturation': round(sum(hues) / len(hues), 1)}


def note(name):
    panel = panel_widget()
    result['steps'].append({'step': name, 'status': panel.status.text(), 'rendering': panel._rendering,
                            'picture': spread(panel.preview.image)})
    panel.window().grab().save(str(out / ('%02d_%s.png' % (len(result['steps']), name))))
    save()


try:
    from moonray_modo import properties
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    mesh = [i for i in modo.Scene().items('mesh')][-1]
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('moonray.library.assign %s' % properties.encode({'shader': 'DwaBaseMaterial', 'parameters': {}}))
    held['material'] = [i for i in modo.Scene().items() if properties.is_material(i)][-1]
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()


def start():
    try:
        panel = panel_widget()
        held['stored'] = panel.preferences.store.value('xpu2/renderer', None)
        panel.preferences.store.setValue('xpu2/renderer', RENDERER)
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        result['renderer'], result['realtime'] = RENDERER, REALTIME
        if REALTIME and hasattr(panel, 'rt'):
            panel.rt.setChecked(True)
        else:
            panel.start_render()
    except Exception:
        result['start_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(25000, add_texture)


def add_texture():
    note('rendered without a texture')
    try:
        from moonray_modo import nodes, properties
        material = held['material']
        stored = properties.read(material)
        graph = stored.get('node_graph') or nodes.from_material(material)
        uv = [m.name for m in modo.Mesh([i for i in modo.Scene().items('mesh')][-1]).geometry.vmaps.uvMaps]
        graph['nodes']['img'] = {'type': 'image', 'parameters': {'file': image, 'uv_map': uv[0] if uv else '', 'texcoord': [0.0, 0.0, 0.0]}, 'inputs': {}, 'position': [-300, 0]}
        graph['nodes'][graph['root']].setdefault('inputs', {})['albedo'] = 'img'
        stored['node_graph'] = graph
        # As the graph editor writes it (node_editor: moonray.material.applyGraph).
        lx.eval('moonray.material.applyGraph {%s} %s' % (material.id, properties.encode(stored)))
        panel = panel_widget()
        if not REALTIME:
            if panel._rendering:
                panel.stop()
            QtCore.QTimer.singleShot(3000, lambda: panel_widget().start_render())
    except Exception:
        result['texture_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(30000, finish)


def finish():
    note('rendered after the texture was added')
    try:
        panel = panel_widget()
        if REALTIME and hasattr(panel, 'rt'):
            panel.rt.setChecked(False)
        if panel._rendering:
            panel.stop()
        if held.get('stored') is None:
            panel.preferences.store.remove('xpu2/renderer')
        else:
            panel.preferences.store.setValue('xpu2/renderer', held['stored'])
    except Exception:
        result['finish_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(1000, lambda: lx.eval('app.quit'))


QtCore.QTimer.singleShot(4000, start)
