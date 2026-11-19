# python
"""Command line: what Modo shows under a Group that holds a material, where the Group's mask is off. Three cubes, each
in its own material group, bottom to top: its grey Material, a white Constant on Diffuse Color (as the tyre's
Dirt_for_tread), and a Group holding a dark Material, the Group masked by a Constant at 0 (Off), 0.5 (Half) or 1 (Full).
Rendered by Modo (modo.*.exr) and exported as the plugin writes it (group_override.rdla), into
test-results/group-override; report.json has the Shader Tree."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\group-override')
# PROBE_PLAIN: the reference, each cube a plain material holding the blended values (group-override-plain).
PLAIN = bool(__import__('os').environ.get('PROBE_PLAIN'))
if PLAIN:
    out = out.parent / 'group-override-plain'
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


def made(kind, before):
    return next(i for i in modo.Scene().iterItems() if i.id not in before and i.type == kind)


def create(kind, under):
    before = {i.id for i in modo.Scene().iterItems()}
    lx.eval('select.item {%s} set' % under.id)
    lx.eval('shader.create %s' % kind)
    return made(kind, before)


def tree(item, depth=0):
    rows = []
    for child in reversed(list(item.children())):
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
    for name, value in (('resX', 768), ('resY', 320), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    floor = scene.addMesh('Floor')
    with floor.geometry as geo:
        points = [geo.vertices.new(p) for p in ((-5, 0, -4), (-5, 0, 4), (5, 0, 4), (5, 0, -4))]
        geo.polygons.new(points)
    camera = scene.renderCamera
    camera.position.set((0.0, 1.8, 5.0))
    camera.rotation.set((-0.3, 0.0, 0.0))
    for name, x, amount in (('Off', -1.6, 0.0), ('Half', 0.0, 0.5), ('Full', 1.6, 1.0)):
        cube(name, x, name + 'Material')
        group = next(m for m in scene.items('mask', superType=False) if m.channel('ptag').get() == name + 'Material')
        base = next(c for c in group.children() if c.type == 'advancedMaterial')
        for axis in 'RGB':
            base.channel('diffCol.' + axis).set(0.5)
        if PLAIN:
            # The reference: no layers, no Group, the material itself holding what the mask blends to, Modo's way
            # (colour and amount each blended): white under, 0.02 at the dark material's 0.8 amount.
            under = base.channel('diffAmt').get()
            colour = 1.0 + (0.02 - 1.0) * amount
            for axis in 'RGB':
                base.channel('diffCol.' + axis).set(colour)
            base.channel('diffAmt').set(under + (0.8 - under) * amount)
            report.setdefault('plain', {})[name] = {'diffCol': colour, 'diffAmt': base.channel('diffAmt').get()}
            continue
        # The "dirt": a white Constant on Diffuse Color, over the grey material.
        dirt = create('constant', group)
        dirt.name = name + ' White Layer'
        for axis in 'RGB':
            dirt.channel('color.' + axis).set(1.0)
        dirt.channel('effect').set('diffColor')
        # On top: a Group holding a dark Material, masked by a Constant.
        before = {i.id for i in scene.iterItems()}
        lx.eval('select.item {%s} set' % group.id)
        lx.eval('shader.create mask')
        inner = made('mask', before)
        inner.name = name + ' Group'
        dark = create('advancedMaterial', inner)
        dark.name = name + ' Dark'
        for axis in 'RGB':
            dark.channel('diffCol.' + axis).set(0.02)
        masking = create('constant', inner)
        for axis in 'RGB':
            masking.channel('color.' + axis).set(amount)
        # A Group Mask is one number: the Constant's Value, not its colour.
        masking.channel('value').set(amount)
        masking.channel('effect').set('groupMask')
        report.setdefault('mask_channels', {})[name] = {c: masking.channel(c).get() for c in ('value', 'color.R')}
    report['shader_tree'] = tree(render)
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'group_override.lxo'))
    lx.eval('!render.animation {%s} openexr' % str(out / 'modo'))
    report['rendered'] = [p.name for p in out.glob('modo*')]
    from moonray_modo import scene_export
    warnings = []
    scene_export.export({'path': out / 'group_override.rdla', 'format': 'rdla', 'outputs': False, 'collect': False,
                         'frames': False}, warnings)
    report['export_warnings'] = [str(w) for w in warnings]
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
