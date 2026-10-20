# python
"""Isolated GUI test: a glass ball in a four-colour sky and no lights, under each of Modo's shading models.

What the ball shows is the sky bent through it and mirrored on it, so how it differs from Modo's own render says
how the plugin's glass differs from Modo's. tools/check_glass.py renders the exported scenes with MoonRay and
compares. MOONRAY_PROBE_CASES limits the cases to those whose names start with one of its words."""
import json
import math
import os
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/glass'
out.mkdir(parents=True, exist_ok=True)
result = {'cases': []}
SIZE = 192
# Clear glass as an artist would set it: no diffuse, all transmitted, Modo's default specular and Fresnel.
BASE = {'diffAmt': 0.0, 'tranAmt': 1.0, 'tranCol.R': 1.0, 'tranCol.G': 1.0, 'tranCol.B': 1.0, 'refIndex': 1.5, 'tranRough': 0.0,
        'specAmt': .04, 'specFres': 1.0, 'reflAmt': .04, 'reflFres': 1.0, 'reflSpec': 1, 'rough': .1, 'brdfType': 'gtr',
        'metallic': 0.0, 'aniso': 0.0, 'dissAmt': 0.0}
CASES = [('gtr', {}), ('principled', {'brdfType': 'principled'}), ('blinn', {'brdfType': 'blinn'}), ('ashikhmin', {'brdfType': 'ashikhmin'}),
         ('gtr_no_reflection', {'reflAmt': 0.0, 'reflSpec': 0}), ('gtr_strong_reflection', {'specAmt': .2, 'reflAmt': .2}),
         ('gtr_no_fresnel', {'specFres': 0.0, 'reflFres': 0.0}), ('gtr_rough', {'rough': .35, 'tranRough': .3}),
         ('principled_rough', {'brdfType': 'principled', 'rough': .35, 'tranRough': .3}),
         ('gtr_tinted', {'tranCol.R': .3, 'tranCol.G': .8, 'tranCol.B': .5}), ('principled_tinted', {'brdfType': 'principled', 'tranCol.R': .3, 'tranCol.G': .8, 'tranCol.B': .5})]
# Refraction roughness alone, the surface's own left smooth: how Modo's blur grows with it.
CASES += [('gtr_refraction_%g' % value, {'tranRough': value}) for value in (.1, .6, .9)]
if os.environ.get('MOONRAY_PROBE_CASES'):
    CASES = [case for case in CASES if any(case[0].startswith(name) for name in os.environ['MOONRAY_PROBE_CASES'].split(','))]


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
    layer.channel('type').set('grad4')
    for name, value in (('zenColor', (.15, .35, 1.0)), ('skyColor', (1.0, .95, .85)), ('gndColor', (.7, .35, .1)), ('nadColor', (.05, .08, .05))):
        for axis, v in zip('RGB', value):
            layer.channel(name + '.' + axis).set(v)
    environment.channel('radiance').set(1.0)
    next(iter(scene.items('sunLight'))).channel('render').set('off')
    material = next(iter(scene.items('advancedMaterial')))
    result['material_defaults'] = channels(material)
    ball = scene.addMesh('Ball')
    with ball.geometry as g:
        rings, around = 64, 128
        rows = [[g.vertices.new((math.sin(math.pi * i / rings) * math.cos(2 * math.pi * j / around), math.cos(math.pi * i / rings),
                                 math.sin(math.pi * i / rings) * math.sin(2 * math.pi * j / around))) for j in range(around)] for i in range(1, rings)]
        top, bottom = g.vertices.new((0, 1, 0)), g.vertices.new((0, -1, 0))
        for j in range(around):
            k = (j + 1) % around
            g.polygons.new([top, rows[0][k], rows[0][j]])
            g.polygons.new([bottom, rows[-1][j], rows[-1][k]])
            for i in range(len(rows) - 1):
                g.polygons.new([rows[i][j], rows[i][k], rows[i + 1][k], rows[i + 1][j]])
    # Level with the ball and near enough that it fills most of the frame; the horizon crosses its middle.
    camera.position.set((0, 0, 4.0))
    camera.rotation.set((0, 0, 0), degrees=True)
    camera.channel('focalLen').set(0.05)
    for name, values in CASES:
        case = {'name': name, 'values': values}
        try:
            for key, value in dict(BASE, **values).items():
                material.channel(key).set(value)
            case['channels'] = {k: v for k, v in channels(material).items() if k in BASE or k.split('.')[0] in BASE}
            lx.eval('!render.animation {%s} openexr' % str(out / ('modo_' + name)))
            snapshot = host.snapshot()
            case['warnings'] = [w for w in snapshot.get('warnings', []) if 'renderOutput' not in w]
            (out / (name + '.rdla')).write_text(rdla.scene_text(snapshot, SIZE, SIZE, 8, 0.0, str(out / ('moonray_' + name + '.exr'))), encoding='utf-8')
            for key in [k for k in snapshot if k.startswith('_')]:
                snapshot.pop(key)
            (out / (name + '.json')).write_text(json.dumps(snapshot, default=str))
        except Exception:
            case['error'] = traceback.format_exc()
        result['cases'].append(case)
except Exception:
    result['error'] = traceback.format_exc()
# Cases rendered before and not this time are kept.
try:
    earlier = json.loads((out / 'report.json').read_text()).get('cases', [])
except (OSError, ValueError):
    earlier = []
done = {case['name'] for case in result['cases']}
result['cases'] = [case for case in earlier if case.get('name') not in done] + result['cases']
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))
