# python
"""Command line: whether a Material item covers a texture layer beneath it in Modo's render (the Group Mask report:
on the car's tyre a purple Material above the tread's dirt image left the dirt showing). Four cubes, each with its own
material group holding, bottom to top: a black Material; a white Constant on Diffuse Color; then
  A: nothing more (white expected),
  B: a purple Material,
  C: a group holding a purple Material,
  D: a group holding a purple Material and, above it, a yellow Constant on Diffuse Color.
Saved as test-results/material-over-texture/scene.lxo and rendered by Modo (modo.*.exr); report.json has the tree."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\material-over-texture')
out.mkdir(parents=True, exist_ok=True)
report = {}


def cube(name, x, material):
    lx.eval('item.create mesh {%s}' % name)
    mesh = next(i for i in modo.Scene().items('mesh') if i.name == name)
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('tool.set prim.cube on')
    for axis, value in (('cenX', x), ('cenY', 0.5), ('cenZ', 0), ('sizeX', 1), ('sizeY', 1), ('sizeZ', 1)):
        lx.eval('tool.attr prim.cube %s %s' % (axis, value))
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('select.type polygon')
    lx.eval('select.all')
    lx.eval('poly.setMaterial {%s}' % material)
    lx.eval('select.type item')


def create(kind, under):
    scene = modo.Scene()
    before = {i.id for i in scene.iterItems()}
    lx.eval('select.item {%s} set' % under.id)
    lx.eval('shader.create %s' % kind)
    return next(i for i in scene.iterItems() if i.id not in before and i.type == kind)


def colour(item, rgb, name='diffCol'):
    for axis, value in zip('RGB', rgb):
        item.channel('%s.%s' % (name, axis)).set(value)


def tree(item, depth=0):
    rows = []
    for child in reversed(list(item.children())):
        rows.append('  ' * depth + '%s (%s)' % (child.name, child.type))
        rows += tree(child, depth + 1)
    return rows


try:
    lx.eval('scene.new')
    scene = modo.Scene()
    render = scene.renderItem
    for name, value in (('resX', 800), ('resY', 240), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    floor = scene.addMesh('Floor')
    with floor.geometry as geo:
        points = [geo.vertices.new(p) for p in ((-6, 0, -4), (-6, 0, 4), (6, 0, 4), (6, 0, -4))]
        geo.polygons.new(points)
    camera = scene.renderCamera
    camera.position.set((0.0, 1.8, 6.5))
    camera.rotation.set((-0.25, 0.0, 0.0))
    for name, x in (('A', -2.4), ('B', -0.8), ('C', 0.8), ('D', 2.4)):
        cube(name, x, name + 'Material')
        group = next(m for m in scene.items('mask', superType=False) if m.channel('ptag').get() == name + 'Material')
        for child in list(group.children()):
            if child.type == 'advancedMaterial':
                colour(child, (0.02, 0.02, 0.02))
                child.name = name + ' Black'
        white = create('constant', group)
        white.channel('effect').set('diffColor')
        colour(white, (1, 1, 1), 'color')
        if name == 'B':
            purple = create('advancedMaterial', group)
            colour(purple, (0.6, 0.0, 0.9))
        if name in ('C', 'D'):
            inner = create('mask', group)
            inner.name = name + ' Group'
            purple = create('advancedMaterial', inner)
            colour(purple, (0.6, 0.0, 0.9))
            if name == 'D':
                yellow = create('constant', inner)
                yellow.channel('effect').set('diffColor')
                colour(yellow, (1, 0.9, 0), 'color')
        report[name] = tree(group)
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'scene.lxo'))
    lx.eval('!render.animation {%s} openexr' % str(out / 'modo'))
    report['rendered'] = [p.name for p in out.glob('modo*')]
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
