# python
"""Isolated GUI test: Shader Tree group masks of each kind, against Modo's own render.

Three cubes in a row, lit by Modo's default light. Each is coloured by a Constant layer (Diffuse Color) in a group
mask of its own: the left one by an item mask (the mesh), the middle one by a Part tag, the right one by a Selection
Set, red, green and blue. A fourth mask, nested in the item mask and naming the part, would colour nothing (no
polygon is both). The scene is rendered by Modo (modo_masks.exr) and exported as the plugin writes it (masks.rdla);
tools/check_shader_masks.py renders that with MoonRay and reads each cube's colour in both."""
import json
import os
import pathlib
import traceback
import lx
import modo

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/shader-masks'
out.mkdir(parents=True, exist_ok=True)
for old in out.glob('*'):
    if old.is_file():
        old.unlink()
result = {'steps': []}
# Where layers go under the render item: MOONRAY_PROBE_PLACE=first puts them first in its list, else last.
PLACE = (lambda parent: 0) if os.environ.get('MOONRAY_PROBE_PLACE') == 'first' else (lambda parent: len(parent.children()))


def step(name, command):
    try:
        lx.eval(command)
        result['steps'].append([name, 'ok'])
    except Exception as exc:
        result['steps'].append([name, str(exc)])


def cube(name, x):
    lx.eval('item.create mesh')
    mesh = modo.Scene().selected[-1]
    mesh.name = name
    lx.eval('tool.set prim.cube on')
    # Every centre and size set: Modo keeps a tool's settings from earlier runs.
    for attribute, value in (('sizeX', .8), ('sizeY', .8), ('sizeZ', .8), ('cenX', x), ('cenY', 0), ('cenZ', 0)):
        lx.eval('tool.attr prim.cube %s %s' % (attribute, value))
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    return mesh


def mask(name, colour):
    """A group mask holding an image layer of one solid colour that sets Diffuse Color, under the render item."""
    from PySide2 import QtGui
    scene = modo.Scene()
    group = scene.addItem('mask')
    group.name = name
    picture = QtGui.QImage(8, 8, QtGui.QImage.Format_RGB32)
    picture.fill(QtGui.QColor(*[int(255 * c) for c in colour]))
    image = out / (name.replace(' ', '_') + '.png')
    picture.save(str(image))
    lx.eval('clip.addStill {%s}' % image)
    clip = scene.items('videoStill')[-1]
    lx.eval('item.create imageMap')
    layer = scene.selected[0]
    lx.eval('texture.parent {%s} %d item:{%s}' % (group.id, 0, layer.id))
    lx.eval('select.item {%s} set' % layer.id)
    lx.eval('texture.setIMap {%s}' % clip.id)
    layer.channel('effect').set('diffColor')
    locator = next(i for i in layer.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator')
    locator.channel('projType').set('uv')
    locator.channel('uvMap').set('Texture')
    shader_root = scene.renderItem
    lx.eval('texture.parent {%s} %d item:{%s}' % (shader_root.id, PLACE(shader_root), group.id))
    lx.eval('select.item {%s} set' % group.id)
    return group


try:
    from moonray_modo import scene_export
    scene = modo.Scene()
    render = scene.renderItem
    for name, value in (('resX', 240), ('resY', 120), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    camera = scene.renderCamera
    camera.position.set((0, 0, 5.0))
    camera.rotation.set((0, 0, 0), degrees=True)
    camera.channel('focalLen').set(0.05)
    lx.eval('select.item {%s} set' % camera.id)
    for axis, value in (('pos.X', 0), ('pos.Y', 0), ('pos.Z', 5), ('rot.X', 0), ('rot.Y', 0), ('rot.Z', 0)):
        lx.eval('transform.channel %s %s' % (axis, value))
    result['camera'] = {'position': list(camera.position.get()), 'rotation': list(camera.rotation.get(degrees=True)),
                        'parent': camera.parent.name if camera.parent else None}
    left, middle, right = cube('Left', -1.2), cube('Middle', 0.0), cube('Right', 1.2)
    # The middle cube's polygons tagged as a part, the right one's as a selection set.
    lx.eval('select.item {%s} set' % middle.id)
    lx.eval('select.typeFrom polygon')
    lx.eval('select.all')
    step('part tag', 'poly.setPart middlePart')
    lx.eval('select.item {%s} set' % right.id)
    lx.eval('select.all')
    step('selection set', 'select.editSet rightSet add')
    lx.eval('select.typeFrom item')
    if os.environ.get('MOONRAY_PROBE_PLAIN'):
        # No mask: a red Constant straight under the render item, at the top, as the masks are placed.
        plain = scene.addItem('constant')
        plain.channel('effect').set('diffColor')
        for axis, value in zip('RGB', (1, 0, 0)):
            plain.channel('color.' + axis).set(value)
        lx.eval('texture.parent {%s} %d item:{%s}' % (render.id, PLACE(render), plain.id))
    item_mask = mask('Item mask', (1, 0, 0))
    step('item mask', 'mask.setMesh {%s}' % left.id)
    mask('Part mask', (0, 1, 0))
    step('part type', 'mask.setPTagType Part')
    step('part tag name', 'mask.setPTag middlePart')
    mask('Set mask', (0, 0, 1))
    step('set type', 'mask.setPTagType "Selection Set"')
    step('set tag name', 'mask.setPTag rightSet')
    result['masks'] = [[m.name, m.channel('ptyp').get(), m.channel('ptag').get(), [t.name for t in m.itemGraph('shadeLoc').forward()]]
                       for m in scene.items('mask', superType=False)]
    def tree(item, depth=0):
        rows = []
        for child in item.children():
            rows.append('  ' * depth + '%s (%s)%s' % (child.name, child.type, ' effect=' + str(child.channel('effect').get()) if child.type == 'constant' else ''))
            rows += tree(child, depth + 1)
        return rows
    result['shader_tree'] = tree(scene.renderItem)
    result['constants'] = {layer.name: {name: layer.channel(name).get() for name in ('enable', 'render', 'opacity', 'effect', 'blend', 'invert', 'effect')}
                           for layer in scene.items('imageMap')}
    result['mask_channels'] = {m.name: {name: m.channel(name).get() for name in m.channelNames if not name.startswith(('pos', 'rot', 'scl'))}
                               for m in scene.items('mask', superType=False)}
    result['item_mask_links'] = {graph: [i.name for i in item_mask.itemGraph(graph).forward()] for graph in ('shadeLoc',)}
    lx.eval('!render.animation {%s} openexr' % str(out / 'modo_masks'))
    warnings = []
    scene_export.export({'path': out / 'masks.rdla', 'format': 'rdla', 'outputs': False, 'collect': False, 'frames': False}, warnings)
    result['warnings'] = warnings
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
