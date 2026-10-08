# python
"""Isolated GUI test: a box and a ball on the ground in a few settings of Modo's material, rendered by Modo and exported for MoonRay.

tools/check_material_parity.py renders the exported scenes and sets the two side by side."""
import json
import math
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/material-parity'
out.mkdir(parents=True, exist_ok=True)
result = {'cases': []}
WIDTH, HEIGHT = 320, 180
PLAIN = {'diffCol.R': .8, 'diffCol.G': .5, 'diffCol.B': .3, 'diffAmt': 1.0, 'specAmt': 0.0, 'reflAmt': 0.0}
CASES = [('default', {}), ('diffuse_only', PLAIN), ('specular', dict(PLAIN, specAmt=.3, rough=.3)), ('reflective', dict(PLAIN, reflAmt=.5, rough=.1)),
         ('fresnel_only', dict(PLAIN, reflFres=1.0, specFres=1.0)), ('metal', dict(PLAIN, metallic=1.0, rough=.3))]


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
    for name, value in (('resX', WIDTH), ('resY', HEIGHT), ('globEnable', True), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    material = next(iter(scene.items('advancedMaterial')))
    defaults = channels(material)
    result['defaults'] = defaults
    ground = scene.addMesh('Ground')
    with ground.geometry as g:
        g.polygons.new([g.vertices.new(place) for place in ((-40, 0, -40), (-40, 0, 40), (40, 0, 40), (40, 0, -40))])
    box = scene.addMesh('Box')
    with box.geometry as g:
        corners = [g.vertices.new((x - 1.0, y, z)) for x in (-.5, .5) for y in (0, 1.4) for z in (-.5, .5)]
        for face in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
            g.polygons.new([corners[i] for i in face])
    ball = scene.addMesh('Ball')
    with ball.geometry as g:
        rings, around = 16, 32
        rows = [[g.vertices.new((1.0 + .7 * math.sin(math.pi * i / rings) * math.cos(2 * math.pi * j / around), .7 + .7 * math.cos(math.pi * i / rings),
                                 .7 * math.sin(math.pi * i / rings) * math.sin(2 * math.pi * j / around))) for j in range(around)] for i in range(1, rings)]
        top, bottom = g.vertices.new((1.0, 1.4, 0)), g.vertices.new((1.0, 0, 0))
        for j in range(around):
            k = (j + 1) % around
            g.polygons.new([top, rows[0][k], rows[0][j]])
            g.polygons.new([bottom, rows[-1][j], rows[-1][k]])
            for i in range(len(rows) - 1):
                g.polygons.new([rows[i][j], rows[i][k], rows[i + 1][k], rows[i + 1][j]])
    camera.position.set((2.6, 2.2, 6.0))
    camera.rotation.set((-12.0, 23.0, 0.0), degrees=True)
    for name, values in CASES:
        case = {'name': name}
        try:
            for key, value in defaults.items():
                if key in ('diffCol.R', 'diffCol.G', 'diffCol.B', 'diffAmt', 'specAmt', 'reflAmt', 'rough', 'reflFres', 'specFres', 'metallic'):
                    material.channel(key).set(value)
            for key, value in values.items():
                material.channel(key).set(value)
            case['channels'] = {key: material.channel(key).get() for key in ('diffAmt', 'specAmt', 'reflAmt', 'rough', 'reflFres', 'specFres', 'metallic', 'refSpec', 'brdfType', 'refIndex')
                                if key in defaults}
            lx.eval('!render.animation {%s} openexr' % str(out / ('modo_' + name)))
            snapshot = host.snapshot()
            case['warnings'] = snapshot.get('warnings')
            case['material'] = {key: value for key, value in next(iter(snapshot['materials'].values())).items()
                                if isinstance(value, (int, float, str, bool)) or (isinstance(value, list) and len(value) <= 4)}
            (out / (name + '.rdla')).write_text(rdla.scene_text(snapshot, WIDTH, HEIGHT, 6, 0.0, str(out / ('moonray_' + name + '.exr'))), encoding='utf-8')
        except Exception:
            case['error'] = traceback.format_exc()
        result['cases'].append(case)
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))
