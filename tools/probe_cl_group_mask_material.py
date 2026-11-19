# python
"""Command line: a scene for the Group Mask report (a tester's tyre: a material group whose Group Mask image has soft
edges showed a white border in MoonRay where Modo blends into the material underneath). Three cubes on a floor, each
with its own material: a black Material, and above it a group holding a purple Material, the group masked by a
Constant at 0.5 (Half), by a Noise (Noise), and by a Constant at 1 (Full). Saved as
test-results/group-mask-material/group_mask_material.lxo and rendered by Modo (modo.*.exr) and exported as the plugin writes it (group_mask_material.rdla), with the Shader
Tree as Modo holds it in report.json."""
import json
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\group-mask-material' + (('-' + os.environ['PROBE_UNDER']) if os.environ.get('PROBE_UNDER') else ''))
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


def made(kind, under, before):
    return next(i for i in modo.Scene().iterItems() if i.id not in before and i.type == kind)


def create(kind, under):
    scene = modo.Scene()
    before = {i.id for i in scene.iterItems()}
    lx.eval('select.item {%s} set' % under.id)
    lx.eval('shader.create %s' % kind)
    return made(kind, under, before)


def colour(item, rgb):
    for axis, value in zip('RGB', rgb):
        item.channel('diffCol.' + axis).set(value)


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
    for name, value in (('resX', 768), ('resY', 320), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    floor = scene.addMesh('Floor')
    with floor.geometry as geo:
        points = [geo.vertices.new(p) for p in ((-5, 0, -4), (-5, 0, 4), (5, 0, 4), (5, 0, -4))]
        geo.polygons.new(points)
    camera = scene.renderCamera
    camera.position.set((0.0, 1.8, 5.0))
    camera.rotation.set((-0.3, 0.0, 0.0))
    for name, x, mask_kind in (('Half', -1.6, 'half'), ('Noise', 0.0, 'noise'), ('Full', 1.6, 'full')):
        cube(name, x, name + 'Material')
        group = mask_of(name + 'Material')
        # Underneath: a black Material; with PROBE_UNDER=dim, a white one at 5% Diffuse Amount (dark as the tyre's
        # rubber, its colour and amount far apart: where a mask is partly on, the two blended apart and multiplied
        # come out lighter than either side).
        black = create('advancedMaterial', group)
        black.name = name + ' Black'
        if os.environ.get('PROBE_UNDER') == 'dim':
            colour(black, (1.0, 1.0, 1.0))
            black.channel('diffAmt').set(0.05)
        else:
            colour(black, (0.02, 0.02, 0.02))
        # Above it: a group masked as asked, holding a purple Material.
        before = {i.id for i in scene.iterItems()}
        lx.eval('select.item {%s} set' % group.id)
        lx.eval('shader.create mask')
        inner = made('mask', group, before)
        inner.name = name + ' Group'
        purple = create('advancedMaterial', inner)
        purple.name = name + ' Purple'
        colour(purple, (0.6, 0.0, 0.9))
        if os.environ.get('PROBE_UNDER') == 'glow':
            # The tyre's case: the material underneath has Modo's own Luminous Color, white at Intensity 0; the group's
            # has black at Intensity 1 (as the car's imported materials do). Neither glows; Modo draws no glow between.
            for axis in 'RGB':
                black.channel('lumiCol.' + axis).set(1.0)
                purple.channel('lumiCol.' + axis).set(0.0)
            black.channel('radiance').set(0.0)
            purple.channel('radiance').set(1.0)
        if mask_kind == 'noise':
            masking = create('noise', inner)
        else:
            masking = create('constant', inner)
            value = 0.5 if mask_kind == 'half' else 1.0
            for axis in 'RGB':
                masking.channel('color.' + axis).set(value)
        masking.channel('effect').set('groupMask')
    report['shader_tree'] = tree(render)
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'group_mask_material.lxo'))
    lx.eval('!render.animation {%s} openexr' % str(out / 'modo'))
    # As the plugin writes it for MoonRay (tools/check_group_mask_material.py renders it).
    from moonray_modo import scene_export
    warnings = []
    scene_export.export({'path': out / 'group_mask_material.rdla', 'format': 'rdla', 'outputs': False, 'collect': False,
                         'frames': False}, warnings)
    report['export_warnings'] = [str(w) for w in warnings]
    report['rendered'] = [p.name for p in out.glob('modo*')]
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
