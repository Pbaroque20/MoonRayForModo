# python
"""Isolated GUI test: Modo's physically based daylight over a grid of sun heights and haze, for the table the plugin's sky reads.

Each node is the sky through a spherical camera with no solar disc, once as it is and once with
Modo's brightness clamp, whose scale is read off the pair. tools/build_modo_sky.py makes the table."""
import json
import math
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/modo-sky-table'
out.mkdir(parents=True, exist_ok=True)
result = {'nodes': [], 'checks': []}
ELEVATIONS = (-6, -3, -1, 0, 1, 2, 4, 7, 10, 15, 20, 30, 45, 60, 75, 90)
HAZES = (1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 10.0)

try:
    scene = modo.Scene()
    render = scene.renderItem
    environment = next(iter(scene.items('environment')))
    layer = next(i for i in environment.children() if i.type == 'envMaterial')
    sun = next(iter(scene.items('sunLight')))
    camera = scene.renderCamera
    layer.channel('type').set('physical')
    for name, value in (('resX', 256), ('resY', 128), ('globEnable', False), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    camera.channel('projType').set('spherical')
    camera.position.set((0, 0, 0))
    camera.rotation.set((0, 0, 0))
    sun.channel('sunPos').set(False)
    layer.channel('disc').set(0.0)
    layer.channel('clampedGamma').set(1.0)

    def shot(name, elevation, haze, normalize):
        sun.channel('haze').set(haze)
        layer.channel('normalize').set(normalize)
        # A directional light shines along its -Z; turned down about X, the sun stands toward +Z.
        sun.rotation.set((-math.radians(elevation), 0, 0), degrees=False)
        lx.eval('!render.animation {%s} openexr' % str(out / name))

    index = 0
    for haze in HAZES:
        for elevation in ELEVATIONS:
            node = {'elevation': elevation, 'haze': haze, 'file': 'node_%03d' % index}
            try:
                shot(node['file'], elevation, haze, 0)
                shot(node['file'] + '_clamped', elevation, haze, 1)
            except Exception as exc:
                node['error'] = str(exc)[:200]
            result['nodes'].append(node)
            index += 1
        (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
    # How the other settings act on a sky.
    base = {'clampedGamma': 1.0, 'normalize': 0, 'albedo.R': 0.5, 'albedo.G': 0.5, 'albedo.B': 0.5, 'disc': 0.0, 'inscatter': 0.0}
    for number, change in enumerate([{'clampedGamma': 2.0}, {'albedo.R': 0.9, 'albedo.G': 0.1, 'albedo.B': 0.1}, {'disc': 1.0}, {'disc': 4.0},
                                     {'disc': 1.0, 'inscatter': 1.0}, {'normalize': 1, 'disc': 1.0}, {'normalize': 1, 'albedo.R': 0.9, 'albedo.G': 0.1, 'albedo.B': 0.1},
                                     {'normalize': 1, 'clampedGamma': 2.0, 'disc': 1.0}]):
        for name, value in dict(base, **change).items():
            layer.channel(name).set(value)
        sun.channel('haze').set(2.0)
        sun.rotation.set((-math.radians(30), 0, 0), degrees=False)
        lx.eval('!render.animation {%s} openexr' % str(out / ('check_%d' % number)))
        result['checks'].append({'change': change, 'file': 'check_%d' % number})
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))
