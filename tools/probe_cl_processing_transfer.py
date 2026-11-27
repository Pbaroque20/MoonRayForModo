# python
"""Command line: Shader Tree processing textures moved into MoonShine graphs (shader_tree_processing), rendered as the
Shader Tree layers and as the graphs. A row of seven cubes on a floor, one material each with one processing texture on
its Diffuse Color (and a roughness image beneath it, as the command moves materials with images); MOONRAY_PROBE_SET picks
the seven:
  a  Occlusion (with an alpha), Curvature, Gradient by Slope, by Incidence Angle, by Distance to its locator, Variation
     by Item, Gradient by Diffuse Amount (a channel beneath);
  b  Tension, Variation by Mesh Part, by Particle, Gradient by Distance to Camera, by Locator Incidence, by Texture U
     under a Solid projection, Weight Map Texture.
Exports <out>/before.rdla (the Shader Tree's), runs shader_tree_scene.run() with the processing textures wired into its
dispatch (as the integration does: shader_tree_processing.CHECKS and FOREGROUNDS, the channel beneath as _beneath), and
exports <out>/after.rdla (the graphs'), with report.json. Render and compare them with tools/check_shader_tree_transfer.py.
MOONRAY_PROBE_OUT is the folder."""
import json
import os
import pathlib
import struct
import traceback
import zlib
import lx
import modo

out = pathlib.Path(os.environ.get('MOONRAY_PROBE_OUT') or pathlib.Path(__file__).resolve().parents[1] / 'test-results' / 'processing-transfer')
which = os.environ.get('MOONRAY_PROBE_SET', 'a')
out.mkdir(parents=True, exist_ok=True)
report = {'set': which}


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))


def png(path, pixel):
    rows = b''.join(b'\0' + b''.join(bytes(pixel(x, y)) for x in range(64)) for y in range(64))

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 64, 64, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(rows))
                     + chunk(b'IEND', b''))
    return path


def cube(name, x, material, size=0.8, segments=8):
    lx.eval('item.create mesh {%s}' % name)
    mesh = next(i for i in modo.Scene().items('mesh') if i.name == name)
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('tool.set prim.cube on')
    for axis, value in (('cenX', x), ('cenY', size / 2), ('cenZ', 0), ('sizeX', size), ('sizeY', size), ('sizeZ', size)):
        lx.eval('tool.attr prim.cube %s %s' % (axis, value))
    for axis in 'XYZ':
        lx.eval('tool.attr prim.cube segments%s %d' % (axis, segments))
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


def link(layer, target):
    graph = lx.object.ItemGraph(lx.object.Scene(layer._item.Context()).GraphLookup('shadeLoc'))
    graph.AddLink(layer._item, target._item)


def rough_image(under, path):
    scene = modo.Scene()
    clip = next((i for i in scene.items('videoStill') if pathlib.Path(i.channel('filename').get()) == pathlib.Path(path)), None)
    if clip is None:
        before = {i.id for i in scene.items('videoStill')}
        lx.eval('clip.addStill {%s}' % path)
        clip = next(i for i in scene.items('videoStill') if i.id not in before)
    made = scene.addItem('imageMap', name='rough (Image)')
    made.setParent(under, len(list(under.children())))
    link(made, clip)
    made.channel('effect').set('rough')
    locator = next(i for i in made.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator')
    locator.channel('projType').set('uv')
    locator.channel('uvMap').set('Texture')
    return made


def layer(tag, kind):
    """A processing texture of this kind in the material's group, over the material, on its Diffuse Color."""
    scene = modo.Scene()
    material = material_in(mask_of(tag))
    before = {i.id for i in scene.items(kind)}
    scene.select(material)
    lx.eval('shader.create %s' % kind)
    made = next(i for i in scene.items(kind) if i.id not in before)
    made.channel('effect').set('diffColor')
    return made


def keys(item, points, prefix='color'):
    """Colour keys (input, (r, g, b)) on a gradient channel."""
    for x, colour in points:
        for axis, value in zip('RGB', colour):
            lx.eval('channel.key time:%g value:%g channel:{%s:%s.%s}' % (x, value, item.id, prefix, axis))


def colours(item, **values):
    for name, value in values.items():
        if isinstance(value, (list, tuple)):
            for axis, v in zip('RGB', value):
                item.channel('%s.%s' % (name, axis)).set(v)
        else:
            item.channel(name).set(value)


def set_a(tags):
    occ = layer(tags[0], 'occlusion')
    colours(occ, color1=(.05, .1, .4), color2=(1, .85, .6), alpha1=.3, alpha2=1.0, rays=64, dist=.6)
    try:
        curvature = layer(tags[1], 'val.RTCurvature')
        report['curvature channels'] = [curvature.internalItem.ChannelName(i) for i in range(curvature.internalItem.ChannelCount())]
        keys(curvature, [(0, (0, 0, 1)), (.5, (.5, .5, .5)), (1, (1, .2, 0))], 'gradientColor')
    except Exception:
        report['curvature error'] = traceback.format_exc()
    for tag, param, points in ((tags[2], 'slope', [(0, (0, .2, 1)), (1.5708, (1, .1, .1)), (3.1416, (.1, 1, .1))]),
                               (tags[3], 'incidenceAngle', [(0, (1, 1, 1)), (1, (.1, .1, .5))]),
                               (tags[4], 'distance', [(.5, (0, 0, 0)), (2.5, (1, .9, .2))]),
                               (tags[6], 'diffAmount', [(0, (0, 0, 0)), (1, (1, .3, .8))])):
        gradient = layer(tag, 'gradient')
        gradient.channel('param').set(param)
        keys(gradient, points)
        if param == 'distance':
            locator = next(i for i in gradient.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator')
            modo.LocatorSuperType(locator).position.set((.4, .3, .5))
    material_in(mask_of(tags[6])).channel('diffAmt').set(.6)
    variation = layer(tags[5], 'variationTexture')
    variation.channel('type').set('item')
    keys(variation, [(0, (1, 0, 0)), (1, (0, 0, 1))])


def set_b(tags, meshes):
    tension = layer(tags[0], 'tensionTexture')
    keys(tension, [(-.5, (0, 0, 1)), (0, (1, .5, 0)), (.5, (0, 1, 0))])
    with meshes[tags[1]].geometry as geo:
        for polygon in geo.polygons:
            if sum(v.position[1] for v in polygon.vertices) / len(polygon.vertices) > .45:
                polygon.setTag(lx.symbol.i_POLYTAG_PART, 'Top')
    for tag, source in ((tags[1], 'meshPart'), (tags[2], 'particle')):
        variation = layer(tag, 'variationTexture')
        variation.channel('type').set(source)
        keys(variation, [(0, (1, 1, 0)), (1, (0, .2, 1))])
    for tag, param, points in ((tags[3], 'cameraDistance', [(11.5, (0, 0, 0)), (13, (1, 1, 1))]),
                               (tags[4], 'locatorIncAngle', [(0, (1, .2, .2)), (2, (.2, .2, 1))]),
                               (tags[5], 'textureU', [(-1, (0, 0, 0)), (1, (1, 1, 1))])):
        gradient = layer(tag, 'gradient')
        gradient.channel('param').set(param)
        keys(gradient, points)
        locator = next(i for i in gradient.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator')
        if param == 'textureU':
            locator.channel('projType').set('none')
            modo.LocatorSuperType(locator).position.set((meshes[tag].position.get()[0] + 2.4, .4, 0))
        if param == 'locatorIncAngle':
            modo.LocatorSuperType(locator).position.set((1.2, 3, 2))
    # A weight map on the last cube: its height.
    mesh = meshes[tags[6]]
    with mesh.geometry as geo:
        weights = geo.vmaps.addMap(lx.symbol.i_VMAP_WEIGHT, 'Heights')
        for vertex in geo.vertices:
            weights[vertex.index] = (max(0.0, min(1.0, vertex.position[1] / .8)),)
    weight = layer(tags[6], 'vmapTexture')
    weight.channel('vmap').set('Heights')
    colours(weight, color1=(.1, .1, .1), color2=(1, .3, .1))


def export(name):
    from moonray_modo import host, rdla
    with host.by_engine('moonray'):
        snapshot = host.snapshot(evaluated_geometry=os.environ.get('MOONRAY_PROBE_EVALUATED', '0') == '1')
    render = modo.Scene().renderItem
    text = rdla.scene_text(snapshot, int(render.channel('resX').get()), int(render.channel('resY').get()), 6, 0.0, str(out / (name + '.exr')))
    (out / (name + '.rdla')).write_text(text, encoding='utf-8')
    report[name + ' warnings'] = snapshot.get('warnings')
    report[name + ' layers'] = {tag: [(l.get('kind'), (l.get('gradient') or {}).get('input')) for l in (m.get('layers') or [])]
                                for tag, m in (snapshot.get('materials') or {}).items()}
    report[name + ' attributes'] = {m.get('name'): sorted(list((m.get('point_attributes') or {})) + list((m.get('corner_attributes') or {})))
                                    for m in snapshot.get('meshes', [])}


def install():
    """The processing textures in shader_tree_transfer's dispatch, as the integration wires them."""
    from moonray_modo import shader_tree_processing as processing, shader_tree_transfer as transfer
    check, image, plan = transfer.check, transfer.image, transfer.plan

    def checked(layer, effect, *rest, **named):
        if processing.key(layer) in processing.CHECKS:
            check(dict(layer, kind='constant'), effect, *rest, **named)  # effect, groups and blend as for any layer
            return processing.CHECKS[processing.key(layer)](layer, effect)
        return check(layer, effect, *rest, **named)

    def drawn(builder, layer, effect, alpha_of):
        if processing.key(layer) in processing.FOREGROUNDS:
            return processing.FOREGROUNDS[processing.key(layer)](builder, layer, effect, alpha_of)
        return image(builder, layer, effect, alpha_of)

    def planned(material, layers, bases, *rest, **named):
        given = []
        for index, held in enumerate(layers):
            source = processing.reads_beneath(held) if held.get('kind') == 'gradient' else None
            if source is not None and not any(other.get('effect') == source for other in layers[:index]):
                held = dict(held, _beneath=('c', transfer.rgb(bases.get(source, 0.0))))
            given.append(held)
        return plan(material, given, bases, *rest, **named)
    transfer.check, transfer.image, transfer.plan = checked, drawn, planned


try:
    lx.eval('scene.new')
    scene = modo.Scene()
    render = scene.renderItem
    for name, value in (('resX', 1260), ('resY', 300), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    floor = scene.addMesh('Floor')
    with floor.geometry as geo:
        points = [geo.vertices.new(p) for p in ((-8, 0, -4), (-8, 0, 4), (8, 0, 4), (8, 0, -4))]
        geo.polygons.new(points)
    tags = ['P%d' % i for i in range(7)]
    meshes = {tag: cube('Cube' + tag, -3.6 + 1.2 * index, tag) for index, tag in enumerate(tags)}
    camera = scene.renderCamera
    camera.position.set((0.0, 1.8, 12.5))
    camera.rotation.set((-0.12, 0.0, 0.0))
    (set_a if which == 'a' else lambda t: set_b(t, meshes))(tags)
    rough = png(out / 'rough.png', lambda x, y: (60 + x * 2, 60 + x * 2, 60 + x * 2))
    for tag in tags:
        rough_image(mask_of(tag), rough)
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / ('processing_%s.lxo' % which)))
    export('before')
    save()
    install()
    from moonray_modo import shader_tree_scene, material_override, properties, shader_tree_transfer as transfer
    made = shader_tree_scene.run()
    report['run'] = {'moved': made.moved, 'left': made.left, 'made': made.made}
    report['graphs'] = {}
    for item in scene.items('advancedMaterial'):
        settings = properties.read(item)
        graph = settings.get('node_graph') if material_override.enabled(settings) else None
        if graph:
            report['graphs'][item.name] = {i: n['type'] for i, n in graph['nodes'].items()}
    export('after')
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / ('processing_%s_after.lxo' % which)))
except Exception:
    report['error'] = traceback.format_exc()
save()
