# python
"""Isolated GUI test: have Modo's own renderer draw the solar disc of its physically based daylight, over a grid of
sun heights and haze amounts, at five amounts of Disc In-Scatter from nothing to all of it: what the setting does
to the disc is not a straight line, least of all with the sun low in thick haze.

Each picture is the sky through a spherical camera, 1024 by 512, with the disc four times its usual width so that
its middle covers several pixels. A few more pictures say what else changes the disc: its size, the sky's clamp and
gamma, and the sun's thinning. tools/build_modo_disc.py turns the pictures into the table the plugin reads."""
import json
import math
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/modo-disc'
out.mkdir(parents=True, exist_ok=True)
ELEVATIONS = [1, 2, 5, 10, 20, 30, 45, 60, 80]
HAZES = [1.0, 2.0, 4.0, 8.0]
AMOUNTS = [0.0, 0.25, 0.5, 0.75, 1.0]
result = {'elevations': ELEVATIONS, 'hazes': HAZES, 'amounts': AMOUNTS, 'nodes': [], 'checks': []}
try:
    scene = modo.Scene()
    render = scene.renderItem
    environment = next(iter(scene.items('environment')))
    layer = next(i for i in environment.children() if i.type == 'envMaterial')
    sun = next(iter(scene.items('sunLight')))
    camera = scene.renderCamera
    layer.channel('type').set('physical')
    for name, value in (('resX', 1024), ('resY', 512), ('first', 1), ('last', 1), ('globEnable', False)):
        render.channel(name).set(value)
    camera.channel('projType').set('spherical')
    camera.position.set((0, 0, 0))
    camera.rotation.set((0, 0, 0))
    sun.channel('sunPos').set(False)
    result['defaults'] = {name: layer.channel(name).get() for name in ('disc', 'inscatter', 'normalize', 'clampedGamma')}
    result['sun_defaults'] = {name: sun.channel(name).get() for name in ('haze', 'thinning', 'gamma', 'clamp', 'radiance', 'spread') if name in sun.channelNames}

    def shot(name, elevation, haze, amount, disc=4.0, **more):
        sun.channel('haze').set(haze)
        sun.rotation.set((-math.radians(elevation), 0, 0), degrees=False)
        values = dict({'disc': disc, 'inscatter': amount, 'normalize': 0, 'clampedGamma': 1.0}, **{k: v for k, v in more.items() if k != 'thinning'})
        for key, value in values.items():
            layer.channel(key).set(value)
        sun.channel('thinning').set(more.get('thinning', 1))
        lx.eval('!render.animation {%s} openexr' % str(out / name))

    for e, elevation in enumerate(ELEVATIONS):
        for h, haze in enumerate(HAZES):
            for a, amount in enumerate(AMOUNTS):
                name = 'disc_%d_%d_%d' % (e, h, a)
                shot(name, elevation, haze, amount)
                result['nodes'].append({'file': name, 'elevation': elevation, 'haze': haze, 'inscatter': amount})
        (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
    # What else was looked at once and found to leave the disc alone: its size, the sky's gamma and the sun's thinning.
    # With Clamp Sky Brightness on, the disc is its colour with its strongest part made 1.
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))
