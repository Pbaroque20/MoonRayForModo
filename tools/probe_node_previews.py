# python
"""Isolated GUI test: the graph editor's node previews on a sphere whose material takes an image through an HSV colour
correction (the artist's case of 2026-10-30, where every rendered preview came out one flat colour). Records each
node's preview: which way it was made, its file, and how much it varies. Writes test-results/node-previews/report.json."""
import json
import pathlib
import struct
import traceback
import lx
import modo
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/node-previews'
out.mkdir(parents=True, exist_ok=True)
image = str(root / 'downloads/moonray-example-scenes/scenes/bedroom/scene.png')
result = {'steps': []}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def spread(path):
    """Mean and spread of a picture's brightness, 0 to 255."""
    picture = QtGui.QImage(str(path))
    if picture.isNull():
        return None
    values = []
    for y in range(0, picture.height(), 2):
        for x in range(0, picture.width(), 2):
            values.append(QtGui.QColor(picture.pixel(x, y)).lightness())
    mean = sum(values) / len(values)
    colour = [QtGui.QColor(picture.pixel(x, y)).hslSaturation() for y in range(0, picture.height(), 4) for x in range(0, picture.width(), 4)]
    return round(mean, 1), round((sum((v - mean) ** 2 for v in values) / len(values)) ** .5, 1), 'saturation %.0f' % (sum(colour) / len(colour))


try:
    from moonray_modo import properties
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    lx.eval('moonray.library.assign %s' % properties.encode({'shader': 'DwaBaseMaterial', 'parameters': {}}))
    held['item'] = modo.Scene().selected[0]
    result['uv_maps'] = [m.name for m in modo.Mesh(held['item']).geometry.vmaps.uvMaps] if held['item'].type == 'mesh' else None
except Exception:
    result['error'] = traceback.format_exc()
save()


def step2():
    try:
        from moonray_modo.node_editor import open_editor
        editor = held['editor'] = open_editor(held['item'])
        # Each node's picture as it is shown, kept for the report.
        kind = type(next(iter(editor.items.values())))
        shown = kind.show_preview
        def recorded(self, path, waiting=False):
            self.probe_path = path
            return shown(self, path, waiting)
        kind.show_preview = recorded
        uv = (result.get('uv_maps') or ['Texture'])[0]
        nodes = editor.graph['nodes']
        nodes['img'] = {'type': 'image', 'parameters': {'file': image, 'uv_map': uv}, 'inputs': {}, 'position': [-300, 0]}
        nodes['hsv'] = {'type': 'ColorCorrectHsvMap', 'parameters': {'saturation_factor': 0.0}, 'inputs': {'input': 'img'}, 'position': [0, 0]}
        nodes[editor.graph['root']].setdefault('inputs', {})['albedo'] = 'hsv'
        editor.rebuild()
        result['graph'] = {k: [v['type'], v.get('inputs')] for k, v in editor.graph['nodes'].items()}
        result['wanted'] = {k: editor.previews.wanted(k) for k in editor.graph['nodes']}
        editor.previews.refresh()
    except Exception:
        result['step2_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(4000, lambda: look(1))


def look(round_):
    try:
        editor = held['editor']
        previews = editor.previews
        state = {'round': round_, 'pending': sorted(previews.pending), 'kept': type(previews.kept).__name__ if previews.kept else previews.kept}
        for identity, item in editor.items.items():
            path = getattr(item, 'probe_path', None)
            state[identity] = {'previewed': getattr(item, 'previewed', None), 'path': path, 'spread': spread(path) if path else None}
        result['steps'].append(state)
        editor.grab().save(str(out / ('editor-%d.png' % round_)))
        if round_ == 1:
            # The HSV node's picture made by hand, step by step, as Previews does where MoonRay is not kept loaded.
            from moonray_modo import graph_bake, native, nodes as graph_nodes, persistent
            trace = result['by_hand'] = {}
            try:
                runtime = native.tool('moonray.exe').parent
                trace['runtime'] = str(runtime)
                trace['persistent_supported'] = persistent.supported(runtime)
                graph = graph_nodes.effective(editor.graph)
                exr, text = graph_bake.written(graph, 'hsv', size=96)
                trace['exr'], trace['text_given'] = str(exr), text is not None
                exr, render = graph_bake.prepared(graph, 'hsv', runtime, size=96)
                trace['render_given'] = render is not None
                if render is not None:
                    render()
                trace['exr_written'] = exr.is_file()
            except Exception:
                trace['error'] = traceback.format_exc()[-1500:]
    except Exception:
        result['look_error'] = traceback.format_exc()
    save()
    if round_ < 4:
        QtCore.QTimer.singleShot(5000, lambda: look(round_ + 1))
    else:
        QtCore.QTimer.singleShot(500, lambda: lx.eval('app.quit'))


QtCore.QTimer.singleShot(1500, step2)
