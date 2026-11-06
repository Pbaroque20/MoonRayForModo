# python
"""Command line: a scene for checking Layer Masks against Modo. Two cubes side by side on a floor, lit by Modo's
default light and environment. The left cube's material has a red Constant layer with a Checker above it as its
Layer Mask (red where the checker is white); the right cube's has a blue Constant inside a group whose Group Mask is
a Checker, for comparison. Saved as test-results/layer-mask/layer_mask.lxo and rendered by Modo (modo.*.exr), with
the Shader Tree as Modo holds it in report.json."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\layer-mask')
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
    return mesh


def mask_of(material_name):
    return next(m for m in modo.Scene().items('mask', superType=False) if m.channel('ptag').get() == material_name)


def layer(kind, under, effect, color=None):
    """A layer of kind made inside the group under, set to effect (and colour)."""
    scene = modo.Scene()
    before = {i.id for i in scene.iterItems()}
    lx.eval('select.item {%s} set' % under.id)
    lx.eval('shader.create %s' % kind)
    made = next(i for i in scene.iterItems() if i.id not in before and i.type == kind)
    made.channel('effect').set(effect)
    if kind == 'checker':
        # Squares of 0.3, turned so that they cross every face of the cubes.
        for locator in made.itemGraph('shadeLoc').forward():
            report.setdefault('locator_channels', sorted(c.name for c in locator.channels())[:80])
            for name, value in (('scl.X', .3), ('scl.Y', .3), ('scl.Z', .3), ('rot.X', 30), ('rot.Y', 30)):
                try:
                    lx.eval('select.item {%s} set' % locator.id)
                    lx.eval('transform.channel %s %s' % (name, value))
                except Exception as exc:
                    report.setdefault('locator_errors', []).append('%s: %s' % (name, exc))
    if color is not None:
        for axis, value in zip('RGB', color):
            made.channel('color.' + axis).set(value)
    return made


def tree(item, depth=0):
    rows = []
    for child in item.children():
        detail = ''
        try:
            detail = ' effect=%s' % child.channel('effect').get()
        except Exception:
            pass
        rows.append('  ' * depth + '%s (%s)%s' % (child.name, child.type, detail))
        rows += tree(child, depth + 1)
    return rows


try:
    lx.eval('scene.new')
    scene = modo.Scene()
    render = scene.renderItem
    for name, value in (('resX', 640), ('resY', 320), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    floor = scene.addMesh('Floor')
    with floor.geometry as geo:
        points = [geo.vertices.new(p) for p in ((-4, 0, -4), (-4, 0, 4), (4, 0, 4), (4, 0, -4))]
        geo.polygons.new(points)
    cube('Left', -0.8, 'LeftMaterial')
    cube('Right', 0.8, 'RightMaterial')
    camera = scene.renderCamera
    camera.position.set((0.0, 1.6, 4.0))
    camera.rotation.set((-0.3, 0.0, 0.0))
    # Left: a red Constant, and above it a Checker as its Layer Mask.
    left = mask_of('LeftMaterial')
    # The mask first, then the red above it: a Layer Mask masks the layer directly above it.
    checker = layer('checker', left, 'layerMask')
    red = layer('constant', left, 'diffColor', (1.0, 0.0, 0.0))
    # Right: a blue Constant in a group masked by a Checker (Group Mask).
    right = mask_of('RightMaterial')
    blue = layer('constant', right, 'diffColor', (0.0, 0.0, 1.0))
    lx.eval('select.item {%s} set' % blue.id)
    before = {i.id for i in scene.iterItems()}
    lx.eval('shader.group')
    group = next((i for i in scene.iterItems() if i.id not in before and i.type == 'mask'), None)
    report['group_made'] = group is not None
    if group is not None:
        layer('checker', group, 'groupMask')
    report['shader_tree'] = tree(render)
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'layer_mask.lxo'))
    lx.eval('!render.animation {%s} openexr' % str(out / 'modo'))
    report['rendered'] = [p.name for p in out.glob('modo*')]
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
