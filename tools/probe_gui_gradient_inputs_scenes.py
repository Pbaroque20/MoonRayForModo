# python
"""Modo's Gradient on Surface ID, Bump Height and Displacement Height against Modo's own render, each in a scene that
gives it something to read: three cubes (separate meshes, one material) for Surface ID; a plane under a Constant of 0.3
on Bump, then on Displacement (the material displacing 0.1), beneath the Gradient, for the heights. The Gradient glows
(luminous colour, a ramp keyed -100, 0 and 100 to the same values, whose curve is kept). Writes
test-results/gradient-inputs-scenes/modo_<case>.exr and report.json."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\gradient-inputs-scenes')
out.mkdir(parents=True, exist_ok=True)
report = {'cases': {}}


def cube(scene, name, x, size=1.0):
    mesh = scene.addMesh(name)
    with mesh.geometry as geo:
        h = size / 2
        c = [geo.vertices.new((x + a, b, d)) for a in (-h, h) for b in (-h, h) for d in (-h, h)]
        for face in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
            geo.polygons.new([c[i] for i in face])
    return mesh


def setup(scene, param):
    material = next(i for i in scene.items('advancedMaterial'))
    material.channel('diffAmt').set(0)
    material.channel('specAmt').set(0)
    material.channel('radiance').set(1)
    scene.select(material)
    lx.eval('shader.create gradient')
    gradient = next(i for i in scene.items('gradient'))
    gradient.channel('effect').set('lumiColor')
    gradient.channel('param').set(param)
    for axis in 'RGB':
        for x in (-100.0, 0.0, 100.0):
            lx.eval('channel.key time:%g value:%g channel:{%s:color.%s}' % (x, x, gradient.id, axis))
    curve = lx.object.GradientFilter(gradient.channel('color.R').get())
    report['curve'] = [[x / 100.0, curve.Generate(x / 100.0)] for x in range(-10000, 10001, 5)]
    camera = next(i for i in scene.items('camera'))
    scene.select(camera)
    for name, value in (('pos.X', 0), ('pos.Y', 0), ('pos.Z', 8), ('rot.X', 0), ('rot.Y', 0), ('rot.Z', 0)):
        lx.eval('transform.channel %s %s' % (name, value))
    render = scene.renderItem
    for name, value in (('resX', 192), ('resY', 128), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    return material, gradient


def constant_beneath(scene, material, effect, value):
    scene.select(material)
    lx.eval('shader.create constant')
    constant = next(i for i in scene.items('constant'))
    constant.channel('effect').set(effect)
    constant.channel('value').set(value)
    # Beneath the Gradient: moved below it in the Shader Tree.
    try:
        lx.eval('texture.parent {%s} %d item:{%s}' % (constant.parent.id, 0, constant.id))
    except Exception as exc:
        report.setdefault('notes', []).append('reorder: %s' % exc)
    return constant


try:
    lx.eval('scene.new')
    scene = modo.Scene()
    for name, x in (('CubeA', -2.0), ('CubeB', 0.0), ('CubeC', 2.0)):
        cube(scene, name, x)
    setup(scene, 'surfaceID')
    report['cases']['surface_id'] = {'order': [i.name for i in scene.items('textureLayer')]}
    lx.eval('!render.animation {%s} openexr' % str(out / 'modo_surface_id'))
    for case, effect, param in (('bump', 'bump', 'bumpHeight'), ('displace', 'displace', 'displaceHeight')):
        lx.eval('scene.new')
        scene = modo.Scene()
        mesh = scene.addMesh('Plane')
        with mesh.geometry as geo:
            n = 8
            grid = {(i, j): geo.vertices.new((4.0 * i / n - 2, 4.0 * j / n - 2, 0.0)) for i in range(n + 1) for j in range(n + 1)}
            for i in range(n):
                for j in range(n):
                    geo.polygons.new((grid[i, j], grid[i + 1, j], grid[i + 1, j + 1], grid[i, j + 1]))
        material, gradient = setup(scene, param)
        if case == 'displace':
            material.channel('displace').set(0.1)
        constant_beneath(scene, material, effect, 0.3)
        report['cases'][case] = {'order': [i.name for i in scene.items('textureLayer')]}
        lx.eval('!render.animation {%s} openexr' % str(out / ('modo_' + case)))
    report['rendered'] = sorted(p.name for p in out.glob('modo_*'))
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
