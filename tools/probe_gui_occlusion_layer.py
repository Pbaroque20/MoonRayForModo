# python
"""Modo's Occlusion texture against Modo's own render, to translate it: a floor (y = 0, x from 0 to 4) meeting a wall
(x = 0) along one edge, seen from straight above, the floor glowing by an Occlusion layer alone (luminous colour). Across
the picture the floor's distance from the wall runs 0 to 4, so each row of the render is how open the floor is against
that distance. Cases: Modo's defaults, a wider spread, a shorter distance, and Same Surface on, each with 256 rays to keep
noise down. Writes test-results/occlusion-layer/modo_<case>.exr and report.json."""
import json
import math
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\occlusion-layer')
out.mkdir(parents=True, exist_ok=True)
CASES = {'default': {}, 'spread90': {'spread': math.pi / 2}, 'dist05': {'dist': 0.5}, 'samesurf': {'sameSurf': 1},
         'dist1': {'dist': 1.0}}
report = {'cases': {}}
try:
    lx.eval('scene.new')
    scene = modo.Scene()
    mesh = scene.addMesh('Corner')
    geometry = modo.Mesh(mesh).geometry
    floor = [geometry.vertices.new(p) for p in ((0, 0, -2), (0, 0, 2), (4, 0, 2), (4, 0, -2))]
    geometry.polygons.new(floor)
    wall = [geometry.vertices.new(p) for p in ((0, 0, -2), (0, 4, -2), (0, 4, 2), (0, 0, 2))]
    geometry.polygons.new(wall)
    geometry.setMeshEdits()
    material = next(i for i in scene.items('advancedMaterial'))
    material.channel('diffAmt').set(0)
    material.channel('specAmt').set(0)
    material.channel('radiance').set(1)
    scene.select(material)
    lx.eval('shader.create occlusion')
    occlusion = next(i for i in scene.items('occlusion'))
    occlusion.channel('effect').set('lumiColor')
    occlusion.channel('rays').set(256)
    defaults = {k: occlusion.channel(k).get() for k in ('type', 'rays', 'dist', 'spread', 'sameSurf', 'minAngle', 'maxAngle', 'cutoff')}
    report['defaults'] = defaults
    report['type_choices'] = None
    camera = next(i for i in scene.items('camera'))
    modo.LocatorSuperType(camera).position.set((2, 30, 0))
    modo.LocatorSuperType(camera).rotation.set((-math.pi / 2, 0, 0))
    # 5 m across at 30 m (36 mm film): x from -0.5 to 4.5, the wall 25.6 pixels in.
    camera.channel('focalLen').set(30 * 0.036 / 5.0)
    render = scene.renderItem
    for name, value in (('resX', 256), ('resY', 64), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    for case, values in CASES.items():
        for key, value in defaults.items():
            occlusion.channel(key).set(values.get(key, value))
        try:
            lx.eval('!render.animation {%s} openexr' % str(out / ('modo_' + case)))
            report['cases'][case] = {k: occlusion.channel(k).get() for k in defaults}
        except Exception as exc:
            report['cases'][case] = {'error': str(exc)}
        (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
    report['rendered'] = sorted(p.name for p in out.glob('modo_*'))
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
