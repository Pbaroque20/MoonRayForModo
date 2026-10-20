# python
"""Builds a small Shader Tree mask scene in a new scene of your own Modo, renders it with Modo, and saves it, for the
plugin's masks to be compared with. Run it from Modo: System > Run Script, and choose this file.

Four cubes in a row, lit by Modo's default light:
- first: its polygons given a material tag of their own (as Modo's Assign Material does), coloured red in that
  material's mask;
- second: a Part tag, coloured green in a Part mask;
- third: a Selection Set, coloured blue in a Selection Set mask;
- fourth: coloured yellow in a group mask that names the item itself (an item mask). How a script tells Modo which
  item a mask is for is tried several ways, and the first Modo holds is kept; report.json says which, and what the
  mask is linked to.
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
            detail = ' ptyp=%r ptag=%r item=%r' % (child.channel('ptyp').get(), child.channel('ptag').get(),
                                                   [i.name for i in child.itemGraph('shadeLoc').forward()])
        elif child.type == 'constant':
            detail = ' effect=%s colour=%s' % (child.channel('effect').get(), [round(child.channel('color.' + a).get(), 2) for a in 'RGB'])
        rows.append('  ' * depth + '%s (%s)%s' % (child.name, child.type, detail))
        rows += tree(child, depth + 1)
    return rows


try:
    lx.eval('scene.new')
    scene = modo.Scene()
    render = scene.renderItem
    for name, value in (('resX', 640), ('resY', 240), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    camera = scene.renderCamera
    lx.eval('select.item {%s} set' % camera.id)
    for axis, value in (('pos.X', 0), ('pos.Y', 0), ('pos.Z', 7), ('rot.X', 0), ('rot.Y', 0), ('rot.Z', 0)):
        lx.eval('transform.channel %s %s' % (axis, value))
    camera.channel('focalLen').set(0.05)
    left, middle, right, fourth = cube('Left', -1.8), cube('Middle', -0.6), cube('Right', 0.6), cube('Fourth', 1.8)

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
    # The fourth cube: a group mask naming the item. Each way of naming it is tried until the mask is linked to it.
    lx.eval('select.item {%s} set' % render.id)
    before = {m.id for m in scene.items('mask', superType=False)}
    if step('Item mask: add Group', 'shader.create mask'):
        item_mask = next(m for m in scene.items('mask', superType=False) if m.id not in before)
        item_mask.name = 'Item mask'
        masks['Item mask'] = item_mask
        linked = lambda: [i.id for i in item_mask.itemGraph('shadeLoc').forward()]
        report['item_link_tries'] = []

        def graph_link(source, target):
            source.itemGraph('shadeLoc') >> target.itemGraph('shadeLoc')

        tries = (('mask.setMesh by id', lambda: lx.eval('mask.setMesh {%s}' % fourth.id)),
                 ('mask.setMesh by name', lambda: lx.eval('mask.setMesh {%s}' % fourth.name)),
                 ('graph link mask to mesh', lambda: graph_link(item_mask, fourth)),
                 ('graph link mesh to mask', lambda: graph_link(fourth, item_mask)),
                 ('item.link mask to mesh', lambda: lx.eval('item.link shadeLoc {%s} {%s}' % (item_mask.id, fourth.id))),
                 ('item.link mesh to mask', lambda: lx.eval('item.link shadeLoc {%s} {%s}' % (fourth.id, item_mask.id))))
        for name, attempt in tries:
            lx.eval('select.item {%s} set' % item_mask.id)
            try:
                attempt()
                outcome = 'ran'
            except Exception as exc:
                outcome = 'failed: %s' % exc
            report['item_link_tries'].append([name, outcome, linked()])
            if fourth.id in linked():
                report['item_link'] = name
                break
        report['item_mask_linked_to'] = [i.name for i in item_mask.itemGraph('shadeLoc').forward()]
        report['item_mask_linked_from'] = [i.name for i in item_mask.itemGraph('shadeLoc').reverse()]
        lx.eval('select.typeFrom item')
    if material_mask is not None:
        colour_layer(material_mask, (1, 0, 0), 'Material mask')
    if 'Part mask' in masks:
        colour_layer(masks['Part mask'], (0, 1, 0), 'Part mask')
    if 'Set mask' in masks:
        colour_layer(masks['Set mask'], (0, 0, 1), 'Set mask')
    if 'Item mask' in masks:
        colour_layer(masks['Item mask'], (1, 1, 0), 'Item mask')

    report['shader_tree'] = tree(render)
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'mask_reference.lxo'))
    lx.eval('!render.animation {%s} openexr' % str(out / 'modo_masks'))
    report['rendered'] = [p.name for p in out.glob('modo_masks*')]
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
lx.out('Mask reference: ' + str(out / 'report.json'))
