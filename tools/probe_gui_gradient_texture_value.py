# python
"""Modo's Gradient on Texture Value against Modo's own render, to learn what "the value beneath" is: a plane facing
the camera, luminous by a Constant layer of a known colour, under a Gradient on Texture Value (luminous colour, a ramp
keyed 0 at 0 and 1 at 1, whose evaluated curve is kept). Colours, and the Constant's own Value, to tell what is read. The scene as the kit captures each is kept too. Writes test-results/gradient-texture-value/modo_<case>.exr,
<case>.pickle and report.json."""
import json
import pathlib
import pickle
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\gradient-texture-value')
out.mkdir(parents=True, exist_ok=True)
# Each: the Constant's colour, and its Value (a texture's own value, beside its colour).
CASES = {'red': ((0.8, 0.2, 0.1), 1.0), 'grey': ((0.5, 0.5, 0.5), 1.0), 'red_value30': ((0.8, 0.2, 0.1), 0.3),
         'grey_value70': ((0.5, 0.5, 0.5), 0.7)}
report = {'cases': {}}
try:
    from moonray_modo import host
    lx.eval('scene.new')
    scene = modo.Scene()
    mesh = scene.addMesh('Plane')
    with mesh.geometry as geo:
        corners = [geo.vertices.new((x, y, 0.0)) for x, y in ((-2, -2), (2, -2), (2, 2), (-2, 2))]
        geo.polygons.new(corners)
    material = next(i for i in scene.items('advancedMaterial'))
    material.channel('diffAmt').set(0)
    material.channel('specAmt').set(0)
    material.channel('radiance').set(1)
    scene.select(material)
    lx.eval('shader.create constant')
    constant = next(i for i in scene.items('constant'))
    constant.channel('effect').set('lumiColor')
    scene.select(material)
    lx.eval('shader.create gradient')
    gradient = next(i for i in scene.items('gradient'))
    gradient.channel('effect').set('lumiColor')
    gradient.channel('param').set('textureValue')
    report['param'] = gradient.channel('param').get()
    for axis in 'RGB':
        for x in (0.0, 1.0):
            lx.eval('channel.key time:%g value:%g channel:{%s:color.%s}' % (x, x, gradient.id, axis))
    curve = lx.object.GradientFilter(gradient.channel('color.R').get())
    report['curve'] = [[x / 1000.0, curve.Generate(x / 1000.0)] for x in range(0, 1001)]
    # Which is above which, as Modo has them (the Gradient should be on top).
    report['order'] = [i.name for i in scene.items('textureLayer')] if hasattr(scene, 'items') else None
    camera = next(i for i in scene.items('camera'))
    scene.select(camera)
    for name, value in (('pos.X', 0), ('pos.Y', 0), ('pos.Z', 10), ('rot.X', 0), ('rot.Y', 0), ('rot.Z', 0)):
        lx.eval('transform.channel %s %s' % (name, value))
    render = scene.renderItem
    for name, value in (('resX', 96), ('resY', 64), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    for label, (rgb, value) in CASES.items():
        for axis, v in zip('RGB', rgb):
            constant.channel('color.' + axis).set(v)
        constant.channel('value').set(value)
        snapshot = host.snapshot()
        report['cases'][label] = {'color': rgb, 'value': value, 'warnings': [w for w in snapshot.get('warnings', []) if 'radient' in w][:3]}
        (out / (label + '.pickle')).write_bytes(pickle.dumps(snapshot, protocol=4))
        lx.eval('!render.animation {%s} openexr' % str(out / ('modo_' + label)))
        (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
    report['rendered'] = sorted(p.name for p in out.glob('modo_*'))
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
