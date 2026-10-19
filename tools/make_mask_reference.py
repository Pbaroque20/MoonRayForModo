# python
"""Builds a small Shader Tree mask scene in a new scene of your own Modo, renders it with Modo, and saves it, for the
plugin's masks to be compared with. Run it from Modo: System > Run Script, and choose this file.

Three cubes in a row, lit by Modo's default light:
- left: its polygons given a material tag of their own (as Modo's Assign Material does), coloured red in that
  material's mask;
- middle: a Part tag, coloured green in a Part mask;
- right: a Selection Set, coloured blue in a Selection Set mask.
Each colour is a Constant layer (Diffuse Color) added inside its mask as Modo's Add Layer adds one there.

Written to MoonRayForModo/test-results/mask-reference: mask_reference.lxo (the scene), modo_masks.*.exr (Modo's render)
and report.json (what was built, and the Shader Tree's order as Modo holds it). Your current scene is left as it is;
the new scene can be closed afterwards without saving."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\mask-reference')
out.mkdir(parents=True, exist_ok=True)
report = {'steps': []}


def step(name, command):
    try:
        lx.eval(command)
        report['steps'].append([name, 'ok'])
        return True
    except Exception as exc:
        report['steps'].append([name, 'failed: %s' % exc])
        return False


def cube(name, x):
    lx.eval('item.create mesh')
    mesh = modo.Scene().selected[-1]
    mesh.name = name
    lx.eval('tool.set prim.cube on')
    # Every setting given: Modo keeps a tool's settings from earlier use.
    for attribute, value in (('cenX', x), ('cenY', 0), ('cenZ', 0), ('sizeX', .8), ('sizeY', .8), ('sizeZ', .8),
                             ('segmentsX', 1), ('segmentsY', 1), ('segmentsZ', 1), ('radius', 0)):
        try:
            lx.eval('tool.attr prim.cube %s %s' % (attribute, value))
        except Exception:
            pass
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    return mesh


def select_polygons_of(mesh):
    lx.eval('select.typeFrom item')
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('select.typeFrom polygon')
    lx.eval('select.all')


def colour_layer(mask, colour, label):
    """A Constant layer set to Diffuse Color, added inside the mask as Add Layer does with the mask selected."""
    lx.eval('select.typeFrom item')
    lx.eval('select.item {%s} set' % mask.id)
    before = {item.id for item in modo.Scene().items('constant')}
    if not step(label + ': add Constant', 'shader.create constant'):
        return None
    layer = next(item for item in modo.Scene().items('constant') if item.id not in before)
    layer.channel('effect').set('diffColor')
    for axis, value in zip('RGB', colour):
        layer.channel('color.' + axis).set(value)
    return layer


def tree(item, depth=0):
    rows = []
    for child in item.children():
        detail = ''
        if child.type == 'mask':
            detail = ' ptyp=%r ptag=%r' % (child.channel('ptyp').get(), child.channel('ptag').get())
        elif child.type == 'constant':
            detail = ' effect=%s colour=%s' % (child.channel('effect').get(), [round(child.channel('color.' + a).get(), 2) for a in 'RGB'])
        rows.append('  ' * depth + '%s (%s)%s' % (child.name, child.type, detail))
        rows += tree(child, depth + 1)
    return rows


try:
    lx.eval('scene.new')
    scene = modo.Scene()
    render = scene.renderItem
    for name, value in (('resX', 480), ('resY', 240), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    camera = scene.renderCamera
    lx.eval('select.item {%s} set' % camera.id)
    for axis, value in (('pos.X', 0), ('pos.Y', 0), ('pos.Z', 5), ('rot.X', 0), ('rot.Y', 0), ('rot.Z', 0)):
        lx.eval('transform.channel %s %s' % (axis, value))
    camera.channel('focalLen').set(0.05)
    left, middle, right = cube('Left', -1.2), cube('Middle', 0.0), cube('Right', 1.2)

    # Left: a material of its own, as Assign Material makes it (a mask by material tag, with its material inside).
    select_polygons_of(left)
    step('left material', 'poly.setMaterial LeftMaterial')
    # Middle: a Part tag. Right: a Selection Set.
    select_polygons_of(middle)
    step('middle part', 'poly.setPart MiddlePart')
    select_polygons_of(right)
    step('right selection set', 'select.editSet RightSet add')
    lx.eval('select.typeFrom item')

    # The material mask Assign Material made, and a Part and a Selection Set mask added as Add Layer > Group adds one.
    material_mask = next((m for m in scene.items('mask', superType=False) if m.channel('ptag').get() == 'LeftMaterial'), None)
    report['material_mask_made'] = material_mask is not None
    masks = {}
    for label, kind, tag in (('Part mask', 'Part', 'MiddlePart'), ('Set mask', 'Selection Set', 'RightSet')):
        lx.eval('select.item {%s} set' % render.id)
        before = {m.id for m in scene.items('mask', superType=False)}
        if step(label + ': add Group', 'shader.create mask'):
            mask = next(m for m in scene.items('mask', superType=False) if m.id not in before)
            mask.name = label
            lx.eval('select.item {%s} set' % mask.id)
            step(label + ': tag type', 'mask.setPTagType "%s"' % kind)
            step(label + ': tag', 'mask.setPTag %s' % tag)
            masks[label] = mask
    if material_mask is not None:
        colour_layer(material_mask, (1, 0, 0), 'Material mask')
    if 'Part mask' in masks:
        colour_layer(masks['Part mask'], (0, 1, 0), 'Part mask')
    if 'Set mask' in masks:
        colour_layer(masks['Set mask'], (0, 0, 1), 'Set mask')

    report['shader_tree'] = tree(render)
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'mask_reference.lxo'))
    lx.eval('!render.animation {%s} openexr' % str(out / 'modo_masks'))
    report['rendered'] = [p.name for p in out.glob('modo_masks*')]
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
lx.out('Mask reference: ' + str(out / 'report.json'))
