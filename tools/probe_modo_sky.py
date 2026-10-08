# python
"""Isolated GUI test: have Modo's own renderer draw its physically based daylight, as the reference the plugin's sky is held to.

Each case is the sky seen through a spherical camera (a latitude-longitude picture), and a white
card lit by the sun alone, which gives what the physical sun delivers."""
import json
import math
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/modo-sky'
out.mkdir(parents=True, exist_ok=True)
result = {'cases': []}
CASES = [(n[0], n[1], dict(n[2], normalize=0)) for n in [(60, 2.0, {}), (30, 2.0, {}), (10, 2.0, {}), (2, 2.0, {}), (30, 4.0, {}), (30, 8.0, {}), (60, 1.5, {}), (80, 2.0, {}), (60, 3.0, {}), (45, 1.0, {}), (45, 6.0, {}), (5, 4.0, {})]] + [
         (30, 2.0, {}), (30, 2.0, {'gamma': 2.0}), (60, 2.0, {}), (10, 2.0, {}), (30, 8.0, {})]


def channels(item):
    found = {}
    for name in item.channelNames:
        try:
            found[name] = item.channel(name).get()
        except Exception:
            found[name] = '?'
    return found


try:
    scene = modo.Scene()
    render = scene.renderItem
    environment = next(iter(scene.items('environment')))
    layer = next(i for i in environment.children() if i.type == 'envMaterial')
    sun = next(iter(scene.items('sunLight')))
    camera = scene.renderCamera
    result['sun_channels'] = channels(sun)
    result['layer_channels'] = channels(layer)
    result['environment_channels'] = channels(environment)
    layer.channel('type').set('physical')
    for name, value in (('resX', 256), ('resY', 128), ('globEnable', False), ('aa', 's64') if False else ('first', 1), ('last', 1)):
        try:
            render.channel(name).set(value)
        except Exception as exc:
            result.setdefault('set_errors', []).append([name, str(exc)])
    camera.channel('projType').set('spherical')
    camera.position.set((0, 0, 0))
    camera.rotation.set((0, 0, 0))
    sun.channel('sunPos').set(False)
    material = next(iter(scene.items('advancedMaterial')))
    for name, value in (('diffCol.R', 1.0), ('diffCol.G', 1.0), ('diffCol.B', 1.0), ('diffAmt', 1.0), ('specAmt', 0.0), ('reflAmt', 0.0)):
        material.channel(name).set(value)
    card = scene.addMesh('Card')
    with card.geometry as g:
        g.polygons.new([g.vertices.new(place) for place in ((-50, 0, -50), (-50, 0, 50), (50, 0, 50), (50, 0, -50))])
    from moonray_modo import sun as sun_reader
    for elevation, haze, flags in CASES:
        name = 'e%02d_h%s%s' % (elevation, str(haze).replace('.', '_'), ''.join('_' + k + str(v) for k, v in sorted(flags.items())))
        sun.channel('haze').set(haze)
        layer.channel('normalize').set(flags.get('normalize', 1))
        sun.channel('thinning').set(flags.get('thinning', 1))
        layer.channel('clampedGamma').set(flags.get('gamma', 1.0))
        # A directional light shines along its +Z; turned about X it comes down from the south.
        sun.rotation.set((-math.radians(elevation), 0, 0), degrees=False)
        case = {'name': name, 'elevation': elevation, 'haze': haze, 'flags': flags, 'direction': sun_reader.direction(sun)}
        try:
            card.channel('render').set('off')
            camera.channel('projType').set('spherical')
            camera.position.set((0, 0, 0)); camera.rotation.set((0, 0, 0))
            lx.eval('!render.animation {%s} openexr' % str(out / ('sky_' + name)))
            card.channel('render').set('default')
            camera.channel('projType').set('persp')
            camera.position.set((0, 5, 0)); camera.rotation.set((-90, 0, 0), degrees=True)
            lx.eval('!render.animation {%s} openexr' % str(out / ('card_' + name)))
        except Exception as exc:
            case['error'] = str(exc)
        result['cases'].append(case)
    # Which way is the sun? Look level along -Z with an ordinary camera and the sun 10 degrees up.
    from moonray_modo.host import world_matrix
    sun.rotation.set((-math.radians(10), 0, 0), degrees=False)
    layer.channel('normalize').set(0)
    card.channel('render').set('off')
    camera.channel('projType').set('persp')
    camera.position.set((0, 0, 0)); camera.rotation.set((0, 0, 0))
    lx.eval('!render.animation {%s} openexr' % str(out / 'forward'))
    result['forward'] = {'matrix': world_matrix(sun), 'direction': sun_reader.direction(sun)}
    # The sun placed by date and time, as a physical sun.
    sun.channel('sunPos').set(True)
    sun.channel('haze').set(2.0)
    for hour in (12.0, 17.0):
        sun.channel('time').set(hour)
        name = 'placed_%d' % hour
        case = {'name': name, 'elevation': math.degrees(sun.channel('elevation').get()), 'azimuth': math.degrees(sun.channel('azimuth').get()),
                'haze': 2.0, 'flags': {'normalize': 0}, 'direction': sun_reader.direction(sun), 'matrix': world_matrix(sun)}
        card.channel('render').set('off')
        camera.channel('projType').set('spherical')
        camera.position.set((0, 0, 0)); camera.rotation.set((0, 0, 0))
        lx.eval('!render.animation {%s} openexr' % str(out / ('sky_' + name)))
        card.channel('render').set('default')
        camera.channel('projType').set('persp')
        camera.position.set((0, 5, 0)); camera.rotation.set((-90, 0, 0), degrees=True)
        lx.eval('!render.animation {%s} openexr' % str(out / ('card_' + name)))
        result['cases'].append(case)
    result['files'] = sorted(p.name for p in out.iterdir())
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))
