# python
"""Command-line test: whether bumps from lower in the Shader Tree show through a Material that covers a surface from a
group mask. Three cubes in a row, lit from the side; a group over every surface holds an image bump; above it:
- Member: the cube in a Group of the Groups list; a group masked to that Group holds a blue Material;
- Tagged: the cube's polygons tagged Tagged; a group for that material tag holds a red Material;
- Other: in neither (the bump alone, on the Base Material).
Writes test-results/item-mask-bump: bump.lxo, modo.*.exr (Modo's render), bump.rdla (the plugin's export, for
tools/check_item_mask_bump.py) and report.json."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\item-mask-bump')
out.mkdir(parents=True, exist_ok=True)
for old in out.glob('*'):
    old.unlink()
report = {'steps': []}


def step(name, command):
    # Written before each step too: a step that takes Modo down leaves its name.
    report['steps'].append([name, 'started'])
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
    try:
        lx.eval(command)
        report['steps'][-1][1] = 'ok'
        return True
    except Exception as exc:
        report['steps'][-1][1] = 'failed: %s' % exc
        return False


def cube(name, x):
    lx.eval('item.create mesh')
    mesh = modo.Scene().selected[-1]
    mesh.name = name
    lx.eval('tool.set prim.cube on')
    for attribute, value in (('cenX', x), ('cenY', 0), ('cenZ', 0), ('sizeX', 1.6), ('sizeY', 1.6), ('sizeZ', 1.6),
                             ('segmentsX', 48), ('segmentsY', 48), ('segmentsZ', 48), ('radius', 0)):
        try:
            lx.eval('tool.attr prim.cube %s %s' % (attribute, value))
        except Exception:
            pass
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    return mesh


def group_mask(scene, render, name, kind, tag):
    lx.eval('select.item {%s} set' % render.id)
    before = {m.id for m in scene.items('mask', superType=False)}
    step(name + ': add Group', 'shader.create mask')
    mask = next(m for m in scene.items('mask', superType=False) if m.id not in before)
    mask.name = name
    lx.eval('select.item {%s} set' % mask.id)
    step(name + ': tag type', 'mask.setPTagType %s' % kind)
    mask.channel('ptag').set(tag)
    return mask


def material_in(scene, mask, name, colour):
    lx.eval('select.item {%s} set' % mask.id)
    before = {m.id for m in scene.items('advancedMaterial', superType=False)}
    step(name + ': add Material', 'shader.create advancedMaterial')
    material = next(m for m in scene.items('advancedMaterial', superType=False) if m.id not in before)
    material.name = name
    material.channel('diffCol').set(colour)
    material.channel('diffAmt').set(1.0)
    return material


try:
    lx.eval('scene.new')
    scene = modo.Scene()
    render = scene.renderItem
    for name, value in (('resX', 900), ('resY', 300), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    camera = scene.renderCamera
    modo.LocatorSuperType(camera).position.set((0, 0, 12))
    modo.LocatorSuperType(camera).rotation.set((0, 0, 0))
    camera.channel('focalLen').set(0.05)
    member, tagged, other = cube('Member', -2.4), cube('Tagged', 0), cube('Other', 2.4)
    lx.eval('select.typeFrom item')
    # Light from the side, for a bump to show.
    light = next(iter(scene.items('sunLight', superType=False)), None) or scene.addItem('sunLight')
    modo.LocatorSuperType(light).rotation.set((0, 1.2, 0))
    holder = scene.addGroup('Members')
    holder.addItems([member])
    # The bump, over every surface: the first group made, the lowest.
    everything = group_mask(scene, render, 'Bumps', 'Material', '')
    # As a material's group is laid out in Modo: its Material, and its bump layer above it in the same group.
    material_in(scene, everything, 'Bumpy material', (.6, .6, .6))
    # The bump is an image on the cubes' UVs, stripes 16 pixels wide, as a real material's bump is an image (a Checker
    # is baked at polygon corners by the plugin and hardly shows). shader.create imageMap takes modo_cl down: the layer
    # is added as an item, and its image set by Modo's own command.
    import struct
    import zlib
    stripes = out / 'stripes.png'
    rows = b''.join(b'\x00' + bytes(255 if (x // 16) % 2 else 0 for x in range(256)) for _ in range(256))
    chunk = lambda kind, data: struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    stripes.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 256, 256, 8, 0, 0, 0, 0))
                        + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))
    step('add clip', 'clip.addStill {%s}' % stripes)
    clip = next(iter(scene.items('videoStill', superType=False)), None)
    bump = scene.addItem('imageMap', name='Stripes')
    bump.setParent(everything, len(everything.children()))
    lx.eval('select.item {%s} set' % bump.id)
    if clip is not None:
        step('image', 'texture.setIMap {%s}' % clip.name)
    bump.channel('effect').set('bump')
    for locator in bump.itemGraph('shadeLoc').forward():
        if locator.type == 'txtrLocator':
            locator.channel('projType').set('uv')
            locator.channel('uvMap').set('Texture')
    report['uv maps'] = [vmap.name for vmap in member.geometry.vmaps.uvMaps]
    report['bump linked'] = [(i.name, i.type) for i in bump.itemGraph('shadeLoc').forward()]
    report['group order'] = [c.name for c in everything.children()]
    # Above it, the group masked to the Group, and the group for the material tag, made by Modo's own commands.
    item_mask = group_mask(scene, render, 'Member mask', 'Material', '')
    lx.eval('select.item {%s} set' % item_mask.id)
    step('link', 'mask.setMesh {%s}' % holder.name)
    material_in(scene, item_mask, 'Member material', (0, 0, 1))
    tag_mask = group_mask(scene, render, 'Tagged mask', 'Material', 'Tagged')
    material_in(scene, tag_mask, 'Tagged material', (1, 0, 0))
    lx.eval('select.item {%s} set' % tagged.id)
    lx.eval('select.typeFrom polygon')
    lx.eval('select.all')
    # The polygons tagged as Polygon > Set Material tags them, the tag's group kept as it was made here.
    step('tag', 'poly.setMaterial Tagged')
    lx.eval('select.typeFrom item')
    # One bump strength for every material, so that a bump showing through shows as strongly as on the Base Material.
    for material in scene.items('advancedMaterial', superType=False):
        material.channel('bumpAmp').set(0.05)

    def tree(item, depth=0):
        rows = []
        for child in item.children():
            rows.append('  ' * depth + '%s (%s)' % (child.name, child.type))
            rows += tree(child, depth + 1)
        return rows
    report['tree'] = tree(render)
    report['tagged masks'] = [m.name for m in scene.items('mask', superType=False) if m.channel('ptag').get() == 'Tagged']
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'bump.lxo'))
    lx.eval('!render.animation {%s} openexr' % str(out / 'modo'))
    from moonray_modo import scene_export
    warnings = []
    scene_export.export({'path': out / 'bump.rdla', 'format': 'rdla', 'outputs': False, 'collect': False, 'frames': False}, warnings)
    report['warnings'] = warnings
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
