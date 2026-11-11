# python
"""Command-line twin of probe_gui_gradient_inputs.py for the inputs given below: the same scene, captured as the kit
hands it on (no render; Modo's renders are probe_gui_gradient_inputs.py's). Modo's Gradient texture on each of its Sample and Surface Parameters, against Modo's own render, to translate them:
a unit sphere (with UVs) 10 units in front of the camera, glowing by a Gradient alone (luminous colour, its default ramp),
the Gradient's input set to each parameter in turn. Modo renders each; from where each pixel lies on the sphere its true
angle, slope, distance and place are known, and the render says what the input is there. The scene as the kit captures it
is kept too. Writes test-results/gradient-inputs/modo_<input>.exr, <input>.pickle and report.json."""
import json
import math
import pathlib
import pickle
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\gradient-inputs')
out.mkdir(parents=True, exist_ok=True)
INPUTS = ['textureU', 'textureV']
report = {'inputs': {}}
try:
    from moonray_modo import host
    lx.eval('scene.new')
    scene = modo.Scene()
    mesh = scene.addMesh('Ball')
    geometry = modo.Mesh(mesh).geometry
    rings, sides = 48, 96
    points = {}
    for i in range(rings + 1):
        lat = math.pi * i / rings - math.pi / 2
        for j in range(sides + 1):
            lon = 2 * math.pi * j / sides
            points[i, j] = geometry.vertices.new((math.cos(lat) * math.sin(lon), math.sin(lat), math.cos(lat) * math.cos(lon)))
    polygons = []
    for i in range(rings):
        for j in range(sides):
            polygons.append(((i, j), geometry.polygons.new((points[i, j], points[i, j + 1], points[i + 1, j + 1], points[i + 1, j]))))
    geometry.setMeshEdits()
    geometry = modo.Mesh(mesh).geometry
    uvs = geometry.vmaps.addUVMap('Texture')
    # Per vertex: the seam has vertices of its own (sides + 1 columns), so u runs 0 to 1 round without a jump.
    for (i, j), vertex in points.items():
        uvs[vertex.index] = (j / sides, i / rings)
    geometry.setMeshEdits()
    material = next(i for i in scene.items('advancedMaterial'))
    material.channel('diffAmt').set(0)
    material.channel('specAmt').set(0)
    material.channel('radiance').set(1)
    scene.select(material)
    lx.eval('shader.create gradient')
    gradient = next(i for i in scene.items('gradient'))
    gradient.channel('effect').set('lumiColor')
    # A ramp that rises with its input, from -100 to 100 (keys at -100, 0 and 100 on each colour), which Modo bends
    # smoothly between its keys; the evaluated curve is kept, so that a rendered value can be turned back into its input.
    for axis in 'RGB':
        for x in (-100.0, 0.0, 100.0):
            lx.eval('channel.key time:%g value:%g channel:{%s:color.%s}' % (x, x, gradient.id, axis))
    curve = lx.object.GradientFilter(gradient.channel('color.R').get())
    report['curve'] = [[x / 100.0, curve.Generate(x / 100.0)] for x in range(-10000, 10001, 5)]
    camera = next(i for i in scene.items('camera'))
    modo.LocatorSuperType(camera).position.set((0, 0, 10))
    modo.LocatorSuperType(camera).rotation.set((0, 0, 0))
    report['camera'] = {k: camera.channel(k).get() for k in ('focalLen', 'apertureX', 'apertureY')}
    render = scene.renderItem
    for name, value in (('resX', 256), ('resY', 256), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    for name in INPUTS:
        try:
            gradient.channel('param').set(name)
            report['inputs'][name] = {'set': gradient.channel('param').get()}
            snapshot = host.snapshot()
            report['inputs'][name]['warnings'] = [w for w in snapshot.get('warnings', []) if 'radient' in w][:3]
            (out / (name + '.pickle')).write_bytes(pickle.dumps(snapshot, protocol=4))
        except Exception as exc:
            report['inputs'].setdefault(name, {})['error'] = str(exc)
        (out / 'report_cl.json').write_text(json.dumps(report, indent=1, default=str))
    report['rendered'] = sorted(p.name for p in out.glob('modo_*'))
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report_cl.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
