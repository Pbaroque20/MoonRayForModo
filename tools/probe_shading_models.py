# python
"""Isolated GUI test: Modo's own renderer on each of its material's shading models, over a range of roughness.

A ball and a box on the ground under one distant light, with no light from the surroundings, so that what shows is
the highlight each model makes. Each case is drawn twice: with the highlight alone on a black material, and with it
over a diffuse colour. The scene the plugin captures is written out once, and each case's material beside its picture,
for tools/check_shading_models.py to draw the same cases in MoonLightIPR and MoonRay."""
import json
import math
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/shading-models'
out.mkdir(parents=True, exist_ok=True)
result = {'cases': []}
WIDTH, HEIGHT = 320, 180
ROUGHNESS = [.1, .2, .35, .5, .7, .9]
KEPT = ('diffCol.R', 'diffCol.G', 'diffCol.B', 'diffAmt', 'specAmt', 'reflAmt', 'rough', 'reflFres', 'specFres', 'metallic', 'brdfType', 'aniso',
        'specCol.R', 'specCol.G', 'specCol.B', 'refSpec')


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
    from moonray_modo import host
    scene = modo.Scene()
    render = scene.renderItem
    camera = scene.renderCamera
    for name, value in (('resX', WIDTH), ('resY', HEIGHT), ('globEnable', False), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    environment = next(iter(scene.items('environment')))
    environment.channel('radiance').set(0.0)
    material = next(iter(scene.items('advancedMaterial')))
    defaults = channels(material)
    result['defaults'] = {key: defaults.get(key) for key in KEPT}
    # The shading models Modo offers, as the channel names them.
    try:
        hints = lx.object.Item(material).ChannelLookup('brdfType')
        result['models_hint'] = [str(h) for h in lx.eval('query sceneservice channel.hints ? {%s:brdfType}' % material.id) or []]
    except Exception as exc:
        result['models_hint_error'] = str(exc)
    models = []
    for kind in ('blinn', 'ashikhmin', 'gtr', 'ggx', 'energy', 'principled', 'phong', 'ward', 'beckmann'):
        try:
            material.channel('brdfType').set(kind)
            if material.channel('brdfType').get() == kind:
                models.append(kind)
        except Exception:
            pass
    result['models'] = models
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
        rings, around = 32, 64
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
    written = False
    for kind in models:
        for rough in ROUGHNESS:
            for look, values in (('gloss', {'diffAmt': 0.0, 'specAmt': 1.0, 'specFres': 0.0}),
                                 ('paint', {'diffCol.R': .6, 'diffCol.G': .3, 'diffCol.B': .15, 'diffAmt': 1.0, 'specAmt': .25, 'specFres': 0.0})):
                name = '%s_%02d_%s' % (kind, round(rough * 100), look)
                case = {'name': name, 'model': kind, 'roughness': rough, 'look': look}
                try:
                    for key in KEPT:
                        if defaults.get(key) is not None:
                            material.channel(key).set(defaults[key])
                    material.channel('brdfType').set(kind)
                    material.channel('rough').set(rough)
                    material.channel('reflAmt').set(0.0)
                    for key, value in values.items():
                        material.channel(key).set(value)
                    case['channels'] = {key: material.channel(key).get() for key in KEPT if key in defaults}
                    lx.eval('!render.animation {%s} openexr' % str(out / ('modo_' + name)))
                    snapshot = host.snapshot()
                    case['warnings'] = snapshot.get('warnings')
                    case['materials'] = snapshot['materials']
                    if not written:
                        (out / 'scene.json').write_text(json.dumps(snapshot, default=str))
                        written = True
                except Exception:
                    case['error'] = traceback.format_exc()
                result['cases'].append(case)
        (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))
