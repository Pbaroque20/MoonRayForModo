# python
"""Command line: masks, vertex maps, drivers and falloffs as graph nodes (shader_tree_masks), each against the Shader
Tree it stands for. Two scenes of cubes in a row (in the first slots of the seven tools/check_shader_tree_transfer.py
compares by column), each with one material:
  masks:  Part    a stripes image, and a nested mask for a Part (the top polygons) with a green image;
          SelSet  the material's colour, and a nested mask for a Selection Set (the top polygons) with a red constant;
          ItemA, ItemB   one material on both, and a nested mask for the item ItemA with a blue constant;
  maps:   Weight  a Weight Map Texture (black to orange) on a weight map that rises with height;
          Driver  a grey image setting Driver A, and a Gradient on Driver A (its own default keys) as the colour;
          Falloff the material's colour only (in the graph: red within a Cubic falloff of a locator at the cube's corner).
Writes to MOONRAY_PROBE_OUT (default test-results/shader-tree-masks in this checkout):
  <scene>-before.rdla        the Shader Tree version (masks: read through Modo's evaluated geometry, as its masks have it);
  <scene>-after.rdla         the graph version, its layers off and its nested masks gone, read from the meshes;
  <scene>-after-evaluated.rdla   the same read through Modo's evaluated geometry;
  graphs-<scene>.json, report.json."""
import json
import math
import os
import pathlib
import struct
import traceback
import zlib
import lx
import modo

root = pathlib.Path(os.environ.get('MOONRAY_PROBE_ROOT') or r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\agent-a51b50ccd90c90520')
out = pathlib.Path(os.environ.get('MOONRAY_PROBE_OUT') or root / 'test-results' / 'shader-tree-masks')
images = out / 'images'
images.mkdir(parents=True, exist_ok=True)
report = {}


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))


def png(path, size, pixel):
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            row.extend(bytes(pixel(x, y)[:3]))
        rows.append(b'\0' + bytes(row))

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    head = struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0)
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', head) + chunk(b'IDAT', zlib.compress(b''.join(rows))) + chunk(b'IEND', b''))
    return path


def cube(name, slot, material, size=0.8):
    x = -3.6 + 1.2 * slot
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


def link(layer, target):
    graph = lx.object.ItemGraph(lx.object.Scene(layer._item.Context()).GraphLookup('shadeLoc'))
    graph.AddLink(layer._item, target._item)


def layer_in(under, kind, effect, name):
    made = modo.Scene().addItem(kind, name=name)
    made.setParent(under, len(list(under.children())))
    made.channel('effect').set(effect)
    return made


def image_layer(under, effect, path):
    scene = modo.Scene()
    before = {i.id for i in scene.items('videoStill')}
    lx.eval('clip.addStill {%s}' % path)
    clip = next(i for i in scene.items('videoStill') if i.id not in before)
    made = layer_in(under, 'imageMap', effect, '%s (Image)' % pathlib.Path(path).stem)
    link(made, clip)
    locator = next(i for i in made.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator')
    locator.channel('projType').set('uv')
    locator.channel('uvMap').set('Texture')
    return made


def constant_layer(under, effect, colour, name):
    made = layer_in(under, 'constant', effect, name)
    for channel, value in zip(('color.R', 'color.G', 'color.B'), colour):
        made.channel(channel).set(value)
    return made


def nested(group, name, ptyp='', ptag=''):
    inner = modo.Scene().addItem('mask')
    inner.setParent(group, len(list(group.children())))
    inner.channel('ptyp').set(ptyp)
    inner.channel('ptag').set(ptag)
    inner.name = name
    return inner


def top_polygons(mesh, tag_kind, value):
    with mesh.geometry as geo:
        top = [p for p in geo.polygons if sum(v.position[1] for v in p.vertices) / len(p.vertices) > .45]
        for polygon in top:
            polygon.setTag(tag_kind, value)
    return len(top)


def export(name, evaluated):
    from moonray_modo import host, rdla
    with host.by_engine('moonray'):
        snapshot = host.snapshot(evaluated_geometry=evaluated)
    render = modo.Scene().renderItem
    text = rdla.scene_text(snapshot, int(render.channel('resX').get()), int(render.channel('resY').get()), 6, 0.0, str(out / (name + '.exr')))
    (out / (name + '.rdla')).write_text(text, encoding='utf-8')
    report[name + ' warnings'] = snapshot.get('warnings')
    report[name + ' mesh attributes'] = sorted({(m.get('name'), key) for m in snapshot.get('meshes') or []
                                                for key in list((m.get('point_attributes') or {})) + list((m.get('corner_attributes') or {}))
                                                if key.startswith('__modo_mask_') or key == 'Wear'})
    report[name + ' parts'] = sorted({(m.get('name'), m.get('_part'), m.get('material')) for m in snapshot.get('meshes') or []})


def new_scene():
    lx.eval('scene.new')
    scene = modo.Scene()
    render = scene.renderItem
    for name, value in (('resX', 1260), ('resY', 300), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    floor = scene.addMesh('Floor')
    with floor.geometry as geo:
        points = [geo.vertices.new(p) for p in ((-8, 0, -4), (-8, 0, 4), (8, 0, 4), (8, 0, -4))]
        geo.polygons.new(points)
    camera = scene.renderCamera
    camera.position.set((0.0, 2.6, 11.0))
    camera.rotation.set((-0.25, 0.0, 0.0))
    return scene


def read(scene, material, items):
    """layers.collect's dicts for these layers of a material (shader_tree_scene.read_layers), by name."""
    from moonray_modo import shader_tree_scene
    warnings = []
    value, found = shader_tree_scene.read_layers(scene, material, 'probe:' + material.id, [i.id for i in items], {}, warnings)
    report.setdefault('read warnings', []).extend(warnings)
    return value, {layer.get('name') or layer['identity']: layer for layer in found}, {item.name: item for item in items}


def graph_for(scene, material, value, build):
    """The graph a material becomes: its output's values as the Shader Tree draws it with no layers
    (shader_tree_scene.modo_values), its colour build(builder, base) laid as shader_tree_transfer lays a channel."""
    from moonray_modo import shader_tree_scene, shader_tree_transfer as transfer, nodes, layers
    from moonray_modo.graph import defaults_for
    parameters, ramps = shader_tree_scene.modo_values(scene, material, value, list(layers.ordered_items(scene.renderItem)))
    bases = defaults_for(value)
    post = dict(ramps, diffuse_amount=value.get('diffuse_amount', 1.0), emission_amount=value.get('emission_amount', 1.0),
                bump_strength=value.get('bump_strength', .005))
    plan = transfer.Plan()
    colour = build(plan.builder, ('c', transfer.rgb(bases['diffCol'])))
    transfer.outputs(plan, material.id, {'diffCol': colour}, {'diffCol'}, 'modo', post)
    return transfer.merged(nodes.new('DwaBaseMaterial', parameters), plan, {'profile': 'modo', 'material': material.id, 'bases': bases, 'post': post},
                           created=True)


def put(material, graph):
    from moonray_modo import properties, material_override
    properties.write(material, material_override.synchronize(properties.read(material), graph))


def off(*items):
    for item in items:
        item.channel('enable').set(0)


def delete(item):
    lx.eval('select.item {%s} set' % item.id)
    lx.eval('!item.delete')


def masks_scene():
    from moonray_modo import shader_tree_transfer as transfer, shader_tree_masks as masks
    alpha_of = transfer.file_alpha
    stripes = png(images / 'stripes.png', 64, lambda x, y: (250, 200, 30) if (y // 8) % 2 else (20, 20, 20))
    green = png(images / 'green.png', 64, lambda x, y: (40, 200, 60) if (x // 16) % 2 else (240, 240, 240))
    scene = new_scene()
    meshes = {name: cube(name, slot, tag) for name, slot, tag in (('Part', 0, 'Part'), ('SelSet', 1, 'SelSet'), ('ItemA', 2, 'Items'), ('ItemB', 3, 'Items'))}
    report['part polygons'] = top_polygons(meshes['Part'], lx.symbol.i_POLYTAG_PART, 'PartTop')
    report['set polygons'] = top_polygons(meshes['SelSet'], lx.symbol.i_POLYTAG_PICK, 'SetY')
    part_group = mask_of('Part')
    base_image = image_layer(part_group, 'diffColor', stripes)
    part_mask = nested(part_group, 'PartTop mask', 'Part', 'PartTop')
    top_image = image_layer(part_mask, 'diffColor', green)
    set_group = mask_of('SelSet')
    set_mask = nested(set_group, 'SetY mask', 'Selection Set', 'SetY')
    red = constant_layer(set_mask, 'diffColor', (0.9, 0.1, 0.1), 'red')
    item_group = mask_of('Items')
    item_mask = nested(item_group, 'ItemA mask')
    link(item_mask, meshes['ItemA'])
    blue = constant_layer(item_mask, 'diffColor', (0.1, 0.2, 0.9), 'blue')
    for material in (material_in(part_group), material_in(set_group), material_in(item_group)):
        material.channel('diffCol.R').set(0.6)
    report['masks'] = [(m.name, m.channel('ptyp').get(), m.channel('ptag').get()) for m in (part_mask, set_mask, item_mask)]
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'masks.lxo'))
    export('masks-before', True)

    def info(mask):
        from moonray_modo.mask_types import tag_kind, mask_items
        return {'identity': mask.id, 'name': mask.name, 'tag_type': tag_kind(mask.channel('ptyp').get()), 'tag': mask.channel('ptag').get(),
                'items': [i.id for i in mask_items(mask)], 'instances': bool(mask.channel('instApply').get())}
    made = {}
    # Part: the stripes, and the green image over them where the Part mask is.
    material = material_in(part_group)
    value, found, _ = read(scene, material, [base_image, top_image])
    report['part layers'] = sorted(found)

    def part(builder, base):
        below = found[base_image.name]
        image, alpha = transfer.image(builder, below, 'diffCol', alpha_of)
        current = transfer.laid(builder, below['identity'], 'over', base, image, 'normal', 1, [alpha])
        above = found[top_image.name]
        image, alpha = transfer.image(builder, above, 'diffCol', alpha_of)
        return transfer.laid(builder, above['identity'], 'over', current, image, 'normal', 1, [alpha, masks.mask_value(builder, info(part_mask))])
    made['Part'] = (material, graph_for(scene, material, value, part))
    # SelSet: red where the Selection Set is.
    material = material_in(set_group)
    value = __import__('moonray_modo.host', fromlist=['material_values']).material_values(material)
    made['SelSet'] = (material, graph_for(scene, material, value, lambda builder, base: transfer.laid(
        builder, red.id, 'over', base, ('c', [0.9, 0.1, 0.1]), 'normal', 1, [masks.mask_value(builder, info(set_mask))])))
    # Items: blue on ItemA, through a Modo Blend.
    material = material_in(item_group)
    value = __import__('moonray_modo.host', fromlist=['material_values']).material_values(material)

    def items(builder, base):
        node = builder.add(blue.id, 'blend', 'modo_blend', {'blend': 0, 'opacity': 1.0}, {'bg': base, 'fg': ('c', [0.1, 0.2, 0.9])})
        transfer.wire(builder.nodes[node[1]], 'mask', masks.mask_value(builder, info(item_mask)), scalar=True)
        return node
    made['Items'] = (material, graph_for(scene, material, value, items))
    for name, (material, graph) in made.items():
        put(material, graph)
    (out / 'graphs-masks.json').write_text(json.dumps({k: g for k, (_, g) in made.items()}, indent=1, sort_keys=True))
    off(base_image, top_image, red, blue)
    for mask in (part_mask, set_mask, item_mask):
        delete(mask)
    export('masks-after', False)
    export('masks-after-evaluated', True)


def maps_scene():
    from moonray_modo import host, gradients, shader_tree_transfer as transfer, shader_tree_masks as masks
    alpha_of = transfer.file_alpha
    grey = png(images / 'grey.png', 64, lambda x, y: (x * 4, x * 4, x * 4))
    scene = new_scene()
    meshes = {name: cube(name, slot, name) for name, slot in (('Weight', 0), ('Driver', 1), ('Falloff', 2))}
    with meshes['Weight'].geometry as geo:
        weight = geo.vmaps.addWeightMap('Wear', 0.0)
        for vertex in geo.vertices:
            weight[vertex.index] = (min(1.0, max(0.0, vertex.position[1] / 0.8)),)
    report['weight maps'] = [m.name for m in meshes['Weight'].geometry.vmaps.weightMaps]
    weight_group = mask_of('Weight')
    wear = layer_in(weight_group, 'vmapTexture', 'diffColor', 'Wear (Weight Map)')
    wear.channel('vmap').set('Wear')
    for channel, value in zip(('color2.R', 'color2.G', 'color2.B'), (1.0, 0.5, 0.0)):
        wear.channel(channel).set(value)
    for channel in ('color1.R', 'color1.G', 'color1.B'):
        wear.channel(channel).set(0.0)
    driver_group = mask_of('Driver')
    drive = image_layer(driver_group, 'driverA', grey)
    gradient = layer_in(driver_group, 'gradient', 'diffColor', 'on Driver A (Gradient)')
    gradient.channel('param').set('driverA')
    for axis, (low, high) in zip('RGB', ((0.9, 0.1), (0.1, 0.8), (0.2, 0.2))):
        for x, value in ((0.0, low), (1.0, high)):
            lx.eval('channel.key time:%g value:%g channel:{%s:color.%s}' % (x, value, gradient.id, axis))
    for material in (material_in(weight_group), material_in(driver_group), material_in(mask_of('Falloff'))):
        material.channel('diffCol.R').set(0.6)
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'maps.lxo'))
    export('maps-before', False)
    made = {}
    material = material_in(weight_group)
    value, found, _ = read(scene, material, [wear])
    report['weight layers'] = {k: v.get('gradient', {}).get('input') for k, v in found.items()}
    layer = next(iter(found.values()))

    def weighted(builder, base):
        masks.CHECKS[masks.layer_key(layer)](layer, 'diffCol')
        colour, mask = masks.FOREGROUNDS[masks.layer_key(layer)](builder, layer, 'diffCol', alpha_of)
        return transfer.laid(builder, layer['identity'], 'over', base, colour, layer.get('blend', 'normal'), layer.get('opacity', 1), [mask])
    made['Weight'] = (material, graph_for(scene, material, value, weighted))
    material = material_in(driver_group)
    value, found, _ = read(scene, material, [drive, gradient])
    report['driver layers'] = {k: (v.get('effect'), v.get('kind'), (v.get('gradient') or {}).get('input')) for k, v in found.items()}
    setting = next(v for v in found.values() if v.get('effect') == 'driverA')
    reading = next(v for v in found.values() if v.get('kind') == 'gradient')

    def driven(builder, base):
        image, alpha = transfer.image(builder, setting, 'driverA', alpha_of)
        drivers = {'driverA': transfer.laid(builder, setting['identity'], 'over', ('c', [0.0] * 3), image, 'normal', 1, [alpha])}
        masks.CHECKS[masks.layer_key(reading)](reading, 'diffCol')
        colour, mask = masks.FOREGROUNDS[masks.layer_key(reading)](builder, reading, 'diffCol', alpha_of, drivers=drivers)
        return transfer.laid(builder, reading['identity'], 'over', base, colour, reading.get('blend', 'normal'), reading.get('opacity', 1), [mask])
    made['Driver'] = (material, graph_for(scene, material, value, driven))
    material = material_in(mask_of('Falloff'))
    value = host.material_values(material)
    corner = [0.4, 0.0, 0, 0, 0, 0.4, 0, 0, 0, 0, 0.4, 0, -1.2 + 0.4, 0.8, 0.4, 1.0]

    def falloff(builder, base):
        fade = builder.add('falloff', 'falloff', 'modo_falloff', {'shape': 0, 'locator_matrix': corner, 'start': 0.5, 'width': 1.0})
        node = builder.add('falloff', 'blend', 'modo_blend', {'blend': 0, 'opacity': 1.0}, {'bg': base, 'fg': ('c', [0.9, 0.1, 0.1])})
        transfer.wire(builder.nodes[node[1]], 'mask', fade, scalar=True)
        return node
    made['Falloff'] = (material, graph_for(scene, material, value, falloff))
    for name, (material, graph) in made.items():
        put(material, graph)
    (out / 'graphs-maps.json').write_text(json.dumps({k: g for k, (_, g) in made.items()}, indent=1, sort_keys=True))
    off(wear, drive, gradient)
    export('maps-after', False)


for name, run in (('masks', masks_scene), ('maps', maps_scene)):
    try:
        run()
        report[name] = 'done'
    except Exception:
        report[name + ' error'] = traceback.format_exc()
    save()
