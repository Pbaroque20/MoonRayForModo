# python
"""Isolated GUI test: a ball that only reflects, under one light and a black sky, over the range of Modo's roughness.

Modo renders each, and each is exported for MoonRay. tools/check_roughness.py compares the highlights."""
import json
import math
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/roughness'
out.mkdir(parents=True, exist_ok=True)
result = {'cases': []}
SIZE = 128
ROUGHNESS = (.05, .1, .15, .2, .3, .4, .5, .6, .7, .85, 1.0)

try:
    from moonray_modo import host, rdla
    scene = modo.Scene()
    render = scene.renderItem
    camera = scene.renderCamera
    for name, value in (('resX', SIZE), ('resY', SIZE), ('globEnable', False), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    environment = next(iter(scene.items('environment')))
    environment.channel('radiance').set(0.0)
    material = next(iter(scene.items('advancedMaterial')))
    for name, value in (('diffAmt', 0.0), ('specAmt', 1.0), ('specFres', 0.0), ('reflAmt', 0.0), ('reflFres', 0.0),
                        ('specCol.R', 1.0), ('specCol.G', 1.0), ('specCol.B', 1.0)):
        material.channel(name).set(value)
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
    camera.position.set((0, 0, 4.2))
    camera.rotation.set((0, 0, 0), degrees=True)
    sun = next(iter(scene.items('sunLight')))
    sun.channel('radiance').set(3.0)
    # From up and to the left, in front of the ball.
    sun.rotation.set((-35.0, -40.0, 0.0), degrees=True)
    for model in ('gtr', 'principled'):
        material.channel('brdfType').set(model)
        for rough in ROUGHNESS:
            name = '%s_%03d' % (model, round(rough * 100))
            case = {'name': name, 'model': model, 'roughness': rough}
            try:
                material.channel('rough').set(rough)
                lx.eval('!render.animation {%s} openexr' % str(out / ('modo_' + name)))
                snapshot = host.snapshot()
                case['material'] = {key: value for key, value in next(iter(snapshot['materials'].values())).items() if key in ('roughness', 'specular', 'metallic')}
                (out / (name + '.rdla')).write_text(rdla.scene_text(snapshot, SIZE, SIZE, 6, 0.0, str(out / ('moonray_' + name + '.exr'))), encoding='utf-8')
            except Exception:
                case['error'] = traceback.format_exc()
            result['cases'].append(case)
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))
