# python
"""Isolated GUI test: a ball in an even white sky and no lights, over Modo's specular, reflection and Fresnel settings.

With nothing but the sky to reflect, what the ball shows from its middle to its edge is how much it
reflects at each angle. tools/check_fresnel.py compares Modo's with MoonRay's of the exported scenes."""
import json
import math
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/fresnel'
out.mkdir(parents=True, exist_ok=True)
result = {'cases': []}
SIZE = 128
BASE = {'diffAmt': 0.0, 'diffCol.R': .8, 'diffCol.G': .5, 'diffCol.B': .3, 'specAmt': 0.0, 'specFres': 0.0, 'reflAmt': 0.0, 'reflFres': 0.0,
        'rough': .1, 'brdfType': 'gtr', 'metallic': 0.0, 'aniso': 0.0}
CASES = [('diffuse_colour', {'diffAmt': 1.0}), ('diffuse_half', {'diffAmt': .5}),
         ('spec_004', {'specAmt': .04}), ('spec_030', {'specAmt': .3}), ('spec_100', {'specAmt': 1.0}),
         ('spec_000_fresnel', {'specFres': 1.0}), ('spec_004_fresnel', {'specAmt': .04, 'specFres': 1.0}), ('spec_030_fresnel', {'specAmt': .3, 'specFres': 1.0}),
         ('spec_030_fresnel_half', {'specAmt': .3, 'specFres': .5}),
         ('refl_030', {'reflAmt': .3}), ('refl_030_fresnel', {'reflAmt': .3, 'reflFres': 1.0}), ('refl_030_spec_010', {'reflAmt': .3, 'specAmt': .1}),
         ('spec_030_rough', {'specAmt': .3, 'rough': .5}), ('spec_030_fresnel_rough', {'specAmt': .3, 'specFres': 1.0, 'rough': .5}),
         ('diffuse_spec_fresnel', {'diffAmt': 1.0, 'specAmt': .04, 'specFres': 1.0, 'rough': .4}),
         ('diffuse_spec_030', {'diffAmt': 1.0, 'specAmt': .3, 'rough': .3}),
         ('blinn_030', {'specAmt': .3, 'brdfType': 'blinn', 'rough': .3}), ('gtr_030', {'specAmt': .3, 'rough': .3}),
         ('aniso_030', {'specAmt': .3, 'rough': .3, 'aniso': .7})]


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
    for name, value in (('resX', SIZE), ('resY', SIZE), ('globEnable', True), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    environment = next(iter(scene.items('environment')))
    layer = next(i for i in environment.children() if i.type == 'envMaterial')
    layer.channel('type').set('constant')
    for axis in 'RGB':
        layer.channel('zenColor.' + axis).set(1.0)
    environment.channel('radiance').set(1.0)
    next(iter(scene.items('sunLight'))).channel('render').set('off')
    material = next(iter(scene.items('advancedMaterial')))
    result['material_channels'] = channels(material)
    ball = scene.addMesh('Ball')
    with ball.geometry as g:
        rings, around = 48, 96
        rows = [[g.vertices.new((math.sin(math.pi * i / rings) * math.cos(2 * math.pi * j / around), math.cos(math.pi * i / rings),
                                 math.sin(math.pi * i / rings) * math.sin(2 * math.pi * j / around))) for j in range(around)] for i in range(1, rings)]
        top, bottom = g.vertices.new((0, 1, 0)), g.vertices.new((0, -1, 0))
        for j in range(around):
            k = (j + 1) % around
            g.polygons.new([top, rows[0][k], rows[0][j]])
            g.polygons.new([bottom, rows[-1][j], rows[-1][k]])
            for i in range(len(rows) - 1):
                g.polygons.new([rows[i][j], rows[i][k], rows[i + 1][k], rows[i + 1][j]])
    # From far off through a long lens, so that the ball's edge is seen nearly edge on.
    camera.position.set((0, 0, 40.0))
    camera.rotation.set((0, 0, 0), degrees=True)
    camera.channel('focalLen').set(0.35)
    for name, values in CASES:
        case = {'name': name, 'values': values}
        try:
            for key, value in dict(BASE, **values).items():
                material.channel(key).set(value)
            lx.eval('!render.animation {%s} openexr' % str(out / ('modo_' + name)))
            snapshot = host.snapshot()
            case['warnings'] = [w for w in snapshot.get('warnings', []) if 'renderOutput' not in w]
            (out / (name + '.rdla')).write_text(rdla.scene_text(snapshot, SIZE, SIZE, 6, 0.0, str(out / ('moonray_' + name + '.exr'))), encoding='utf-8')
            for key in [k for k in snapshot if k.startswith('_')]:
                snapshot.pop(key)
            (out / (name + '.json')).write_text(json.dumps(snapshot, default=str))
        except Exception:
            case['error'] = traceback.format_exc()
        result['cases'].append(case)
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))
