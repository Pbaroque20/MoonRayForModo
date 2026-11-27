# python
"""Command line: the test scene for Move Shader Tree Textures to MoonShine Graphs (shader_tree_scene), saved as
<out>/shader_tree.lxo with its images in <out>/images. A row of cubes on a floor, one material each, by polygon tag:
  Tags     colour, roughness and normal images (its colour image also on Shared);
  Shared   the Tags colour image, the same clip;
  SelSet   a material in a group mask for a polygon selection set, with a colour image;
  Nested   a material with a colour image, and a nested mask for a part of its polygons with another colour image;
  Udim     a colour image from a UDIM Image Folder;
  Repeat   a colour image repeated 3 x 2, moved and turned on its UVs;
  Blend    a colour image, with a second one over it at 50% Multiply, and one masked by its alpha.
MOONRAY_PROBE_OUT is the folder (default test-results/shader-tree in this checkout). Writes report.json there."""
import json
import os
import pathlib
import struct
import traceback
import zlib
import lx
import modo

out = pathlib.Path(os.environ.get('MOONRAY_PROBE_OUT') or r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\agent-a1b7a7f9b3e570cb4\test-results\shader-tree')
images = out / 'images'
images.mkdir(parents=True, exist_ok=True)
report = {}
BIG = int(os.environ.get('MOONRAY_PROBE_BIG', '0') or 0)


def step(text):
    with open(out / 'steps.txt', 'a') as handle:
        handle.write(text + '\n')


def png(path, size, pixel, alpha=False):
    """A PNG of size x size, pixel(x, y) giving (r, g, b[, a]) in 0..255: a 64-pixel tile of it, repeated where size
    is larger (MOONRAY_PROBE_BIG: 4096-pixel images, to see what they cost Modo's memory)."""
    size = BIG or size
    tile = 64
    rows = []
    for y in range(tile):
        row = bytearray()
        for x in range(tile):
            row.extend(bytes(pixel(x, y)[:4 if alpha else 3]))
        rows.append(b'\0' + bytes(row) * (size // tile))
    rows = b''.join(rows[y % tile] for y in range(size))

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    head = struct.pack('>IIBBBBB', size, size, 8, 6 if alpha else 2, 0, 0, 0)
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', head) + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))
    return path


def make_images():
    made = {}
    made['colour'] = png(images / 'colour.png', 64, lambda x, y: (230, 60, 40) if (x // 8 + y // 8) % 2 else (40, 90, 220))
    made['rough'] = png(images / 'rough.png', 64, lambda x, y: (x * 4, x * 4, x * 4))
    def normal(x, y):
        import math
        nx = math.sin(x / 64 * 6.2832 * 4) * .5
        n = (nx, 0, 1)
        length = (n[0] ** 2 + 1) ** .5
        return (int((n[0] / length * .5 + .5) * 255), 128, int((1 / length * .5 + .5) * 255))
    made['normal'] = png(images / 'normal.png', 64, normal)
    made['green'] = png(images / 'green.png', 64, lambda x, y: (40, 200, 60) if (x // 16) % 2 else (240, 240, 240))
    made['stripes'] = png(images / 'stripes.png', 64, lambda x, y: (250, 200, 30) if (y // 8) % 2 else (20, 20, 20))
    made['dots'] = png(images / 'dots.png', 64, lambda x, y: (255, 40, 200, 255 if ((x % 16 - 8) ** 2 + (y % 16 - 8) ** 2) < 30 else 0), alpha=True)
    made['grey'] = png(images / 'grey.png', 64, lambda x, y: (128 + y, 128 + y, 128 + y))
    made['udim1001'] = png(images / 'tile.1001.png', 64, lambda x, y: (200, 120, 30) if (x // 32 + y // 32) % 2 else (30, 160, 200))
    made['udim1002'] = png(images / 'tile.1002.png', 64, lambda x, y: (90, 30, 160))
    return made


def cube(name, x, material, size=0.8):
    lx.eval('item.create mesh {%s}' % name)
    mesh = next(i for i in modo.Scene().items('mesh') if i.name == name)
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('tool.set prim.cube on')
    for axis, value in (('cenX', x), ('cenY', size / 2), ('cenZ', 0), ('sizeX', size), ('sizeY', size), ('sizeZ', size)):
        lx.eval('tool.attr prim.cube %s %s' % (axis, value))
    lx.eval('tool.attr prim.cube segmentsX 2')
    lx.eval('tool.attr prim.cube segmentsY 2')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('select.type polygon')
    lx.eval('select.all')
    lx.eval('poly.setMaterial {%s}' % material)
    lx.eval('select.type item')
    return mesh


def mask_of(tag):
    return next(m for m in modo.Scene().items('mask', superType=False) if m.channel('ptag').get() == tag)


def material_in(mask):
    return next(i for i in mask.children() if i.type == 'advancedMaterial')


def clip(path):
    scene = modo.Scene()
    for held in scene.items('videoStill'):
        if pathlib.Path(held.channel('filename').get()) == pathlib.Path(path):
            return held
    before = {i.id for i in scene.items('videoStill')}
    lx.eval('clip.addStill {%s}' % path)
    return next(i for i in scene.items('videoStill') if i.id not in before)


def image_layer(under, effect, source, uv='Texture'):
    """An Image Map in the group under, at the top of it, laid on by the clip source (a clip, or a path), for effect."""
    scene = modo.Scene()
    if not hasattr(source, 'id'):
        source = clip(source)
    made = scene.addItem('imageMap', name='%s (Image)' % pathlib.Path(source.channel('filename').get()).stem)
    made.setParent(under, len(list(under.children())))
    link(made, source)
    made.channel('effect').set(effect)
    locator = next(i for i in made.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator')
    locator.channel('projType').set('uv')
    locator.channel('uvMap').set(uv)
    return made, locator, source


def link(layer, target):
    graph = lx.object.ItemGraph(lx.object.Scene(layer._item.Context()).GraphLookup('shadeLoc'))
    graph.AddLink(layer._item, target._item)


def unlink(layer, target):
    graph = lx.object.ItemGraph(lx.object.Scene(layer._item.Context()).GraphLookup('shadeLoc'))
    graph.DeleteLink(layer._item, target._item)


def tree(item, depth=0):
    rows = []
    for child in reversed(list(item.children())):
        detail = ''
        try:
            detail = ' effect=%s on=%s' % (child.channel('effect').get(), child.channel('enable').get())
        except Exception:
            pass
        try:
            detail += ' ptyp=%s ptag=%s' % (child.channel('ptyp').get(), child.channel('ptag').get())
        except Exception:
            pass
        rows.append('  ' * depth + '%s (%s)%s' % (child.name, child.type, detail))
        rows += tree(child, depth + 1)
    return rows


try:
    (out / 'steps.txt').write_text('')
    made = make_images()
    step('images')
    lx.eval('scene.new')
    scene = modo.Scene()
    render = scene.renderItem
    for name, value in (('resX', 1260), ('resY', 300), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    floor = scene.addMesh('Floor')
    with floor.geometry as geo:
        points = [geo.vertices.new(p) for p in ((-8, 0, -4), (-8, 0, 4), (8, 0, 4), (8, 0, -4))]
        geo.polygons.new(points)
    names = ['Tags', 'Shared', 'SelSet', 'Nested', 'Udim', 'Repeat', 'Blend']
    meshes = {}
    for index, name in enumerate(names):
        meshes[name] = cube(name, -3.6 + 1.2 * index, name)
    camera = scene.renderCamera
    camera.position.set((0.0, 2.6, 11.0))
    camera.rotation.set((-0.25, 0.0, 0.0))
    step('# Tags: colour, roughness, normal.')
    # Tags: colour, roughness, normal.
    tags = mask_of('Tags')
    _, _, colour_clip = image_layer(tags, 'diffColor', made['colour'])
    image_layer(tags, 'rough', made['rough'])
    normal, _, _ = image_layer(tags, 'normal', made['normal'])
    material_in(tags).channel('rough').set(0.3)
    step('# Shared: the same clip as the Tags colour.')
    # Shared: the same clip as the Tags colour.
    image_layer(mask_of('Shared'), 'diffColor', colour_clip)
    step("# SelSet: the cube's polygons in a selection set, and a group mask for it holding a material and an image.")
    # SelSet: the cube's polygons in a selection set, and a group mask for it holding a material and an image.
    lx.eval('select.item {%s} set' % meshes['SelSet'].id)
    lx.eval('select.type polygon')
    lx.eval('select.all')
    lx.eval('select.editSet SetX add')
    lx.eval('select.type item')
    selset = mask_of('SelSet')
    selset.channel('ptyp').set('Selection Set')
    selset.channel('ptag').set('SetX')
    report['selset_mask'] = (selset.channel('ptyp').get(), selset.channel('ptag').get())
    image_layer(selset, 'diffColor', made['green'])
    step("# Nested: half its polygons a part, and a mask for that part inside the material's group.")
    # Nested: half its polygons a part, and a mask for that part inside the material's group.
    with meshes['Nested'].geometry as geo:
        top = [p for p in geo.polygons if sum(v.position[1] for v in p.vertices) / len(p.vertices) > .45]
        for polygon in top:
            polygon.setTag(lx.symbol.i_POLYTAG_PART, 'PartTop')
    nested = mask_of('Nested')
    image_layer(nested, 'diffColor', made['stripes'])
    inner = scene.addItem('mask')
    inner.setParent(nested, len(list(nested.children())))
    inner.channel('ptyp').set('Part')
    inner.channel('ptag').set('PartTop')
    inner.name = 'PartTop mask'
    image_layer(inner, 'diffColor', made['green'])
    report['nested_mask'] = (inner.channel('ptyp').get(), inner.channel('ptag').get(), len(top))
    step('# Udim: an Image Folder of two tiles, Use UDIM on.')
    # Udim: an Image Folder of two tiles, Use UDIM on.
    udim, locator, first = image_layer(mask_of('Udim'), 'diffColor', made['udim1001'])
    try:
        folder = scene.addItem('imageFolder')
        folder.name = 'tile set'
        second = clip(made['udim1002'])
        for held, number in ((first, 1001), (second, 1002)):
            held.setParent(folder)
            held.channel('udim').set(number)
        unlink(udim, first)
        link(udim, folder)
        locator.channel('useUDIM').set(1)
        report['udim_links'] = [(i.name, i.type) for i in udim.itemGraph('shadeLoc').forward()]
    except Exception:
        report['udim_error'] = traceback.format_exc()
    step('# Repeat: 3 x 2, moved and turned.')
    # Repeat: 3 x 2, moved and turned.
    _, locator, _ = image_layer(mask_of('Repeat'), 'diffColor', made['stripes'])
    locator.channel('wrapU').set(3)
    locator.channel('wrapV').set(2)
    locator.channel('m02').set(.25)
    locator.channel('m12').set(.1)
    locator.channel('uvRotation').set(0.3)
    step('# Blend: a colour, a grey at 50% Multiply over it, and dots masked by their alpha.')
    # Blend: a colour, a grey at 50% Multiply over it, and dots masked by their alpha.
    blend = mask_of('Blend')
    image_layer(blend, 'diffColor', made['green'])
    grey, _, _ = image_layer(blend, 'diffColor', made['grey'])
    grey.channel('opacity').set(.5)
    grey.channel('blend').set('multiply')
    image_layer(blend, 'diffColor', made['dots'])
    report['shader_tree'] = tree(render)
    report['clips'] = [(c.name, c.channel('filename').get()) for c in scene.items('videoStill')]
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'shader_tree.lxo'))
    report['saved'] = str(out / 'shader_tree.lxo')
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
