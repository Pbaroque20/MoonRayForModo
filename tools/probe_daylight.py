# python
"""Isolated GUI test: a box on the ground under Modo's physically based daylight and physical sun, rendered by Modo and exported for MoonRay.

tools/check_daylight.py renders the exported scenes and sets the two side by side."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/daylight'
out.mkdir(parents=True, exist_ok=True)
result = {'cases': []}
WIDTH, HEIGHT = 320, 180

try:
    from moonray_modo import host, rdla
    scene = modo.Scene()
    render = scene.renderItem
    environment = next(iter(scene.items('environment')))
    layer = next(i for i in environment.children() if i.type == 'envMaterial')
    sun = next(iter(scene.items('sunLight')))
    camera = scene.renderCamera
    layer.channel('type').set('physical')
    for name, value in (('resX', WIDTH), ('resY', HEIGHT), ('globEnable', True), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    material = next(iter(scene.items('advancedMaterial')))
    for name, value in (('diffCol.R', .8), ('diffCol.G', .8), ('diffCol.B', .8), ('diffAmt', 1.0), ('specAmt', 0.0), ('reflAmt', 0.0)):
        material.channel(name).set(value)
    ground = scene.addMesh('Ground')
    with ground.geometry as g:
        g.polygons.new([g.vertices.new(place) for place in ((-40, 0, -40), (-40, 0, 40), (40, 0, 40), (40, 0, -40))])
    box = scene.addMesh('Box')
    with box.geometry as g:
        corners = [g.vertices.new((x, y, z)) for x in (-.5, .5) for y in (0, 1.6) for z in (-.5, .5)]
        for face in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
            g.polygons.new([corners[i] for i in face])
    camera.position.set((3.0, 2.2, 6.0))
    camera.rotation.set((-12.0, 26.5, 0.0), degrees=True)
    sun.channel('sunPos').set(True)
    cases = [('afternoon', {'time': 16.0, 'haze': 2.0}, {}), ('morning', {'time': 8.0, 'haze': 2.0}, {}), ('hazy', {'time': 14.0, 'haze': 6.0}, {}),
             ('unclamped_gamma', {'time': 16.0, 'haze': 2.0}, {'clampedGamma': 2.0}),
             ('toward_sun', {'time': 17.5, 'haze': 2.0}, {'disc': 4.0}), ('toward_sun_small', {'time': 17.5, 'haze': 2.0}, {'disc': 1.0})]
    for name, sun_values, sky_values in cases:
        case = {'name': name}
        try:
            for key, value in dict({'clamp': 'clamp', 'gamma': 2.2}, **sun_values).items():
                sun.channel(key).set(value)
            for key, value in dict({'normalize': 1, 'clampedGamma': 1.0, 'disc': 1.0}, **sky_values).items():
                layer.channel(key).set(value)
            if name.startswith('toward_sun'):
                # Turn the camera to face the sun, which is low enough to share the picture with the box.
                import math
                from moonray_modo import sun as sun_reader
                toward = sun_reader.direction(sun)
                camera.position.set((-8.0 * toward[0], 1.2, -8.0 * toward[2]))
                camera.rotation.set((math.degrees(math.asin(toward[1])) * .5, math.degrees(math.atan2(-toward[0], -toward[2])), 0.0), degrees=True)
                case['toward'] = toward
            lx.eval('!render.animation {%s} openexr' % str(out / ('modo_' + name)))
            snapshot = host.snapshot()
            case['warnings'] = snapshot.get('warnings')
            case['lights'] = [{k: light.get(k) for k in ('name', 'kind', 'color', 'intensity', 'matrix')} for light in snapshot['lights']]
            case['environments'] = [[{k: v for k, v in entry.items() if k in ('kind', 'sun_direction', 'haze', 'normalize', 'sky_gamma', 'ground_albedo')}
                                     for entry in e.get('layers', [])] for e in snapshot.get('environments', [])]
            # The same plain surface as the Modo material above, so that only the daylight is compared.
            snapshot['materials'] = {key: {'color': [.8, .8, .8], 'roughness': 1.0} for key in list(snapshot['materials']) + ['']}
            text = rdla.scene_text(snapshot, WIDTH, HEIGHT, 6, 0.0, str(out / ('moonray_' + name + '.exr')))
            (out / (name + '.rdla')).write_text(text, encoding='utf-8')
        except Exception:
            case['error'] = traceback.format_exc()
        result['cases'].append(case)
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))
