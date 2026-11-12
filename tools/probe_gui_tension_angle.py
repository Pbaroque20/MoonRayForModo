# python
"""Modo's Tension texture, Type Angle, on folded squares (probe_gui_tension_layer.py's scene with folds of 15 to 179
degrees and meshes of 2, 4 and 8 polygons across), to fit its measure: eight separate squares (each 1 x 1, a 4 x 4 grid
of polygons) facing the camera, each stretched by one morph deformer by a known amount (X only by 0.5, 1, 2 and 3; both
ways by 2 and by 0.5; sheared by 0.5 and 1), glowing by the Tension texture alone (luminous colour, a ramp that rises with its input, -100 to
100, whose evaluated curve is kept). Rendered for each Type the layer offers. The scene as the kit captures it is kept
too. Writes test-results/tension/modo_<type>.exr, <type>.pickle and report.json."""
import json
import math
import pathlib
import pickle
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\tension-angle')
out.mkdir(parents=True, exist_ok=True)
# Each square: its centre, and (fold in degrees about its middle, polygons across).
BANDS = [((-6, 4), (15, 4)), ((-2, 4), (45, 4)), ((2, 4), (75, 4)), ((6, 4), (120, 4)),
         ((-6, 0), (150, 4)), ((-2, 0), (60, 2)), ((2, 0), (60, 8)), ((6, 0), (60, 4)), ((-6, -4), (179, 4))]
report = {'bands': BANDS}
try:
    from moonray_modo import host
    lx.eval('scene.new')
    scene = modo.Scene()
    mesh = scene.addMesh('Sheet')
    starts = []
    with mesh.geometry as geo:
        for (cx, cy), (fold, n) in BANDS:
            starts.append(len(geo.vertices))
            grid = {(i, j): geo.vertices.new((cx + i / float(n) - .5, cy + j / float(n) - .5, 0.0)) for i in range(n + 1) for j in range(n + 1)}
            for i in range(n):
                for j in range(n):
                    geo.polygons.new((grid[i, j], grid[i + 1, j], grid[i + 1, j + 1], grid[i, j + 1]))
    with mesh.geometry as geo:
        morph = geo.vmaps.addMorphMap('stretch', False)
        for band, ((cx, cy), (fold, n)) in enumerate(BANDS):
            for i in range(n + 1):
                for j in range(n + 1):
                    dx, dy = i / float(n) - .5, j / float(n) - .5
                    x, z = dx, 0.0
                    if dx > 0:
                        x, z = dx * math.cos(math.radians(fold)), dx * math.sin(math.radians(fold))
                    morph.setAbsolutePosition(starts[band] + i * (n + 1) + j, (cx + x, cy + dy, z))
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
        for x in (-100.0, 0.0, 100.0):
            lx.eval('channel.key time:%g value:%g channel:{%s:color.%s}' % (x, x + 5.0, layer.id, axis))
    curve = lx.object.GradientFilter(layer.channel('color.R').get())
    report['curve'] = [[x / 100.0, curve.Generate(x / 100.0)] for x in range(-10000, 10001, 5)]
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
    for kind in ('angle',):
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
