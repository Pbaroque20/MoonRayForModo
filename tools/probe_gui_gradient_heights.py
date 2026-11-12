# python
"""Modo's Gradient on Bump Height, Displacement Height and Clip Distance against Modo's own render, in scenes that give
each something to read. A plane facing the camera glows by the Gradient alone (luminous colour, a ramp keyed -100, 0 and
100 to the same values, whose curve is kept). For the heights a Constant on Bump or Displacement is made first and the
Gradient above it, with the Constant's value, the material's bump amplitude and its displacement varied. For Clip
Distance a plane tilted away from the camera, and a sphere. The Shader Tree order of each case is kept. Writes
test-results/gradient-heights/modo_<case>.exr, <case>.pickle (the scene as the kit captures it) and report.json."""
import json
import math
import pathlib
import pickle
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\gradient-heights')
out.mkdir(parents=True, exist_ok=True)
report = {'cases': {}}


def plane(scene, tilt=0.0, n=8):
    mesh = scene.addMesh('Plane')
    with mesh.geometry as geo:
        grid = {}
        for i in range(n + 1):
            for j in range(n + 1):
                x, y = 4.0 * i / n - 2, 4.0 * j / n - 2
                grid[i, j] = geo.vertices.new((x, y * math.cos(tilt), -y * math.sin(tilt)))
        for i in range(n):
            for j in range(n):
                geo.polygons.new((grid[i, j], grid[i + 1, j], grid[i + 1, j + 1], grid[i, j + 1]))
    return mesh


def ball(scene):
    mesh = scene.addMesh('Ball')
    with mesh.geometry as geo:
        rings, sides = 24, 48
        p = {}
        for i in range(rings + 1):
            lat = math.pi * i / rings - math.pi / 2
            for j in range(sides):
                lon = 2 * math.pi * j / sides
                p[i, j] = geo.vertices.new((1.5 * math.cos(lat) * math.sin(lon), 1.5 * math.sin(lat), 1.5 * math.cos(lat) * math.cos(lon)))
        for i in range(rings):
            for j in range(sides):
                geo.polygons.new((p[i, j], p[i, (j + 1) % sides], p[i + 1, (j + 1) % sides], p[i + 1, j]))
    return mesh


def material_of(scene):
    material = next(i for i in scene.items('advancedMaterial'))
    material.channel('diffAmt').set(0)
    material.channel('specAmt').set(0)
    material.channel('radiance').set(1)
    return material


def gradient_above(scene, below, param):
    scene.select(below)
    lx.eval('shader.create gradient')
    gradient = next(i for i in scene.items('gradient'))
    gradient.channel('effect').set('lumiColor')
    gradient.channel('param').set(param)
    for axis in 'RGB':
        for x in (-100.0, 0.0, 100.0):
            lx.eval('channel.key time:%g value:%g channel:{%s:color.%s}' % (x, x, gradient.id, axis))
    curve = lx.object.GradientFilter(gradient.channel('color.R').get())
    report['curve'] = [[x / 100.0, curve.Generate(x / 100.0)] for x in range(-10000, 10001, 5)]
    return gradient


def camera_and_render(scene, z=8.0):
    camera = next(i for i in scene.items('camera'))
    scene.select(camera)
    for name, value in (('pos.X', 0), ('pos.Y', 0), ('pos.Z', z), ('rot.X', 0), ('rot.Y', 0), ('rot.Z', 0)):
        lx.eval('transform.channel %s %s' % (name, value))
    report['camera'] = {k: camera.channel(k).get() for k in ('focalLen', 'apertureX', 'apertureY', 'clipDist', 'clipping')
                        if camera.channel(k) is not None}
    render = scene.renderItem
    for name, value in (('resX', 192), ('resY', 128), ('first', 1), ('last', 1)):
        render.channel(name).set(value)


def tree(scene):
    rows = []
    for layer in scene.items('textureLayer'):
        try:
            rows.append([layer.name, layer.type, layer.parent.name if layer.parent else None, layer.parentIndex])
        except Exception as exc:
            rows.append([layer.name, str(exc)])
    return rows


def render(case, scene, extra):
    report['cases'][case] = dict(extra, tree=tree(scene))
    from moonray_modo import host
    snapshot = host.snapshot()
    report['cases'][case]['warnings'] = [w for w in snapshot.get('warnings', []) if 'radient' in w][:3]
    (out / (case + '.pickle')).write_bytes(pickle.dumps(snapshot, protocol=4))
    lx.eval('!render.animation {%s} openexr' % str(out / ('modo_' + case)))


HEIGHT_CASES = [
    ('bump03', 'bump', 'bumpHeight', 0.3, {}),
    ('bump07', 'bump', 'bumpHeight', 0.7, {}),
    ('bump03_amp2', 'bump', 'bumpHeight', 0.3, {'bumpAmp': 'double'}),
    ('bump_none', None, 'bumpHeight', 0.0, {}),
    ('disp03', 'displace', 'displaceHeight', 0.3, {'displace': 0.1}),
    ('disp07', 'displace', 'displaceHeight', 0.7, {'displace': 0.1}),
    ('disp03_d2', 'displace', 'displaceHeight', 0.3, {'displace': 0.2}),
    ('disp_none', None, 'displaceHeight', 0.0, {'displace': 0.1}),
]

try:
    for case, effect, param, value, settings in HEIGHT_CASES:
        try:
            lx.eval('scene.new')
            scene = modo.Scene()
            plane(scene)
            material = material_of(scene)
            info = {'param': param, 'value': value}
            if 'bumpAmp' in settings:
                amp = material.channel('bumpAmp').get()
                material.channel('bumpAmp').set(2 * amp)
            info['bumpAmp'] = material.channel('bumpAmp').get()
            if 'displace' in settings:
                material.channel('displace').set(settings['displace'])
            info['displace'] = material.channel('displace').get()
            below = material
            if effect:
                scene.select(material)
                lx.eval('shader.create constant')
                constant = next(i for i in scene.items('constant'))
                constant.channel('effect').set(effect)
                constant.channel('value').set(value)
                below = constant
            gradient_above(scene, below, param)
            camera_and_render(scene)
            render(case, scene, info)
        except Exception:
            report['cases'][case] = {'error': traceback.format_exc()}
        (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
    for case, make, z in (('clip_tilt', lambda s: plane(s, tilt=1.0), 8.0), ('clip_ball', ball, 8.0), ('clip_ball_far', ball, 20.0)):
        try:
            lx.eval('scene.new')
            scene = modo.Scene()
            make(scene)
            material = material_of(scene)
            gradient_above(scene, material, 'clipDist')
            camera_and_render(scene, z)
            render(case, scene, {'param': 'clipDist', 'cameraZ': z})
        except Exception:
            report['cases'][case] = {'error': traceback.format_exc()}
        (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
    report['rendered'] = sorted(p.name for p in out.glob('modo_*'))
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
