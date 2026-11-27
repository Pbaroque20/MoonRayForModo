# python
"""Command line: the second test scene for Shader Tree -> MoonShine (shader_tree_scene), what the first
(probe_cl_shader_tree_scene.py) left in the Shader Tree: a grid of cubes, one material each, by polygon tag:
  row 1  an image laid on by a Planar, Cubic, Spherical, Cylindrical and Front projection;
  row 2  stripes at 70% over a grey image by Overlay, Soft Light, Hard Light, Color Dodge and Color Burn;
  row 3  Noise, Cellular, Wood, Checker and Weave procedurals through the object (Solid);
  row 4  a Specular Color image, a Subsurface Color image, a Displacement image under a colour image, a Normal image
         with a Bump image over it at 50%, and a Diffuse Amount image.
Images from probe_cl_shader_tree_scene.py's folder (run it first), saved as <out>/round2.lxo. MOONRAY_PROBE_OUT is the
folder (default test-results/shader-tree-round2 in this checkout); MOONRAY_PROBE_IMAGES the images' folder."""
import json
import os
import pathlib
import struct
import traceback
import zlib
import lx
import modo

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\agent-a1b7a7f9b3e570cb4\test-results')
out = pathlib.Path(os.environ.get('MOONRAY_PROBE_OUT') or root / 'shader-tree-round2')
images = pathlib.Path(os.environ.get('MOONRAY_PROBE_IMAGES') or root / 'shader-tree' / 'images')
out.mkdir(parents=True, exist_ok=True)
report = {}


def png(path, size, pixel):
    rows = b''.join(b'\0' + bytes(v for x in range(size) for v in pixel(x, y)) for y in range(size))

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0))
                     + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))
    return path


def cube(name, x, y, material, size=0.8):
    lx.eval('item.create mesh {%s}' % name)
    mesh = next(i for i in modo.Scene().items('mesh') if i.name == name)
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('tool.set prim.cube on')
    for axis, value in (('cenX', x), ('cenY', y), ('cenZ', 0), ('sizeX', size), ('sizeY', size), ('sizeZ', size)):
        lx.eval('tool.attr prim.cube %s %s' % (axis, value))
    for axis in 'XYZ':
        lx.eval('tool.attr prim.cube segments%s 6' % axis)
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


def link(layer, target):
    graph = lx.object.ItemGraph(lx.object.Scene(layer._item.Context()).GraphLookup('shadeLoc'))
    graph.AddLink(layer._item, target._item)


def locator_of(layer):
    return next(i for i in layer.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator')


def layer(under, kind, effect, source=None, projection='uv', name=None):
    scene = modo.Scene()
    made = scene.addItem(kind, name=name or '%s %s' % (kind, effect))
    made.setParent(under, len(list(under.children())))
    if source is not None:
        link(made, clip(source))
    made.channel('effect').set(effect)
    locator = locator_of(made)
    locator.channel('projType').set(projection)
    if projection == 'uv':
        locator.channel('uvMap').set('Texture')
    return made, locator


def place(locator, position, scale, rotation=(0, 0, 0)):
    lx.eval('select.item {%s} set' % locator.id)
    for axis, value in zip('XYZ', position):
        lx.eval('transform.channel pos.%s %s' % (axis, value))
    for axis, value in zip('XYZ', scale):
        lx.eval('transform.channel scl.%s %s' % (axis, value))
    for axis, value in zip('XYZ', rotation):
        lx.eval('transform.channel rot.%s %s' % (axis, value))


def colour(item, name, value):
    for axis, part in zip('RGB', value):
        try:
            item.channel('%s.%s' % (name, axis)).set(part)
        except Exception as exc:
            report.setdefault('colour errors', []).append('%s %s: %s' % (item.name, name, exc))


try:
    height = png(images / 'height.png', 64, lambda x, y: [int(127 + 120 * ((x // 8 + y // 8) % 2 * 2 - 1) * .5)] * 3)
    lx.eval('scene.new')
    scene = modo.Scene()
    render = scene.renderItem
    for name, value in (('resX', 1280), ('resY', 720), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    rows = [['Planar', 'Cubic', 'Spherical', 'Cylindrical', 'Front'],
            ['Overlay', 'SoftLight', 'HardLight', 'ColorDodge', 'ColorBurn'],
            ['Noise', 'Cellular', 'Wood', 'Checker', 'Weave'],
            ['Specular', 'Subsurface', 'Displace', 'NormalBump', 'DiffAmount']]
    meshes = {}
    for r, names in enumerate(rows):
        for c, name in enumerate(names):
            meshes[name] = cube(name, -3.2 + 1.6 * c, 4.2 - 1.3 * r, name, size=1.0)
    camera = scene.renderCamera
    camera.position.set((0.0, 2.3, 10.5))
    camera.rotation.set((0.0, 0.0, 0.0))
    # Row 1: projections.
    for c, (name, kind) in enumerate(zip(rows[0], ('planar', 'cubic', 'spherical', 'cylindrical', 'front'))):
        made, locator = layer(mask_of(name), 'imageMap', 'diffColor', images / 'colour.png', kind)
        if kind != 'front':
            place(locator, (-3.2 + 1.6 * c, 4.2, 0), (.45, .45, .45), (20, 30, 0))
            locator.channel('projAxis').set(1 if kind in ('planar', 'cylindrical') else 2)
    # Row 2: blend modes.
    for name, blend in zip(rows[1], ('overlay', 'softlight', 'hardlight', 'colordodge', 'colorburn')):
        layer(mask_of(name), 'imageMap', 'diffColor', images / 'colour.png')
        over, _ = layer(mask_of(name), 'imageMap', 'diffColor', images / 'stripes.png')
        over.channel('blend').set(blend)
        over.channel('opacity').set(.7)
    # Row 3: procedurals through the object.
    for c, (name, kind) in enumerate(zip(rows[2], ('noise', 'cellular', 'wood', 'checker', 'weave'))):
        made, locator = layer(mask_of(name), kind, 'diffColor', None, 'none')
        place(locator, (-3.2 + 1.6 * c, 1.6, 0), (.2, .2, .2))
        colour(made, 'color1', (.9, .2, .1))
        colour(made, 'color2', (.1, .3, .9))
        report.setdefault('procedural types', {})[name] = made.type
    # Row 4: channels.
    m = material_in(mask_of('Specular'))
    m.channel('specAmt').set(.5)
    layer(mask_of('Specular'), 'imageMap', 'specColor', images / 'colour.png')
    m = material_in(mask_of('Subsurface'))
    m.channel('subsAmt').set(1.0)
    m.channel('subsDist').set(.2)
    layer(mask_of('Subsurface'), 'imageMap', 'subsColor', images / 'stripes.png')
    material_in(mask_of('Displace')).channel('displace').set(.05)
    layer(mask_of('Displace'), 'imageMap', 'displace', height)
    layer(mask_of('Displace'), 'imageMap', 'diffColor', images / 'green.png')
    m = material_in(mask_of('NormalBump'))
    m.channel('bumpAmp').set(.02)
    m.channel('rough').set(.2)
    layer(mask_of('NormalBump'), 'imageMap', 'normal', images / 'normal.png')
    bump, _ = layer(mask_of('NormalBump'), 'imageMap', 'bump', height)
    bump.channel('opacity').set(.5)
    layer(mask_of('DiffAmount'), 'imageMap', 'diffColor', images / 'colour.png')
    layer(mask_of('DiffAmount'), 'imageMap', 'diffAmount', images / 'grey.png')
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'round2.lxo'))
    report['saved'] = str(out / 'round2.lxo')
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report-scene.json').write_text(json.dumps(report, indent=1, default=str))
