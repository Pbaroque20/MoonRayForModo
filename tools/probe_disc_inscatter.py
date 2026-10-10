# python
"""Isolated GUI test: what Modo's Disc In-Scatter does to a physically based sky.

The sky is drawn through a spherical camera with a large solar disc, with the sun high and low, at three amounts of
in-scatter; and a white card under the same skies with global illumination on, to see whether the light changes."""
import json
import math
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/disc-inscatter'
out.mkdir(parents=True, exist_ok=True)
result = {'cases': []}
try:
    scene = modo.Scene()
    render = scene.renderItem
    environment = next(iter(scene.items('environment')))
    layer = next(i for i in environment.children() if i.type == 'envMaterial')
    sun = next(iter(scene.items('sunLight')))
    camera = scene.renderCamera
    layer.channel('type').set('physical')
    for name, value in (('resX', 512), ('resY', 256), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    sun.channel('sunPos').set(False)
    sun.channel('haze').set(2.0)
    layer.channel('normalize').set(0)
    layer.channel('clampedGamma').set(1.0)
    material = next(iter(scene.items('advancedMaterial')))
    for name, value in (('diffCol.R', 1.0), ('diffCol.G', 1.0), ('diffCol.B', 1.0), ('diffAmt', 1.0), ('specAmt', 0.0), ('reflAmt', 0.0)):
        material.channel(name).set(value)
    card = scene.addMesh('Card')
    with card.geometry as g:
        g.polygons.new([g.vertices.new(place) for place in ((-50, 0, -50), (-50, 0, 50), (50, 0, 50), (50, 0, -50))])
    result['inscatter_default'] = layer.channel('inscatter').get()
    result['disc_default'] = layer.channel('disc').get()
    for elevation in (30, 5):
        sun.rotation.set((-math.radians(elevation), 0, 0), degrees=False)
        for disc in (8.0,):
            for amount in (0.0, 0.5, 1.0):
                layer.channel('disc').set(disc)
                layer.channel('inscatter').set(amount)
                name = 'e%02d_d%d_i%03d' % (elevation, disc, round(amount * 100))
                render.channel('globEnable').set(False)
                card.channel('render').set('off')
                camera.channel('projType').set('spherical')
                camera.position.set((0, 0, 0)); camera.rotation.set((0, 0, 0))
                lx.eval('!render.animation {%s} openexr' % str(out / ('sky_' + name)))
                render.channel('globEnable').set(True)
                card.channel('render').set('default')
                camera.channel('projType').set('persp')
                camera.position.set((0, 5, 0)); camera.rotation.set((-90, 0, 0), degrees=True)
                lx.eval('!render.animation {%s} openexr' % str(out / ('card_' + name)))
                result['cases'].append({'name': name, 'elevation': elevation, 'disc': disc, 'inscatter': amount})
    result['files'] = sorted(p.name for p in out.iterdir())
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))
