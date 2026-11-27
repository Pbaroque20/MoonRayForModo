"""Graph nodes for what Shader Tree masks, vertex maps, Texture Locator falloffs and drivers do, and how Move Shader Tree
Textures to MoonShine Graphs (shader_tree_transfer) makes them.

Four nodes, under Modo Shader Tree in the graph editor (nodes.MODO_NODES):
  modo_vertex_map  a mesh's weight map, RGB map or an RGBA map's alpha, by name, as the kit sends them (vertex_maps):
                   a primitive attribute of that name read at each point.
  modo_mask        0 to 1 for whether a point is in a group mask: by item, Selection Set, Part, Material Tag, weight map
                   or particle (the copies a Replicator lays), with Invert and Opacity. Wired into a Modo Blend's mask,
                   one graph does what a nested mask does, and the surfaces in and out of it can wear one material.
  modo_falloff     1 near a Texture Locator, fading to 0 away from it (Cubic, Spherical, Linear X, Y or Z, in the
                   locator's own space and size): for decals and wear.
  modo_driver      a Driver A to D: a value laid once (a chain of layers) and read by as many layers as read it.

How a mask is known at render: the kit writes, on the meshes that wear a graph with a Modo Mask (apply), a number of
the mask's own name (attribute()) that is 1 where the mesh is in it and 0 where not: one value for a whole mesh (an item
mask), one for each copy of it (instances), or one at each corner of each polygon (a Part or a Selection Set, whose
membership changes from polygon to polygon). MoonRay and XPU2 read it as any vertex map (an AttributeMap), MoonLightIPR
as a weight map (its '@vmap' rows). A mask by weight map reads the map itself.

The conversion hooks for shader_tree_transfer (the dispatcher is shader_tree_transfer's):
  CHECKS = {key: fn(layer, effect)}, raising shader_tree_transfer.Refused;
  FOREGROUNDS = {key: fn(builder, layer, effect, alpha_of, drivers=None) -> (value, mask)};
  key: 'gradient:' + the gradient's input for a Gradient layer (its '@vmap' a Weight Map Texture, 'driverA'..'driverD'
  a gradient on a driver), 'effect:' + a driver for a layer that sets one;
  mask_value(builder, info) -> value: a nested mask as a factor of its layers' masks (info: see mask_value);
  driver_node(builder, material, effect, value) -> value: the Driver node of a driver chain.
"""
import hashlib
import json
import math

NODES = ('modo_vertex_map', 'modo_mask', 'modo_falloff', 'modo_driver')
MASK_MODES = ('item', 'pick', 'part', 'material', 'weight', 'particle')
MASK_LABELS = ('Item', 'Selection Set', 'Part', 'Material Tag', 'Weight Map', 'Particle')
FALLOFF_SHAPES = ('cubic', 'spherical', 'linearX', 'linearY', 'linearZ')
FALLOFF_LABELS = ('Cubic', 'Spherical', 'Linear X', 'Linear Y', 'Linear Z')
DRIVERS = ('driverA', 'driverB', 'driverC', 'driverD')
IDENTITY = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]
SCHEMAS = {
    'modo_vertex_map': {'vertex_map': ('String', ''), 'type': ('Int', 0)},
    'modo_mask': {'mode': ('Int', 0), 'tag': ('String', ''), 'items': ('String', ''), 'vertex_map': ('String', ''),
                  'instances': ('Bool', False), 'invert': ('Bool', False), 'opacity': ('Float', 1.0)},
    'modo_falloff': {'shape': ('Int', 0), 'locator_matrix': ('FloatVector', list(IDENTITY)), 'start': ('Float', 0.5),
                     'width': ('Float', 0.5), 'invert': ('Bool', False)},
    'modo_driver': {'driver': ('Int', 0), 'value': ('Rgb', [0.0, 0.0, 0.0])},
}
# What of these nodes is wired, not set (nodes.specs): the rest are settings.
BINDABLE = {'modo_driver': ('value',)}
PREFIX = '__modo_mask_'
# A Modo Procedural gradient's input name for what is wired into its Input (a Vertex Map node): gradients.emit looks the
# gradient up by it, as by a channel beneath.
VERTEX_INPUT = 'vertexMap'
VERTEX_TYPES = {'Weight': 0, 'RGB': 1, 'RGBA alpha': 2}


def annotate(kind, result):
    """nodes.specs' enums and comments for these nodes."""
    if kind == 'modo_vertex_map':
        result['vertex_map']['comment'] = "The map's name, as the mesh has it (a weight map, an RGB or an RGBA map)."
        result['type']['enum'] = dict(VERTEX_TYPES)
        result['type']['comment'] = 'Weight: the weight at each point. RGB: the colour. RGBA alpha: an RGBA map\'s alpha.'
    elif kind == 'modo_mask':
        result['mode']['enum'] = {label: index for index, label in enumerate(MASK_LABELS)}
        result['mode']['comment'] = ('What the mask goes by, as a Shader Tree group mask: its Item, its polygon tag (Selection '
                                     'Set, Part, Material Tag), a weight map, or the copies a Replicator lays on particles.')
        result['tag']['comment'] = 'The Selection Set, Part or Material Tag (Polygon Tag in the Shader Tree).'
        result['items']['comment'] = ('Item and Particle: the items (or Replicators) the mask is for, by name or identity, '
                                      'separated by ;. A Group Locator or a Group covers what is in it, as in Modo.')
        result['vertex_map']['comment'] = 'Weight Map: the weight map whose weight (0 to 1) is the mask.'
        result['instances']['comment'] = "Instances of the items count too (the Shader Tree mask's Apply to Instances)."
        result['invert']['comment'] = 'Where the surface is not in the mask, rather than where it is.'
        result['opacity']['comment'] = 'The mask times this, 0 to 1.'
    elif kind == 'modo_falloff':
        result['shape']['enum'] = {label: index for index, label in enumerate(FALLOFF_LABELS)}
        result['shape']['comment'] = ("How the distance from the locator is measured, in its own space and size: Cubic its "
                                      "box, Spherical a ball, Linear along one of its axes.")
        result['locator_matrix']['comment'] = "The Texture Locator's world matrix (its place, turn and size)."
        result['start']['comment'] = 'Where the fade starts, in locator sizes from its centre (0.5: the edge of its box).'
        result['width']['comment'] = 'How far it takes to fade to nothing, in locator sizes.'
        result['invert']['comment'] = '0 near the locator, 1 away from it.'
    elif kind == 'modo_driver':
        result['driver']['enum'] = {'Driver A': 0, 'Driver B': 1, 'Driver C': 2, 'Driver D': 3}
        result['driver']['comment'] = 'Which driver: its value is read by the Gradients wired to this node.'
        result['value']['comment'] = 'The driver: a chain of layers, or a value, laid once and read by any number of nodes.'


# Masks: what a Modo Mask node goes by, and the name of the number the meshes carry for it.
def mask_spec(parameters):
    """A Modo Mask node's settings as what decides which surfaces it holds ({'mode', 'tag', 'items', 'instances'}), or
    None where none of the meshes carries it (a mask by weight map, which reads the map)."""
    mode = mode_name(parameters.get('mode', 0))
    if mode == 'weight':
        return None
    items = sorted({word.strip() for word in str(parameters.get('items', '') or '').split(';') if word.strip()})
    spec = {'mode': mode, 'tag': str(parameters.get('tag', '') or '') if mode in ('pick', 'part', 'material') else '',
            'items': items if mode in ('item', 'particle') else [],
            'instances': bool(parameters.get('instances', False)) if mode == 'item' else mode == 'particle'}
    return spec


def mode_name(value):
    if isinstance(value, str) and value in MASK_MODES:
        return value
    index = int(value)
    if not 0 <= index < len(MASK_MODES):
        raise ValueError('Modo Mask: unknown mode %r' % value)
    return MASK_MODES[index]


def attribute(spec):
    """The name of the number the meshes carry for a mask: the same for the same mask, at every reading."""
    text = json.dumps(spec, sort_keys=True, separators=(',', ':'))
    return PREFIX + hashlib.sha1(text.encode('utf-8')).hexdigest()[:16]


def graphs(value):
    """Every node graph in scene data (materials, their stacks), however deep."""
    found = []
    todo = [value]
    while todo:
        held = todo.pop()
        if isinstance(held, dict):
            if isinstance(held.get('nodes'), dict) and 'root' in held:
                found.append(held)
            todo.extend(held.values())
        elif isinstance(held, (list, tuple)):
            todo.extend(held)
    return found


def wanted(materials):
    """{attribute name: spec} of the Modo Mask nodes the materials' graphs have (enabled overrides of them included)."""
    found = {}
    for graph in graphs(materials):
        members = list((graph.get('nodes') or {}).values())
        members += [{'type': 'modo_mask', 'parameters': dict((graph['nodes'][override['node']].get('parameters') or {}), **(override.get('parameters') or {}))}
                    for override in graph.get('overrides') or ()
                    if isinstance(override, dict) and (graph.get('nodes') or {}).get(override.get('node'), {}).get('type') == 'modo_mask']
        for node in members:
            if not isinstance(node, dict) or node.get('type') != 'modo_mask':
                continue
            try:
                spec = mask_spec(node.get('parameters') or {})
            except (ValueError, TypeError):
                continue
            if spec is not None:
                found[attribute(spec)] = spec
    return found


def tags_wanted(materials):
    """Whether the meshes are to be read with each polygon's Part and Selection Sets (a mask goes by them)."""
    return any(spec['mode'] in ('part', 'pick') for spec in wanted(materials).values())


def tags_newly_wanted(materials, meshes):
    """Whether a mask now goes by polygon tags that meshes kept from an earlier reading were read without."""
    return tags_wanted(materials) and any('_mask_tags' not in mesh for mesh in meshes or () if mesh.get('faces'))


def polygon_tags(mesh):
    """Each surface polygon's Part and Selection Sets (their names joined by ;), in the order the scene reader counts
    polygons, of a Modo mesh (lx.object.Mesh): [(part, sets)]."""
    import lx
    import lxu.utils
    from .vertex_maps import NOT_SURFACE
    polygons = lx.object.Polygon(mesh.PolygonAccessor())
    tags = lx.object.StringTag(polygons)
    result = []
    for index in range(mesh.PolygonCount()):
        polygons.SelectByIndex(index)
        if lxu.utils.decodeID4(polygons.Type()) in NOT_SURFACE or polygons.VertexCount() < 3:
            continue
        held = []
        for kind in (lx.symbol.i_POLYTAG_PART, lx.symbol.i_POLYTAG_PICK):
            try:
                held.append(tags.Get(kind) or '')
            except LookupError:
                held.append('')
        result.append((held[0], ';'.join(sorted(word for word in held[1].split(';') if word))))
    return result


def face_tags(tags, ordinals):
    """polygon_tags for the faces of one shape, in its order (ordinals: which surface polygon each face is)."""
    parts, picks = [], []
    for ordinal in ordinals:
        part, sets = tags[ordinal] if 0 <= ordinal < len(tags) else ('', '')
        parts.append(part)
        picks.append(sets)
    return {'part': parts, 'pick': picks}


def coverage(scene, materials):
    """{attribute name: the identities of the items an item or particle mask holds} for the masks the materials ask for,
    as Modo renders them (mask_types.covered), with the instances of those items where the mask says so. Needs Modo."""
    from .mask_types import covered
    held = {}
    cache = {}
    everything = None
    for name, spec in wanted(materials).items():
        if spec['mode'] not in ('item', 'particle'):
            continue
        if everything is None:
            everything = list(scene.iterItems())
        ids = set()
        for word in spec['items']:
            found = [item for item in everything if item.id == word] or [item for item in everything if item.name == word]
            for item in found:
                ids |= covered(item, cache)
        if spec['instances']:
            for item in everything:
                if item.type != 'meshInst':
                    continue
                source, seen = item, set()
                while source is not None and source.type == 'meshInst' and source.id not in seen:
                    seen.add(source.id)
                    links = source.itemGraph('source').forward()
                    source = links[0] if len(links) == 1 else None
                if source is not None and source.id in ids:
                    ids.add(item.id)
        held[name] = ids
    return held


def _face_count(faces):
    return len(faces)


def _corner_values(faces, per_face):
    values = []
    for index in range(len(faces)):
        values.extend([[per_face[index]]] * len(faces[index]))
    return values


def apply(snapshot, warnings, covered=None):
    """Put on each mesh the numbers its graphs' Modo Mask nodes read (wanted): 1 in the mask, 0 out of it. covered:
    coverage()'s item sets (an item mask with none holds nothing)."""
    specs = wanted(snapshot.get('materials'))
    if not specs:
        return
    covered = covered or {}
    told = set()
    # Which materials read each mask: only the meshes that wear one of them carry its number.
    readers = {name: {tag for tag, material in (snapshot.get('materials') or {}).items() if name in wanted({tag: material})} for name in specs}
    for mesh in snapshot.get('meshes') or []:
        faces = mesh.get('faces')
        if not mesh.get('vertices') or not faces:
            continue
        item = str(mesh.get('identity') or mesh.get('name') or '').split('|')[0]
        worn = set(mesh.get('face_materials') or ()) | {mesh.get('material', '')}
        for name, spec in specs.items():
            if not worn & readers[name]:
                continue
            mode = spec['mode']
            if mode in ('item', 'particle'):
                held = covered.get(name, set())
                ids = mesh.get('instance_ids')
                if mesh.get('instances') and ids and len(ids) == len(mesh['instances']):
                    members = [1.0 if member(identity, held, spec, mesh) else 0.0 for identity in ids]
                    if len(set(members)) > 1:
                        rows = mesh.get('instance_attributes') or [[] for _ in ids]
                        mesh['instance_attributes'] = [[entry for entry in row if entry.get('name') != name]
                                                       + [{'name': name, 'type': 'float', 'value': value}] for row, value in zip(rows, members)]
                        if name not in told:
                            told.add(name)
                            warnings.append('Modo Mask by item: some copies of %s are in it and some not; MoonLightIPR shows '
                                            'them all as the first.' % mesh.get('name'))
                    _constant(mesh, name, members[0])
                else:
                    _constant(mesh, name, 1.0 if member(item, held, spec, mesh) else 0.0)
            elif mode == 'material':
                tags = mesh.get('face_materials')
                if tags and len(tags) == len(faces) and not mesh.get('evaluated_geometry'):
                    per_face = [1.0 if tag == spec['tag'] else 0.0 for tag in tags]
                    _per_face(mesh, name, faces, per_face)
                else:
                    _constant(mesh, name, 1.0 if mesh.get('_source_material', mesh.get('material')) == spec['tag'] else 0.0)
            else:
                tags = (mesh.get('_mask_tags') or {}).get(mode)
                if tags is not None and len(tags) == len(faces):
                    per_face = [1.0 if (tag == spec['tag'] if mode == 'part' else spec['tag'] in tag.split(';')) else 0.0 for tag in tags]
                    _per_face(mesh, name, faces, per_face)
                else:
                    # Read through Modo's evaluated geometry: a surface's polygons are not told apart, only its own Part where
                    # Modo's render cache split the mesh by it (as it does for a Shader Tree mask of that Part).
                    _constant(mesh, name, 1.0 if mode == 'part' and mesh.get('_part') == spec['tag'] else 0.0)
                    if (mode, spec['tag']) not in told:
                        told.add((mode, spec['tag']))
                        warnings.append("Modo Mask by %s %s: the scene is read through Modo's evaluated geometry (replicators, Scene "
                                        "Proxies, Alembic, instance overrides or masks by item), which does not say which polygons are in "
                                        "it; it holds only where Modo splits the surfaces by it." % ('Selection Set' if mode == 'pick' else 'Part', spec['tag']))


def member(identity, held, spec, mesh):
    """Whether an item (a mesh, an instance, a Replicator's copy: its identity, the source item first) is in an item
    mask (held: its items)."""
    source = str(identity).split('|')[0]
    if spec['mode'] == 'particle':
        return source in held and bool(mesh.get('instances') or mesh.get('evaluated_geometry'))
    return source in held


def _constant(mesh, name, value):
    mesh.setdefault('point_attributes', {})[name] = {'kind': 'float', 'values': [[float(value)]] * len(mesh['vertices'])}
    (mesh.get('corner_attributes') or {}).pop(name, None)


def _per_face(mesh, name, faces, per_face):
    if len(set(per_face)) <= 1:
        _constant(mesh, name, per_face[0] if per_face else 0.0)
        return
    mesh.setdefault('corner_attributes', {})[name] = {'kind': 'float', 'values': _corner_values(faces, per_face)}
    (mesh.get('point_attributes') or {}).pop(name, None)


# MoonRay (and XPU2, which reads the same scene): the nodes as maps.
def emit_node(kind, params, refs, path, definition, binding):
    """A node of NODES written for MoonRay (nodes.emit): its reference."""
    from .rdla import string, number, vector
    if kind == 'modo_driver':
        if 'value' in refs:
            return refs['value']
        value = params.get('value', [0.0, 0.0, 0.0])
        return definition('ModoTextureMap', path, {'foreground': vector(_triple(value), 'Rgb')})
    if kind == 'modo_vertex_map':
        name = str(params.get('vertex_map', '') or '')
        kind_of = int(params.get('type', 0))
        if kind_of == 1:
            return definition('AttributeMap', path, {'primitive_attribute_name': string(name), 'primitive_attribute_type': '3',
                                                    'default_value': 'Rgb(0,0,0)'})
        return _weight(name + '_alpha' if kind_of == 2 else name, path, definition, binding)
    if kind == 'modo_mask':
        mode = mode_name(params.get('mode', 0))
        if mode == 'weight':
            raw = _weight(str(params.get('vertex_map', '') or ''), path + '/weight', definition, binding)
            low = definition('OpMap', path + '/low', {'operation': '4', 'op1': binding(raw, 'Rgb'), 'op2': 'Rgb(0,0,0)'})
            value = definition('OpMap', path + '/high', {'operation': '5', 'op1': binding(low, 'Rgb'), 'op2': 'Rgb(1,1,1)'})
        else:
            value = _weight(attribute(mask_spec(params)), path + '/weight', definition, binding)
        return _shaped(value, bool(params.get('invert')), float(params.get('opacity', 1.0)), path, definition, binding, number)
    if kind == 'modo_falloff':
        return _falloff(params, path, definition, binding, number, vector)
    raise ValueError('Not a mask node: ' + kind)


def _triple(value):
    if isinstance(value, (int, float)):
        return [float(value)] * 3
    return [float(v) for v in value][:3]


def _weight(name, path, definition, binding):
    """A number the shape carries under name, as a Weight Map Texture reads it (gradients.emit): 0 where it has none."""
    from .rdla import string
    held = definition('AttributeMap', path + '/attribute', {'primitive_attribute_name': string(name), 'primitive_attribute_type': '0',
                                                           'default_value': 'Rgb(0,0,0)'})
    return definition('ModoTextureMap', path, {'mode': '7', 'component': '0', 'foreground': binding(held, 'Rgb')})


def _shaped(value, invert, opacity, path, definition, binding, number):
    if invert:
        value = definition('ModoTextureMap', path + '/invert', {'background': 'Rgb(1,1,1)', 'foreground': binding(value, 'Rgb'), 'blend': '3'})
    if opacity != 1.0:
        value = definition('ModoTextureMap', path + '/opacity', {'background': binding(value, 'Rgb'), 'foreground': 'Rgb(%s,%s,%s)' % ((number(opacity),) * 3),
                                                                'blend': '1'})
    return value


def falloff_frame(matrix):
    """(the locator's place, its three axes each over its length squared): a point's coordinate along axis k in the
    locator's space and size is (point - place) . axis_k."""
    matrix = [float(v) for v in matrix]
    if len(matrix) != 16:
        raise ValueError('Modo Falloff: its locator matrix is 16 numbers')
    place = matrix[12:15]
    axes = []
    for row in range(3):
        axis = matrix[row * 4:row * 4 + 3]
        length = sum(v * v for v in axis)
        if length < 1e-20:
            raise ValueError('Modo Falloff: its locator has no size')
        axes.append([v / length for v in axis])
    return place, axes


def falloff_at(params, point):
    """The falloff at a point of the world, worked out as the maps do (for tests and the editor)."""
    place, axes = falloff_frame(params.get('locator_matrix', IDENTITY))
    local = [sum((p - q) * a for p, q, a in zip(point, place, axis)) for axis in axes]
    shape = FALLOFF_SHAPES[int(params.get('shape', 0))]
    distance = {'cubic': max(abs(v) for v in local), 'spherical': math.sqrt(sum(v * v for v in local)),
                'linearX': abs(local[0]), 'linearY': abs(local[1]), 'linearZ': abs(local[2])}[shape]
    start, width = float(params.get('start', .5)), max(float(params.get('width', .5)), 1e-6)
    weight = min(1.0, max(0.0, (start + width - distance) / width))
    return 1.0 - weight if params.get('invert') else weight


def _falloff(params, path, definition, binding, number, vector):
    place, axes = falloff_frame(params.get('locator_matrix', IDENTITY))
    shape = FALLOFF_SHAPES[int(params.get('shape', 0))]
    start, width = float(params.get('start', .5)), max(float(params.get('width', .5)), 1e-6)
    rgb = lambda v: vector(_triple(v), 'Rgb')
    point = definition('AttributeMap', path + '/point', {'map_type': '1'})
    world = definition('TransformSpaceMap', path + '/world', {'input': binding(point, 'Rgb'), 'input_type': '0', 'from_space': '0', 'to_space': '2'})
    relative = definition('OpMap', path + '/relative', {'operation': '1', 'op1': binding(world, 'Rgb'), 'op2': rgb(place)})

    def along(index):
        dot = definition('OpMap', path + '/along%d' % index, {'operation': '8', 'op1': binding(relative, 'Rgb'), 'op2': rgb(axes[index])})
        return definition('ModoTextureMap', path + '/component%d' % index, {'mode': '7', 'component': '0', 'foreground': binding(dot, 'Rgb')})
    if shape.startswith('linear'):
        index = 'XYZ'.index(shape[-1])
        distance = definition('OpMap', path + '/distance', {'operation': '15', 'op1': binding(along(index), 'Rgb')})
    elif shape == 'cubic':
        parts = [definition('OpMap', path + '/abs%d' % i, {'operation': '15', 'op1': binding(along(i), 'Rgb')}) for i in range(3)]
        most = definition('OpMap', path + '/max01', {'operation': '4', 'op1': binding(parts[0], 'Rgb'), 'op2': binding(parts[1], 'Rgb')})
        distance = definition('OpMap', path + '/distance', {'operation': '4', 'op1': binding(most, 'Rgb'), 'op2': binding(parts[2], 'Rgb')})
    else:
        pieces = []
        for i in range(3):
            unit = [0.0, 0.0, 0.0]
            unit[i] = 1.0
            pieces.append(definition('ModoTextureMap', path + '/isolate%d' % i, {'background': binding(along(i), 'Rgb'), 'foreground': rgb(unit), 'blend': '1'}))
        joined = definition('ModoTextureMap', path + '/sum01', {'background': binding(pieces[0], 'Rgb'), 'foreground': binding(pieces[1], 'Rgb'), 'blend': '2'})
        joined = definition('ModoTextureMap', path + '/local', {'background': binding(joined, 'Rgb'), 'foreground': binding(pieces[2], 'Rgb'), 'blend': '2'})
        distance = definition('OpMap', path + '/distance', {'operation': '20', 'op1': binding(joined, 'Rgb')})
    left = definition('OpMap', path + '/left', {'operation': '1', 'op1': rgb(start + width), 'op2': binding(distance, 'Rgb')})
    scaled = definition('OpMap', path + '/scaled', {'operation': '2', 'op1': binding(left, 'Rgb'), 'op2': rgb(1.0 / width)})
    low = definition('OpMap', path + '/low', {'operation': '4', 'op1': binding(scaled, 'Rgb'), 'op2': rgb(0.0)})
    high = definition('OpMap', path + '/high', {'operation': '5', 'op1': binding(low, 'Rgb'), 'op2': rgb(1.0)})
    value = definition('ModoTextureMap', path + '/weight', {'mode': '7', 'component': '0', 'foreground': binding(high, 'Rgb')})
    if params.get('invert'):
        value = definition('ModoTextureMap', path, {'background': 'Rgb(1,1,1)', 'foreground': binding(value, 'Rgb'), 'blend': '3'})
    return value


# MoonLightIPR: the nodes as the rows its Compiler draws (moonlightipr_materials.graph_expression).
RGB_SUFFIX = '@rgb'


def ipr_leaf(graph, node, leaf):
    """A node of NODES as one row of MoonLightIPR ((layer, gain, offset)), or None where it is not one row. leaf is
    graph_expression's own, for what is wired into a Driver."""
    kind = node['type']
    params = node.get('parameters') or {}
    if kind == 'modo_driver':
        source = (node.get('inputs') or {}).get('value')
        if source is not None:
            return leaf(source)
        return (None, _triple(params.get('value', [0.0, 0.0, 0.0])))
    if kind == 'modo_vertex_map':
        kind_of = int(params.get('type', 0))
        if kind_of == 1:
            return None
        name = str(params.get('vertex_map', '') or '') + ('_alpha' if kind_of == 2 else '')
        return (_vmap_row(name, 0.0, 1.0), 1.0, 0.0)
    if kind == 'modo_mask':
        mode = mode_name(params.get('mode', 0))
        name = str(params.get('vertex_map', '') or '') if mode == 'weight' else attribute(mask_spec(params))
        opacity = float(params.get('opacity', 1.0))
        low, high = (opacity, 0.0) if params.get('invert') else (0.0, opacity)
        return (_vmap_row(name, low, high), 1.0, 0.0)
    if kind == 'modo_falloff':
        row = falloff_row(params)
        return None if row is None else (row, 1.0, 0.0)
    return None


def _vmap_row(name, low, high):
    return {'kind': 'gradient', 'gradient': {'input': '@vmap', 'vmap': name, 'label': 'the map ' + name, 'positions': [0.0, 1.0],
                                             'colors': [[low] * 3, [high] * 3]}}


def ipr_rows(node):
    """An RGB Vertex Map node as MoonLightIPR's rows: each colour channel a weight row of its own (with_weights reads
    name@rgb0..2), added. None for any other node."""
    params = node.get('parameters') or {}
    if node.get('type') != 'modo_vertex_map' or int(params.get('type', 0)) != 1:
        return None
    name = str(params.get('vertex_map', '') or '')
    rows = []
    for index in range(3):
        top = [0.0, 0.0, 0.0]
        top[index] = 1.0
        row = _vmap_row(name + RGB_SUFFIX + str(index), 0.0, 1.0)
        row['gradient']['colors'] = [[0.0, 0.0, 0.0], top]
        rows.append((row, 'normal' if index == 0 else 'add'))
    return rows


def ipr_gradient(graph, node, expression):
    """A Modo Procedural gradient whose Input is a Vertex Map or a Driver node as MoonLightIPR's rows: (rows to put first,
    the gradient's own row). A Driver's chain comes first as rows of its driver (expression: graph_expression), which the
    gradient row reads as a channel, as a Shader Tree Gradient on a driver does. None for any other node."""
    params = node.get('parameters') or {}
    if node.get('type') != 'modo_procedural' or not params.get('gradient'):
        return None
    try:
        data = json.loads(params['gradient'])
    except (TypeError, ValueError):
        return None
    if int(params.get('output', 0)) == 1:
        if 'alpha' not in data:
            return [], {'kind': 'constant', 'value': [1.0, 1.0, 1.0]}
        data = dict(data, colors=[[a] * 3 for a in data['alpha']])
    data.pop('alpha', None)
    source = (node.get('inputs') or {}).get('input')
    wired = (graph.get('nodes') or {}).get(source) if source is not None else None
    rows = []
    if wired is not None and wired.get('type') == 'modo_vertex_map':
        held = wired.get('parameters') or {}
        kind_of = int(held.get('type', 0))
        name = str(held.get('vertex_map', '') or '') + {0: '', 1: RGB_SUFFIX + '0', 2: '_alpha'}.get(kind_of, '')
        data.update(input='@vmap', vmap=name)
    elif wired is not None and wired.get('type') == 'modo_driver':
        effect = DRIVERS[int((wired.get('parameters') or {}).get('driver', 0))]
        inner = (wired.get('inputs') or {}).get('value')
        if inner is not None:
            rows = expression(graph, inner, effect)
            if not rows:
                return None
        else:
            rows = [{'kind': 'constant', 'value': _triple((wired.get('parameters') or {}).get('value', [0.0] * 3)), 'effect': effect,
                     'blend': 'normal', 'opacity': 1.0, 'identity': '%s:driver' % source}]
        data['input'] = effect
    elif wired is not None or not str(data.get('input', '')).startswith('@'):
        return None
    return rows, {'kind': 'gradient', 'gradient': data}


def falloff_row(params):
    """A Modo Falloff node as a MoonLightIPR sample row ('@sample': the point's place along the locator's axis, or its
    distance from it): Linear and, for a locator of one size along its axes, Spherical. None for Cubic (no one row)."""
    place, axes = falloff_frame(params.get('locator_matrix', IDENTITY))
    shape = FALLOFF_SHAPES[int(params.get('shape', 0))]
    start, width = float(params.get('start', .5)), max(float(params.get('width', .5)), 1e-6)
    end = start + width
    inside, outside = (0.0, 1.0) if params.get('invert') else (1.0, 0.0)
    if shape.startswith('linear'):
        axis = axes['XYZ'.index(shape[-1])]
        # Signed along the axis: in from -end, flat from -start to start, out to end.
        positions = [0.0, (end - start) / (2 * end), (end + start) / (2 * end), 1.0] if start > 0 else [0.0, .5, 1.0]
        colours = [outside, inside, inside, outside] if start > 0 else [outside, inside, outside]
        data = {'input': '@sample', 'sample': 'textureLocal', 'span': [-end, end], 'locator': list(place), 'axis_vector': list(axis),
                'wrap': False, 'positions': positions, 'colors': [[c] * 3 for c in colours]}
    elif shape == 'spherical':
        sizes = [1.0 / math.sqrt(sum(v * v for v in axis)) for axis in axes]
        if max(sizes) - min(sizes) > 1e-6 * max(sizes):
            return None
        size = sizes[0]
        data = {'input': '@sample', 'sample': 'distance', 'span': [start * size, end * size], 'locator': list(place),
                'positions': [0.0, 1.0], 'colors': [[inside] * 3, [outside] * 3]}
    else:
        return None
    data['label'] = 'a falloff'
    return {'kind': 'gradient', 'gradient': data}


# The conversion's hooks (shader_tree_transfer).
def mask_value(builder, info):
    """A nested Shader Tree mask as a value of the graph, 1 where a surface is in it: a Modo Mask node (two, multiplied,
    where it goes by both a polygon tag and items, as Modo takes both). info, read from the mask item:
      'identity'   the mask item's identity (its nodes are tagged with it);
      'name'       its name, for the node's label;
      'tag_type'   its Polygon Tag Type (mask_types.tag_kind of its ptyp): 'material', 'part', 'selection set' or '';
      'tag'        its Polygon Tag;
      'items'      the identities of the items it is for (mask_types.mask_items), [] for none;
      'instances'  its Apply to Instances (instApply).
    The same mask for several layers gives the same node. ('c', [1, 1, 1]) where the mask holds every surface."""
    from .shader_tree_transfer import node_id
    owner = info['identity']
    factors = []
    kind = TAG_TYPES.get(str(info.get('tag_type') or '').strip().lower())
    label = info.get('name') or owner
    if kind and info.get('tag'):
        factors.append(_mask_node(builder, owner, 'mask_tag', {'mode': MASK_MODES.index(kind), 'tag': str(info['tag'])}, label))
    if info.get('items'):
        factors.append(_mask_node(builder, owner, 'mask_items', {'mode': 0, 'items': ';'.join(sorted(info['items'])),
                                                                 'instances': bool(info.get('instances'))}, label))
    if not factors:
        return ('c', [1.0, 1.0, 1.0])
    if len(factors) == 1:
        return factors[0]
    identity = node_id(owner, 'mask_both')
    if identity in builder.nodes:
        return ('n', identity)
    return builder.add(owner, 'mask_both', 'multiply', {}, {'in1': factors[0], 'in2': factors[1]})


# A mask item's Polygon Tag Type, as Modo's channel or mask_types.tag_kind gives it, as a Modo Mask's mode.
TAG_TYPES = {'material': 'material', 'matr': 'material', 'part': 'part', 'pick': 'pick', 'selection': 'pick', 'selection set': 'pick',
             'selectionset': 'pick'}


def _mask_node(builder, owner, role, parameters, label):
    from .shader_tree_transfer import node_id
    identity = node_id(owner, role)
    if identity in builder.nodes:
        return ('n', identity)
    return builder.add(owner, role, 'modo_mask', parameters, label=label + ' (mask)', data={'mask': owner})


def driver_node(builder, material, effect, value):
    """A driver's chain (value: what the layers setting it come to) as a Driver node, the one every Gradient reading it is
    wired to. The same chain gives the same node."""
    from .shader_tree_transfer import node_id
    if effect not in DRIVERS:
        raise ValueError('not a driver: %s' % effect)
    role = 'driver_%s_%s' % (effect, hashlib.sha1(repr(value).encode('utf-8')).hexdigest()[:8])
    identity = node_id(material, role)
    if identity in builder.nodes:
        return ('n', identity)
    return builder.add(material, role, 'modo_driver', {'driver': DRIVERS.index(effect)}, {'value': value},
                       label='Driver ' + effect[-1])


def _refuse(text):
    from .shader_tree_transfer import Refused
    raise Refused(text)


def check_driver_layer(layer, effect):
    """A layer that sets a driver: as any image or constant layer (shader_tree_transfer.check), with no output of its own."""
    if layer.get('kind') not in ('imageMap', 'constant', 'gradient'):
        _refuse('a %s layer setting %s: only image, constant and gradient layers move' % (layer.get('kind'), effect))


def check_gradient(layer, effect):
    data = layer.get('gradient') or {}
    if effect in ('normal', 'bump'):
        _refuse('a Gradient on the %s' % effect)
    if data.get('input') == '@vmap' and not data.get('vmap'):
        _refuse('a Weight Map Texture with no weight map chosen')
    if data.get('input') == '@vmap' and data.get('occlusion'):
        _refuse('an Occlusion texture')
    if data.get('input') == '@vmap' and str(data.get('vmap', '')).startswith('__modo_'):
        _refuse('a Variation Texture')
    if layer.get('groups') and any(group.get('invert') for group in layer['groups']):
        _refuse('its group is inverted')


def gradient_foreground(builder, layer, effect, alpha_of=None, drivers=None):
    """A Gradient on a weight map (Modo's Weight Map Texture) or on a driver: a Modo Procedural of the gradient, its Input
    wired to a Vertex Map node or to the driver's Driver node; with its alpha as the mask where it has one. drivers: the
    effects' values as the layers beneath leave them (shader_tree_transfer.build's current); a driver no layer has set
    is 0, as graph.defaults_for has it."""
    data = dict(layer['gradient'])
    source = data.get('input')
    identity = layer['identity']
    if source == '@vmap':
        reading = builder.add(identity, 'vertex_map', 'modo_vertex_map', {'vertex_map': str(data.get('vmap', '')), 'type': 0},
                              label=data.get('vmap') or 'Vertex Map')
        # Read through the node's Input (VERTEX_INPUT): the weight, as the Weight Map Texture reads it.
        data['input'] = VERTEX_INPUT
    elif source in DRIVERS:
        held = (drivers or {}).get(source, ('c', [0.0, 0.0, 0.0]))
        reading = driver_node(builder, identity, source, held)
    else:
        _refuse('a Gradient on %s' % source)
    data.pop('vmap', None)
    colour = builder.add(identity, 'gradient', 'modo_procedural', {'gradient': json.dumps(data, sort_keys=True), 'output': 0},
                         {'input': reading}, label=layer.get('name') or identity, data={'effect': effect})
    mask = None
    if 'alpha' in data:
        mask = builder.add(identity, 'gradient_alpha', 'modo_procedural', {'gradient': json.dumps(data, sort_keys=True), 'output': 1},
                           {'input': reading}, label=(layer.get('name') or identity) + ' alpha')
    if layer.get('invert'):
        colour = builder.add(identity, 'invert', 'subtract', {}, {'in1': ('c', [1.0, 1.0, 1.0]), 'in2': colour})
    return colour, mask


CHECKS = {'gradient:@vmap': check_gradient, **{'gradient:' + d: check_gradient for d in DRIVERS},
          **{'effect:' + d: check_driver_layer for d in DRIVERS}}
FOREGROUNDS = {'gradient:@vmap': gradient_foreground, **{'gradient:' + d: gradient_foreground for d in DRIVERS}}


def layer_key(layer):
    """The key of CHECKS and FOREGROUNDS a layer goes by, or None."""
    if layer.get('kind') == 'gradient':
        key = 'gradient:' + str((layer.get('gradient') or {}).get('input'))
        return key if key in FOREGROUNDS else None
    return None


# The graph editor: the scene's vertex maps to choose from.
def map_choices(item=None):
    """(label, name) of the weight and colour maps of the meshes a material is on (all the scene's meshes where it is on
    none), an RGBA map's alpha as name_alpha, as the Vertex Map node and the Weight Map mask read them."""
    names = []
    try:
        import modo
        meshes = []
        if item is not None:
            from .node_editor import material_meshes
            meshes = list(material_meshes(item))
        if not meshes:
            meshes = list(modo.Scene().items('mesh', superType=False))
        from .vertex_maps import names_of
        for mesh in meshes:
            for name in names_of(modo.meshgeometry.MeshProvider.meshFromMeshChannel(mesh._item, 'deformed')):
                if name not in names:
                    names.append(name)
    except Exception:
        pass
    return [('(none)', '')] + [(name, name) for name in sorted(names, key=str.casefold)]
