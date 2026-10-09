# python
"""Isolated GUI test: what each kind of Modo light sheds on a white card, rendered by Modo and exported for MoonRay.

tools/check_light_units.py renders the exported scenes and gives MoonRay's brightness against Modo's."""
import json
import math
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/light-units'
out.mkdir(parents=True, exist_ok=True)
result = {'cases': []}
SIZE = 96
CASES = [
    ('sun', 'sunLight', {'radiance': 3.0}, 90), ('sun_low', 'sunLight', {'radiance': 3.0}, 30), ('sun_dim', 'sunLight', {'radiance': 1.0}, 90),
    ('sun_spread', 'sunLight', {'radiance': 3.0, 'spread': math.radians(10)}, 90),
    ('point', 'pointLight', {'radiance': 3.0, 'radius': .05}, 90), ('point_big', 'pointLight', {'radiance': 3.0, 'radius': .5}, 90),
    ('point_bright', 'pointLight', {'radiance': 9.0, 'radius': .05}, 90),
    ('area', 'areaLight', {'radiance': 3.0, 'width': 1.0, 'height': 1.0}, 90), ('area_wide', 'areaLight', {'radiance': 3.0, 'width': 2.0, 'height': 1.0}, 90),
    ('area_small', 'areaLight', {'radiance': 3.0, 'width': .25, 'height': .25}, 90),
    ('spot', 'spotLight', {'radiance': 3.0, 'cone': math.radians(60), 'edge': 0.0, 'radius': .01}, 90),
    ('spot_wide', 'spotLight', {'radiance': 3.0, 'cone': math.radians(120), 'edge': 0.0, 'radius': .01}, 90),
    ('spot_soft', 'spotLight', {'radiance': 3.0, 'cone': math.radians(60), 'edge': math.radians(10), 'radius': .01}, 90),
    ('spot_big', 'spotLight', {'radiance': 3.0, 'cone': math.radians(60), 'edge': 0.0, 'radius': .3}, 90),
]


def channels(item):
    found = {}
    for name in item.channelNames:
        try:
            value = item.channel(name).get()
            if isinstance(value, (int, float, str)):
                found[name] = value
        except Exception:
            pass
    return found


try:
    from moonray_modo import host, rdla
    scene = modo.Scene()
    render = scene.renderItem
    camera = scene.renderCamera
    for name, value in (('resX', SIZE), ('resY', SIZE), ('globEnable', False), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    try:
        render.channel('ambRad').set(0.0)
    except Exception as exc:
        result['ambient'] = str(exc)
    material = next(iter(scene.items('advancedMaterial')))
    for name, value in (('diffCol.R', 1.0), ('diffCol.G', 1.0), ('diffCol.B', 1.0), ('diffAmt', 1.0), ('specAmt', 0.0), ('reflAmt', 0.0)):
        material.channel(name).set(value)
    card = scene.addMesh('Card')
    with card.geometry as g:
        g.polygons.new([g.vertices.new(place) for place in ((-20, 0, -20), (-20, 0, 20), (20, 0, 20), (20, 0, -20))])
    camera.position.set((0, 8, 0))
    camera.rotation.set((-90, 0, 0), degrees=True)
    first = next(iter(scene.items('sunLight')))
    lights = {'sunLight': first}
    for kind in ('pointLight', 'areaLight', 'spotLight'):
        lights[kind] = scene.addItem(kind, name=kind)
    result['defaults'] = {kind: channels(item) for kind, item in lights.items()}
    for name, kind, values, elevation in CASES:
        case = {'name': name, 'kind': kind, 'values': values, 'elevation': elevation}
        try:
            for other, item in lights.items():
                item.channel('render').set('default' if other == kind else 'off')
            light = lights[kind]
            for key, value in values.items():
                light.channel(key).set(value)
            # Two metres above the card, shining down on it (or from lower in the sky, for a sun).
            light.position.set((0, 2, 0))
            light.rotation.set((-math.radians(elevation), 0, 0), degrees=False)
            lx.eval('!render.animation {%s} openexr' % str(out / ('modo_' + name)))
            snapshot = host.snapshot()
            case['lights'] = [{k: v for k, v in entry.items() if k != 'matrix'} for entry in snapshot['lights']]
            snapshot['materials'] = {key: {'color': [1, 1, 1], 'roughness': 1.0} for key in list(snapshot['materials']) + ['']}
            snapshot['environments'] = []
            (out / (name + '.rdla')).write_text(rdla.scene_text(snapshot, SIZE, SIZE, 6, 0.0, str(out / ('moonray_' + name + '.exr'))), encoding='utf-8')
        except Exception:
            case['error'] = traceback.format_exc()
        result['cases'].append(case)
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))
