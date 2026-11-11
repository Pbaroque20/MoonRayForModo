# python
"""Modo's Tension texture against Modo's own render, to learn its measure: eight separate squares (each 1 x 1, a 4 x 4 grid
of polygons) facing the camera, each stretched by one morph deformer by a known amount (X only by 0.5, 1, 2 and 3; both
ways by 2 and by 0.5; sheared by 0.5 and 1), glowing by the Tension texture alone (luminous colour, a ramp that rises with its input, -1 to 4
(beyond them it holds), whose evaluated curve is kept). Rendered for each Type the layer offers. The scene as the kit captures it is kept
too. Writes test-results/tension/modo_<type>.exr, <type>.pickle and report.json."""
import json
import math
import pathlib
import pickle
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\tension')
out.mkdir(parents=True, exist_ok=True)
# Each square: its centre, and (scale X, scale Y, shear, fold in degrees about its middle, right half only scaled).
BANDS = [((-6, 4), (0.5, 1, 0, 0, 0)), ((-2, 4), (1, 1, 0, 0, 0)), ((2, 4), (2, 1, 0, 0, 0)), ((6, 4), (3, 1, 0, 0, 0)),
         ((-6, 0), (2, 2, 0, 0, 0)), ((-2, 0), (0.5, 0.5, 0, 0, 0)), ((2, 0), (1, 1, 0.5, 0, 0)), ((6, 0), (1, 1, 1, 0, 0)),
         ((-6, -4), (1, 1, 0, 30, 0)), ((-2, -4), (1, 1, 0, 60, 0)), ((2, -4), (1, 1, 0, 90, 0)), ((6, -4), (2, 1, 0, 0, 1))]
report = {'bands': BANDS}
try:
    from moonray_modo import host
    lx.eval('scene.new')
    scene = modo.Scene()
    mesh = scene.addMesh('Sheet')
    with mesh.geometry as geo:
        for (cx, cy), _ in BANDS:
            grid = {(i, j): geo.vertices.new((cx + i / 4.0 - .5, cy + j / 4.0 - .5, 0.0)) for i in range(5) for j in range(5)}
            for i in range(4):
                for j in range(4):
                    geo.polygons.new((grid[i, j], grid[i + 1, j], grid[i + 1, j + 1], grid[i, j + 1]))
    with mesh.geometry as geo:
        morph = geo.vmaps.addMorphMap('stretch', False)
        for band, ((cx, cy), (sx, sy, k, fold, half)) in enumerate(BANDS):
            for i in range(5):
                for j in range(5):
                    dx, dy = i / 4.0 - .5, j / 4.0 - .5
                    x, z = (max(dx, 0.0) * sx + min(dx, 0.0)) if half else dx * sx, 0.0
                    if fold and dx > 0:
                        x, z = dx * math.cos(math.radians(fold)), dx * math.sin(math.radians(fold))
                    morph.setAbsolutePosition(band * 25 + i * 5 + j, (cx + x + k * dy, cy + dy * sy, z))
    with mesh.geometry as geo:
        morph = geo.vmaps.morphMaps[0]
        report['morph_band1'] = [morph.getAbsolutePosition(25 + k) for k in range(10)]
    deformer = scene.addItem('morphDeform', name='Stretch')
    deformer.channel('mapName').set('stretch')
    deformer.itemGraph('deformers') >> mesh.itemGraph('deformers')
    deformer.channel('strength').set(1.0)
    material = next(i for i in scene.items('advancedMaterial'))
    material.channel('diffAmt').set(0)
    material.channel('specAmt').set(0)
    material.channel('radiance').set(1)
    scene.select(material)
    lx.eval('shader.create tensionTexture')
    layer = next(i for i in scene.items('tensionTexture'))
    layer.channel('effect').set('lumiColor')
    for axis in 'RGB':
        for x in (-1.0, 0.0, 4.0):
            lx.eval('channel.key time:%g value:%g channel:{%s:color.%s}' % (x, x + 5.0, layer.id, axis))
    curve = lx.object.GradientFilter(layer.channel('color.R').get())
    report['curve'] = [[x / 1000.0, curve.Generate(x / 1000.0)] for x in range(-1000, 4001)]
    camera = next(i for i in scene.items('camera'))
    scene.select(camera)
    for name, value in (('pos.X', 0), ('pos.Y', 0), ('pos.Z', 30), ('rot.X', 0), ('rot.Y', 0), ('rot.Z', 0)):
        lx.eval('transform.channel %s %s' % (name, value))
    report['camera_place'] = [lx.eval('query sceneservice item.worldPos ? %s' % camera.id)] if False else str(modo.LocatorSuperType(camera).position.get())
    camera.channel('focalLen').set(0.05)
    camera.channel('apertureX').set(0.036)
    camera.channel('apertureY').set(0.024)
    report['camera'] = {k: camera.channel(k).get() for k in ('focalLen', 'apertureX', 'apertureY')}
    render = scene.renderItem
    for name, value in (('resX', 1536), ('resY', 1024), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    report['types'] = {}
    for kind in ('area', 'angle'):
        try:
            layer.channel('type').set(kind)
        except Exception as exc:
            report['types'][kind] = {'error': str(exc)}
            continue
        held = layer.channel('type').get()
        report['types'][kind] = {'set': held}
        if held != kind:
            continue
        snapshot = host.snapshot()
        report['types'][kind]['warnings'] = [w for w in snapshot.get('warnings', []) if 'ension' in w][:3]
        (out / (kind + '.pickle')).write_bytes(pickle.dumps(snapshot, protocol=4))
        lx.eval('!render.animation {%s} openexr' % str(out / ('modo_' + kind)))
        (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
    report['rendered'] = sorted(p.name for p in out.glob('modo_*'))
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
