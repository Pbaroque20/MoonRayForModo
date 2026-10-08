# python
"""Isolated GUI test: what Modo's physical sun delivers. A white card lit by the sun alone, over time of day, haze and the sun's own settings."""
import json
import math
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/modo-sun'
out.mkdir(parents=True, exist_ok=True)
result = {'cases': []}

try:
    scene = modo.Scene()
    render = scene.renderItem
    sun = next(iter(scene.items('sunLight')))
    camera = scene.renderCamera
    for name, value in (('resX', 32), ('resY', 32), ('globEnable', False), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    material = next(iter(scene.items('advancedMaterial')))
    for name, value in (('diffCol.R', 1.0), ('diffCol.G', 1.0), ('diffCol.B', 1.0), ('diffAmt', 1.0), ('specAmt', 0.0), ('reflAmt', 0.0)):
        material.channel(name).set(value)
    card = scene.addMesh('Card')
    with card.geometry as g:
        g.polygons.new([g.vertices.new(place) for place in ((-50, 0, -50), (-50, 0, 50), (50, 0, 50), (50, 0, -50))])
    camera.position.set((0, 5, 0))
    camera.rotation.set((-90, 0, 0), degrees=True)
    sun.channel('sunPos').set(True)
    # The choices of the sun's clamp setting, as Modo lists them.
    try:
        hints = sun.channel('clamp')._item.ChannelIntHint(sun.channel('clamp').index) if hasattr(sun.channel('clamp'), 'index') else None
        result['clamp_hint'] = str(hints)
    except Exception as exc:
        result['clamp_hint_error'] = str(exc)
    # The sun as it is, unclamped and with no gamma, over the day at a latitude where it passes overhead.
    for name, value in (('clamp', 'none'), ('gamma', 1.0), ('lat', 0.4093), ('radiance', 3.0)):
        sun.channel(name).set(value)
    index = 0
    for thinning in (1, 0):
        for haze in (1.0, 2.0, 3.0, 5.0, 8.0):
            for step in range(29):
                hour = 5.0 + step * .25
                case = {'thinning': thinning, 'haze': haze, 'time': hour}
                try:
                    sun.channel('thinning').set(thinning)
                    sun.channel('haze').set(haze)
                    sun.channel('time').set(hour)
                    case['elevation'] = math.degrees(sun.channel('elevation').get())
                    if case['elevation'] > 0:
                        lx.eval('!render.animation {%s} openexr' % str(out / ('sun_%03d' % index)))
                        case['file'] = 'sun_%03d' % index
                except Exception as exc:
                    case['error'] = str(exc)[:200]
                result['cases'].append(case)
                index += 1
    # Checks on how the settings combine.
    checks = [{'clamp': 'none', 'gamma': 2.2}, {'clamp': 'clamp', 'gamma': 1.0}, {'clamp': 'clamp', 'gamma': 2.2}, {'clamp': 'replace', 'gamma': 2.2},
              {'clamp': 'replace', 'gamma': 1.0}, {'clamp': 'replace', 'gamma': 2.2, 'radiance': 6.0}, {'clamp': 'none', 'gamma': 1.0, 'radiance': 6.0},
              {'clamp': 'none', 'gamma': 1.0, 'height': 3000.0}]
    for number, values in enumerate(checks):
        case = {'check': values, 'thinning': 1, 'haze': 2.0, 'time': 9.0}
        for name, value in dict({'thinning': 1, 'haze': 2.0, 'time': 9.0, 'radiance': 3.0, 'height': 10.0}, **values).items():
            sun.channel(name).set(value)
        case['elevation'] = math.degrees(sun.channel('elevation').get())
        lx.eval('!render.animation {%s} openexr' % str(out / ('check_%d' % number)))
        case['file'] = 'check_%d' % number
        result['cases'].append(case)
    try:
        material_light = sun.material
        result['light_color'] = [material_light.channel('lightCol.' + c).get() for c in 'RGB']
    except Exception as exc:
        result['light_color_error'] = str(exc)
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))
