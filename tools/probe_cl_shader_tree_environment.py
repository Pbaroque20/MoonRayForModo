# python
"""Command line: an Environment's Shader Tree layers moved into its MoonShine graph by Move Shader Tree Textures to
MoonShine Graphs (moonray.material.moveShaderTreeTextures; shader_tree_environment). MOONRAY_PROBE_CASE picks the
environment, made in a new scene (a floor, a cube and a ball under it, no light but the environment):
  hdri        a latitude-longitude HDR image, Spherical;
  gradient    Modo's Environment Material, a 4 Color Gradient;
  blend       the HDR image at 60% Add over the gradient, a Grid at 30% and a colour at 50% Multiply over them;
  projection  a colour image laid by a Cubic projection over the gradient at 80%;
  physical    a Physical Sky lit by a Sun Light (no light of its own), the HDR at 40% Screen over it.
Run with tools/launch_cl_steps.py, the command, app.undo and app.redo at Modo's own prompt between the phases:
  probe  moonray.material.moveShaderTreeTextures  probe  moonray.material.moveShaderTreeTextures  probe  app.undo  probe
  app.undo  probe  app.redo  app.redo  probe
Writes to MOONRAY_PROBE_OUT/<case>: before.rdla and after.rdla (the scene as MoonRay is given it before the command
and after its redo), before.json and after.json (the environments the kit hands MoonRay, XPU2 and MoonLightIPR, the
layers' identities left out), report.json (the command's report, the clips, layers and graph at each phase)."""
import builtins
import json
import math
import os
import pathlib
import struct
import traceback
import zlib
import lx
import modo

case = os.environ.get('MOONRAY_PROBE_CASE', 'hdri')
base = pathlib.Path(os.environ.get('MOONRAY_PROBE_OUT') or r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\agent-a373440d5d5ce84bd\test-results\shader-tree-environment')
out = base / case
images = base / 'images'
out.mkdir(parents=True, exist_ok=True)
images.mkdir(parents=True, exist_ok=True)


def hdr(path, width=128, height=64):
    """A Radiance HDR, flat scanlines: a sky brighter upward, a warm ground, coloured bands by longitude, a sun."""
    rows = []
    for y in range(height):
        row = bytearray()
        latitude = (0.5 - (y + .5) / height) * math.pi
        for x in range(width):
            u = (x + .5) / width
            if latitude > 0:
                r, g, b = .3 + .4 * math.sin(latitude), .45 + .4 * math.sin(latitude), .9 + .6 * math.sin(latitude)
            else:
                r, g, b = .35, .25, .15
            band = int(u * 4) % 4
            r, g, b = (r * 1.6, g, b) if band == 0 else (r, g * 1.5, b) if band == 1 else (r, g, b) if band == 2 else (r * .6, g * .6, b * .6)
            if abs(u - .3) < .03 and abs(latitude - .5) < .06:
                r, g, b = 40.0, 36.0, 30.0
            top = max(r, g, b)
            exponent = math.frexp(top)[1]
            scale = 256.0 / 2 ** exponent
            row += bytes((min(255, int(r * scale)), min(255, int(g * scale)), min(255, int(b * scale)), exponent + 128))
        rows.append(bytes(row))
    path.write_bytes(b'#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y %d +X %d\n' % (height, width) + b''.join(rows))
    return path


def png(path, size, pixel):
    rows = b''.join(b'\0' + bytes(v for x in range(size) for v in pixel(x, y)) for y in range(size))

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    head = struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0)
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', head) + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))
    return path


def link(layer, target):
    graph = lx.object.ItemGraph(lx.object.Scene(layer._item.Context()).GraphLookup('shadeLoc'))
    graph.AddLink(layer._item, target._item)


def clip(path):
    scene = modo.Scene()
    before = {i.id for i in scene.items('videoStill')}
    lx.eval('clip.addStill {%s}' % path)
    return next(i for i in scene.items('videoStill') if i.id not in before)


def on_top(environment, kind, name):
    made = modo.Scene().addItem(kind, name=name)
    made.setParent(environment, len(list(environment.children())))
    made.channel('effect').set('envColor')
    return made


def locator_of(layer):
    return next(i for i in layer.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator')


def image_layer(environment, path, projection='spherical', opacity=1.0, blend='normal'):
    source = clip(path)
    layer = on_top(environment, 'imageMap', pathlib.Path(path).stem + ' (Image)')
    link(layer, source)
    locator = locator_of(layer)
    locator.channel('projType').set(projection)
    layer.channel('opacity').set(opacity)
    layer.channel('blend').set(blend)
    return layer, locator, source


def set_colour(item, prefix, rgb):
    for axis, value in zip('RGB', rgb):
        item.channel(prefix + '.' + axis).set(value)


def build():
    lx.eval('scene.new')
    scene = modo.Scene()
    render = scene.renderItem
    for name, value in (('resX', 480), ('resY', 270), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    for light in list(scene.items('light')):
        scene.removeItems(light)
    floor = scene.addMesh('Floor')
    with floor.geometry as geo:
        points = [geo.vertices.new(p) for p in ((-6, 0, -6), (-6, 0, 6), (6, 0, 6), (6, 0, -6))]
        geo.polygons.new(points)
    lx.eval('item.create mesh Ball')
    ball = next(i for i in scene.items('mesh') if i.name == 'Ball')
    lx.eval('select.item {%s} set' % ball.id)
    lx.eval('tool.set prim.sphere on')
    for axis, value in (('cenX', .8), ('cenY', .7), ('cenZ', 0), ('sizeX', .7), ('sizeY', .7), ('sizeZ', .7)):
        lx.eval('tool.attr prim.sphere %s %s' % (axis, value))
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    lx.eval('select.type item')
    camera = scene.renderCamera
    camera.position.set((0.0, 1.4, 5.5))
    camera.rotation.set((0.12, 0.0, 0.0))
    environment = next(iter(scene.items('environment', superType=False)))
    material = next(i for i in environment.children() if i.type == 'envMaterial')
    material.channel('type').set('grad4')
    set_colour(material, 'zenColor', (.08, .2, .55))
    set_colour(material, 'skyColor', (.7, .78, .95))
    set_colour(material, 'gndColor', (.32, .28, .22))
    set_colour(material, 'nadColor', (.1, .08, .06))
    sky = hdr(images / 'sky.hdr')
    if case == 'hdri':
        scene.removeItems(material)
        image_layer(environment, sky)
    elif case == 'blend':
        image_layer(environment, sky, opacity=.6, blend='add')
        grid = on_top(environment, 'grid', 'Grid')
        grid.channel('opacity').set(.3)
        locator_of(grid).channel('projType').set('spherical')
        tint = on_top(environment, 'constant', 'Tint')
        set_colour(tint, 'color', (1.0, .7, .4))
        tint.channel('opacity').set(.5)
        tint.channel('blend').set('multiply')
    elif case == 'projection':
        checker = png(images / 'checker.png', 64, lambda x, y: (230, 60, 40) if (x // 8 + y // 8) % 2 else (40, 90, 220))
        image_layer(environment, checker, projection='cubic', opacity=.8)
    elif case == 'physical':
        sun = scene.addItem('sunLight', name='Sun')
        sun.rotation.set((-0.6, 0.8, 0.0))
        material.channel('type').set('physical')
        image_layer(environment, sky, opacity=.4, blend='screen')
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'scene.lxo'))


def state():
    from moonray_modo import properties, shader_tree_environment
    scene = modo.Scene()
    environment = next(iter(scene.items('environment', superType=False)))
    return {'clips': sorted(c.name for c in scene.items('videoStill')),
            'layers': {item.name: bool(item.channel('enable').get()) for item in environment.children()},
            'graph': properties.read(environment).get(shader_tree_environment.KEY)}


def export(name):
    from moonray_modo import host, rdla
    with host.by_engine('moonray'):
        snapshot = host.snapshot(evaluated_geometry=True)
    render = modo.Scene().renderItem
    text = rdla.scene_text(snapshot, int(render.channel('resX').get()), int(render.channel('resY').get()), 16, 0.0, str(out / (name + '.exr')))
    (out / (name + '.rdla')).write_text(text, encoding='utf-8')

    def strip(value):
        if isinstance(value, dict):
            return {k: strip(v) for k, v in value.items() if k != 'layer_identity'}
        if isinstance(value, list):
            return [strip(v) for v in value]
        return value
    (out / (name + '.json')).write_text(json.dumps(strip(snapshot.get('environments')), indent=1, sort_keys=True, default=str))
    report[name + ' warnings'] = snapshot.get('warnings')


def turned(name):
    """Exported with the first image layer's Texture Locator turned about Y (as turning an HDRI), then turned back:
    after the move the graph's image is still placed by it."""
    scene = modo.Scene()
    layer = next((i for i in scene.items('imageMap')), None)
    if layer is None:
        return
    locator = locator_of(layer)
    lx.eval('select.item {%s} set' % locator.id)
    lx.eval('transform.channel rot.Y 40.0')
    export(name)
    lx.eval('select.item {%s} set' % locator.id)
    lx.eval('transform.channel rot.Y 0.0')


held = getattr(builtins, '_shader_tree_environment_probe', None)
if held is None:
    held = builtins._shader_tree_environment_probe = {'phase': 0, 'report': {}}
held['phase'] += 1
phase = held['phase']
report = held['report']
try:
    from moonray_modo import shader_tree_scene
    if phase == 1:
        if case == 'gradient':
            # An environment with no image is left as it is by the command; moved here to see it drawn from its graph.
            from moonray_modo import shader_tree_environment
            shader_tree_environment.WITHOUT_IMAGES = True
        build()
        held['initial'] = state()
        report['initial'] = held['initial']
        export('before')
        turned('before-turned')
    elif phase == 2:
        held['first'] = state()
        report['first'] = held['first']
        report['first report'] = list(shader_tree_scene.LAST_REPORT)
        export('after-first')
    elif phase == 3:
        again = state()
        report['again report'] = list(shader_tree_scene.LAST_REPORT)
        report['again unchanged'] = again == held['first']
    elif phase in (4, 5):
        undone = state()
        report['undo %d' % (phase - 3)] = {'as before the command': undone == held['initial'], 'as after the first run': undone == held['first'],
                                           'clips': undone['clips'], 'layers': undone['layers']}
    elif phase == 6:
        report['redo: as after the first run'] = state() == held['first']
        export('after')
        turned('after-turned')
except Exception:
    report['error phase %d' % phase] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
