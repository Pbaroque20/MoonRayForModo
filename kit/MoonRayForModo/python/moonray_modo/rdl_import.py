"""A MoonRay scene (RDL) as editable Modo content.

MoonRay's own reader opens the file in a separate process and hands every object over with its class and
attributes. plan() decides, without touching Modo, what each becomes; apply() makes it.

What an object becomes:
  a mesh                      a Modo mesh, with its place in the world as the item's transform, its UVs and its parts
  an instancer                Modo instances of the meshes it repeats, however deeply instancers nest
  curves                      a Modo mesh of curves, rendered as tubes
  a material and its maps     a MoonRay material in the Shader Tree holding the whole graph, displacement included
  a light, a light filter, a volume, a shape or a camera MoonRay has and Modo has not
                              the MoonRay item of that class, with every attribute the scene set
  a perspective camera        a Modo camera
  the scene's settings and outputs   the plugin's render settings and custom outputs
Anything that has no home in Modo is named in the notices, so nothing is left out silently."""
import math
import re
import uuid
from pathlib import Path

IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
# More instances than this of one instancer are not made into Modo items, which would be too many to work with.
INSTANCE_LIMIT = 20000
LINE, BEZIER, BSPLINE = 0, 1, 2
pending = None
result = ''


def transform(point, matrix):
    return [sum(point[j] * matrix[j * 4 + i] for j in range(3)) + matrix[12 + i] for i in range(3)]


def product(a, b):
    """a then b, for matrices that move a row vector: the order MoonRay writes them in."""
    return [sum(a[row * 4 + k] * b[k * 4 + col] for k in range(4)) for row in range(4) for col in range(4)]


def placed(position, orientation=None, scale=None):
    """The matrix of an instance given as a position, a turn (a quaternion x y z w) and a scale, as MoonRay builds it."""
    x, y, z, w = orientation or (0.0, 0.0, 0.0, 1.0)
    length = math.sqrt(x * x + y * y + z * z + w * w)
    if length < 1e-12:
        x, y, z, w = 0.0, 0.0, 0.0, 1.0
    else:
        x, y, z, w = x / length, y / length, z / length, w / length
    rows = [[1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y)],
            [2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x)],
            [2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y)]]
    sizes = scale or (1.0, 1.0, 1.0)
    return [value for row, size in zip(rows, sizes) for value in [v * size for v in row] + [0.0]] + list(position) + [1.0]


def followed(points, kind, steps=8):
    """The path a curve takes through its control points, as points along it: MoonRay's cubic B-spline or Bezier.
    A Modo curve of the same points would not take the same path, so the path itself is what is imported."""
    if kind == LINE:
        return [list(p) for p in points]
    if kind == BSPLINE:
        spans = [points[i:i + 4] for i in range(len(points) - 3)]
        weights = lambda t: ((1 - t) ** 3 / 6, (3 * t ** 3 - 6 * t ** 2 + 4) / 6, (-3 * t ** 3 + 3 * t ** 2 + 3 * t + 1) / 6, t ** 3 / 6)
    else:
        spans = [points[i:i + 4] for i in range(0, len(points) - 3, 3)]
        weights = lambda t: ((1 - t) ** 3, 3 * t * (1 - t) ** 2, 3 * t * t * (1 - t), t ** 3)
    if not spans:
        return [list(p) for p in points]
    path = []
    for index, span in enumerate(spans):
        for step in range(steps + (index == len(spans) - 1)):
            w = weights(step / steps)
            path.append([sum(w[k] * span[k][axis] for k in range(4)) for axis in range(3)])
    return path


def decomposed(matrix):
    """(position, rows of a pure turn, scale) if the matrix is a move, a turn and a scale along the axes, which a Modo
    item's transform can hold; None if it shears or mirrors."""
    rows = [matrix[i * 4:i * 4 + 3] for i in range(3)]
    sizes = [math.sqrt(sum(v * v for v in row)) for row in rows]
    if any(size < 1e-12 for size in sizes):
        return None
    turn = [[v / size for v in row] for row, size in zip(rows, sizes)]
    if any(abs(sum(a * b for a, b in zip(turn[i], turn[j]))) > 1e-4 for i, j in ((0, 1), (0, 2), (1, 2))):
        return None
    cross = [turn[0][1] * turn[1][2] - turn[0][2] * turn[1][1], turn[0][2] * turn[1][0] - turn[0][0] * turn[1][2], turn[0][0] * turn[1][1] - turn[0][1] * turn[1][0]]
    if sum(a * b for a, b in zip(cross, turn[2])) < 0:
        return None
    return list(matrix[12:15]), turn, sizes


def checked_matrix(matrix, owner):
    if len(matrix) != 16 or any(not math.isfinite(v) for v in matrix):
        raise ValueError('Invalid transform: ' + owner)
    return list(matrix)


def graph(root, objects, base, warnings, displacement=None):
    """A material and everything wired into it, as a node graph the plugin's materials hold."""
    from . import nodes, shader_library
    found = {'version': 1, 'root': root, 'nodes': {}}

    def visit(name):
        if name in found['nodes']:
            return
        if len(found['nodes']) >= 1000:
            raise ValueError('Imported material exceeds node limit')
        record = objects[name]
        kind = record['type']
        schema = nodes.specs(kind)
        node = {'type': kind, 'parameters': {}, 'inputs': {}, 'position': [len(found['nodes']) * 180, 0]}
        found['nodes'][name] = node
        for key, spec in schema.items():
            if key not in record.get('attributes', {}):
                continue
            value = record['attributes'][key]
            binding = record.get('bindings', {}).get(key)
            target = binding or (value if spec['type'] == 'SceneObject*' and isinstance(value, str) else None)
            if target:
                if target not in objects or not nodes.connectable(kind, key):
                    warnings.append(name + ': the connection into ' + key + ' is not one the plugin can hold')
                    continue
                visit(target)
                node['inputs'][key] = target
                if spec['type'] == 'SceneObject*':
                    continue
            if key in record.get('files', []) and isinstance(value, str) and value:
                path = Path(value)
                value = str((base / path).resolve()) if not path.is_absolute() else str(path)
                if not Path(value).is_file() and '<UDIM>' not in value:
                    warnings.append('Missing asset: ' + value)
            try:
                node['parameters'][key] = shader_library.typed(value, spec)
            except ValueError as exc:
                warnings.append(name + ' / ' + key + ': ' + str(exc))
    visit(root)
    if displacement:
        visit(displacement)
        found['displacement'] = displacement
    return nodes.validate(found)


def short(name):
    """A scene object's name as an item is called: the last step of its path."""
    return name.rstrip('/').rsplit('/', 1)[-1] or name


def authored(record):
    """The attributes the scene set. An older reader does not say, and then every attribute counts."""
    return set(record['authored']) if 'authored' in record else set(record.get('attributes', {}))


def plan(document, path):
    if document.get('version') != 1 or not isinstance(document.get('objects'), list):
        raise ValueError('Invalid RDL conversion document')
    from . import entities, options, outputs, shader_library
    objects = {v['name']: v for v in document['objects']}
    catalog = entities.catalog()
    warnings, meshes, curves, instances, items, materials, cameras = [], [], [], [], [], {}, []
    base = Path(path).resolve().parent
    variables = next((v for v in objects.values() if v['type'] == 'SceneVariables'), {'attributes': {}})
    scene = variables.get('attributes', {})
    layer = objects.get(scene.get('layer'), next((v for v in objects.values() if v['type'] == 'Layer'), {})).get('attributes', {})

    # Names: every item made is called by the last step of the object's path, told apart where two would match.
    labels, taken = {}, set()

    def label(name):
        if name not in labels:
            wanted, count = short(name), 1
            chosen = wanted
            while chosen in taken or ',' in chosen:
                count += 1
                chosen = '%s %d' % (wanted.replace(',', ' '), count)
            taken.add(chosen)
            labels[name] = chosen
        return labels[name]

    # What the layer assigns to each shape and part of a shape.
    rows = max((len(layer.get(key, [])) for key in ('geometries', 'parts', 'surface_shaders')), default=0)
    column = lambda key: list(layer.get(key, [])) + [None] * rows
    assigned = {}
    for index in range(rows):
        geometry, part = column('geometries')[index], column('parts')[index] or ''
        if geometry is None:
            continue
        assigned[(geometry, part)] = {key: column(source)[index] for key, source in (
            ('surface', 'surface_shaders'), ('displacement', 'displacements'), ('volume', 'volume_shaders'), ('lights', 'lightsets'),
            ('shadows', 'shadowsets'), ('filters', 'lightfiltersets'), ('receivers', 'shadowreceiversets'))}
    all_lights = {name for name, record in objects.items() if catalog.get(record['type'], {}).get('category') == 'light'}
    for (geometry, part), row in assigned.items():
        members = set(objects.get(row['lights'], {}).get('attributes', {}).get('lights', [])) if row['lights'] else set()
        if all_lights and row['lights'] and members != all_lights:
            warnings.append('Light linking is not imported: %s is lit by %d of the %d lights.' % (short(geometry) + (' / ' + part if part else ''), len(members), len(all_lights)))
        for key, what in (('shadows', 'shadow set'), ('filters', 'light filter set'), ('receivers', 'shadow receiver set')):
            if row[key]:
                warnings.append('%s: its %s is not imported.' % (short(geometry), what))

    def material(geometry, part, owner=None):
        """The key of the material a part of a shape is rendered with, made on first use; None for no material."""
        # The shape's own assignment first, then that of the instancer repeating it.
        rows = [assigned.get(key) for key in ((geometry, part), (geometry, ''), (owner, part), (owner, ''))]
        row = next((r for r in rows if r and r['surface']), None)
        if not row:
            return None
        surface, displacement = row['surface'], row['displacement']
        if surface not in objects or objects[surface]['type'] not in shader_library.catalog():
            warnings.append('%s: its material %s is of a class the plugin has no material for.' % (short(geometry), short(str(surface))))
            return None
        key = surface if not displacement else surface + '|' + displacement
        if key not in materials:
            try:
                materials[key] = {'name': short(surface), 'graph': graph(surface, objects, base, warnings, displacement)}
            except (ValueError, KeyError) as exc:
                if displacement:
                    try:
                        materials[key] = {'name': short(surface), 'graph': graph(surface, objects, base, warnings)}
                        warnings.append('%s: its displacement %s could not be held (%s).' % (short(surface), short(displacement), exc))
                        return key
                    except (ValueError, KeyError):
                        pass
                warnings.append(surface + ': material graph could not be converted: ' + str(exc))
                materials[key] = None
        return key if materials[key] else None

    def volume_of(geometry):
        row = assigned.get((geometry, ''))
        return row['volume'] if row and row['volume'] in objects else None

    def note_motion(record):
        moving = [key for key in record.get('close', {}) if key != 'node_xform']
        if 'node_xform' in record.get('close', {}):
            warnings.append('%s moves over the shutter; its place at shutter open is imported.' % short(record['name']))
        if moving or record.get('attributes', {}).get('vertex_list_1'):
            warnings.append('%s changes shape over the shutter; its shape at shutter open is imported.' % short(record['name']))

    def carried(record):
        """What a shape's UserData holds: [(name, type, values)]."""
        from . import primitive_attributes
        found = []
        for reference in record.get('attributes', {}).get('primitive_attributes') or []:
            held = objects.get(reference)
            if not held or held['type'] != 'UserData':
                continue
            read = primitive_attributes.from_userdata(held)
            if not read:
                warnings.append('%s: the values in %s are of a kind the plugin does not hold' % (short(record['name']), short(reference)))
            found += read
        return found

    def picked(values, index=None, count=None):
        """The attributes of one thing out of what a shape carries: those with one value for everything, and with index,
        those with one value for each of count things."""
        return [{'name': name, 'type': kind, 'value': held[0] if len(held) == 1 else held[index]}
                for name, kind, held in values if len(held) == 1 or (index is not None and len(held) == count)]

    def merged(own, outer):
        """A shape's attributes under those of the instancer that repeats it, whose values are the ones MoonRay uses."""
        names = {entry['name'] for entry in outer}
        return [entry for entry in own if entry['name'] not in names] + list(outer)

    def mesh(record, owner=None):
        """A mesh in its own space, once however many times it is placed. Returns its name in the plan."""
        key = record['name']
        if key in mesh.made:
            return mesh.made[key]
        a = record.get('attributes', {})
        vertices, counts, indices = a.get('vertex_list_0', a.get('vertex_list', [])), a.get('face_vertex_count', []), a.get('vertices_by_index', [])
        if not vertices or not counts:
            mesh.made[key] = None
            return None
        if any(type(n) != int or n < 3 for n in counts) or sum(counts) != len(indices):
            raise ValueError('Invalid face counts: ' + record['name'])
        if any(type(i) != int or i < 0 or i >= len(vertices) for i in indices):
            raise ValueError('Invalid point index: ' + record['name'])
        if any(len(v) != 3 or any(not math.isfinite(x) for x in v) for v in vertices):
            raise ValueError('Invalid vertex coordinates: ' + record['name'])
        tags = [material(record['name'], '', owner)] * len(counts)
        offset = 0
        for part, count in zip(a.get('part_list', []), a.get('part_face_count_list', [])):
            chosen = material(record['name'], part, owner)
            for face in a.get('part_face_indices', [])[offset:offset + count]:
                if not 0 <= face < len(tags):
                    raise ValueError('Invalid material part face index: ' + record['name'])
                tags[face] = chosen if chosen is not None or (record['name'], part) in assigned else tags[face]
            offset += count
        uv = a.get('uv_list', [])
        if uv and len(uv) not in (len(vertices), len(indices)):
            warnings.append(short(record['name']) + ': its UVs are neither one for each point nor one for each corner, and are left out')
            uv = []
        normals = a.get('normal_list', [])
        if normals and len(normals) not in (len(vertices), len(indices)):
            normals = []
        faces, offset = [], 0
        for count in counts:
            faces.append(indices[offset:offset + count])
            offset += count
        if a.get('subd_crease_indices') or a.get('subd_corner_indices'):
            warnings.append(short(record['name']) + ': subdivision crease and corner weights are not imported')
        if volume_of(record['name']):
            warnings.append(short(record['name']) + ': the volume inside it is not imported; MoonRay volumes go in a MoonRay shape')
        for name_, kind_, held in carried(record):
            if len(held) > 1:
                warnings.append('%s: %s differs from face to face or point to point, which is not imported; only one value for a whole item is' % (short(record['name']), name_))
        note_motion(record)
        name = label(record['name'])
        meshes.append({'name': name, 'vertices': vertices, 'faces': faces, 'uv': uv, 'normals': normals, 'tags': tags, 'subd': bool(a.get('is_subd', False)),
                       'matrix': None, 'render': False, 'attributes': []})
        mesh.made[key] = name
        return name
    mesh.made = {}

    def strands(record, matrix, outer=()):
        a = record.get('attributes', {})
        counts, points, radii = a.get('curves_vertex_count', []), a.get('vertex_list_0', []), a.get('radius_list', [])
        if not counts or sum(counts) != len(points) or any(type(n) != int or n < 2 for n in counts):
            raise ValueError('Invalid curve counts: ' + record['name'])
        kind = int(a.get('curve_type', 0))
        if kind not in (LINE, BEZIER, BSPLINE):
            warnings.append('%s: curve type %d is imported as straight lines' % (short(record['name']), kind))
            kind = LINE
        lines, offset, roots, tips = [], 0, [], []
        for count in counts:
            lines.append(followed(points[offset:offset + count], kind))
            if len(radii) == len(points):
                roots.append(radii[offset])
                tips.append(radii[offset + count - 1])
            offset += count
        if len(radii) == len(counts) and len(radii) != len(points):
            # One radius for each curve.
            roots, tips = list(radii), list(radii)
        elif radii and len(radii) != len(points):
            warnings.append(short(record['name']) + ': its radii are neither one for each point nor one for each curve; the first is used throughout')
            roots, tips = [radii[0]], [radii[0]]
        mean = lambda values: sum(values) / len(values) if values else 0.001
        if len(lines) > 64 and roots and (max(roots) - min(roots) > 1e-6 * max(roots) or max(tips) - min(tips) > 1e-6 * max(max(tips), 1e-9)):
            warnings.append(short(record['name']) + ': its curves differ in width; all are given the average root and tip width')
        note_motion(record)
        values = carried(record)
        # Curves that differ in what they carry, or in width, are imported as an item each, so that each keeps its own.
        apart = any(len(held) == len(lines) and len(held) > 1 for name_, kind_, held in values) or (len(roots) == len(lines) and (max(roots) - min(roots) > 1e-6 * max(roots) or max(tips) - min(tips) > 1e-6 * max(max(tips), 1e-9)))
        for index in (range(len(lines)) if apart and len(lines) <= 64 else [None]):
            curves.append({'name': label(record['name']) if index is None else label('%s %d' % (record['name'], index + 1)),
                           'lines': lines if index is None else [lines[index]], 'kind': kind, 'round': int(a.get('curves_subtype', 0)) == 1, 'matrix': matrix,
                           'material': material(record['name'], ''), 'attributes': merged(picked(values, index, len(lines)), outer),
                           'root_mm': (mean(roots) if index is None else roots[index]) * 2000.0, 'tip_mm': (mean(tips) if index is None else tips[index]) * 2000.0})

    def entity(record, matrix, name=None, owner=None, outer=()):
        """A MoonRay item of the object's class, holding the attributes the scene set."""
        kind, spec = record['type'], catalog[record['type']]['attributes']
        a, parameters = record.get('attributes', {}), {}
        for key in sorted(authored(record)):
            if key == 'node_xform' or key not in spec or key not in a:
                continue
            value = a[key]
            if key in record.get('bindings', {}):
                warnings.append('%s: the map wired into %s is not imported; MoonRay items hold values only' % (short(record['name']), key))
            if spec[key]['type'].startswith('SceneObject'):
                names = [value] if isinstance(value, str) else [v for v in (value or []) if v]
                held = [label(v) for v in names if v in objects and objects[v]['type'] in catalog]
                if len(held) != len(names):
                    warnings.append('%s: %s names something that is not a MoonRay item and is left out' % (short(record['name']), key))
                if not held:
                    continue
                value = held[0] if spec[key]['type'] == 'SceneObject*' else held
            elif key in record.get('files', []) and isinstance(value, str) and value:
                file = Path(value)
                value = str((base / file).resolve()) if not file.is_absolute() else str(file)
                if not Path(value).is_file() and '<UDIM>' not in value:
                    warnings.append('Missing asset: ' + value)
            if 'default' in spec[key] and value == spec[key]['default']:
                continue
            parameters[key] = value
        for key in list(parameters):
            try:
                entities.validate(kind, {key: parameters[key]})
            except ValueError as exc:
                warnings.append('%s / %s: %s' % (short(record['name']), key, exc))
                del parameters[key]
        if record.get('unsupported_attributes'):
            unread = [key for key in record['unsupported_attributes'] if key in spec]
            if unread:
                warnings.append('%s: %s could not be read' % (short(record['name']), ', '.join(unread)))
        made = {'name': name or label(record['name']), 'class': kind, 'matrix': matrix, 'parameters': parameters, 'material': None, 'volume': None,
                'attributes': merged(picked(carried(record)), outer) if catalog[kind]['category'] == 'geometry' else []}
        parameters.pop('primitive_attributes', None)
        if catalog[kind]['category'] == 'geometry':
            made['material'] = material(record['name'], '', owner)
            volume = volume_of(owner or record['name']) or volume_of(record['name'])
            if volume and objects[volume]['type'] in catalog:
                made['volume'] = label(volume)
            elif volume:
                warnings.append('%s: its volume %s is of a class the plugin has no item for' % (short(record['name']), short(volume)))
        if kind == 'EnvLight':
            # It is the scene's environment; Modo's own would be added to it.
            parameters['modo_replace_environment'] = True
        if 'node_xform' in record.get('close', {}):
            warnings.append('%s moves over the shutter; its place at shutter open is imported.' % made['name'])
        items.append(made)
        return made

    def place(name, matrix, title, owner=None, depth=0, outer=()):
        """Put one object into the scene at a matrix: a mesh, a MoonRay shape, curves, or everything an instancer repeats."""
        record = objects.get(name)
        if record is None:
            return
        kind, a = record['type'], record.get('attributes', {})
        if depth > 8:
            warnings.append(short(name) + ': instancers nested more than eight deep are not followed')
            return
        if kind != 'RdlInstancerGeometry' and not any(row['surface'] or row['volume'] for (geometry, part), row in assigned.items() if geometry in (name, owner)):
            # MoonRay leaves out a shape the layer gives no material; brought in, it would be in the picture where it was not.
            warnings.append('%s is given no material by the scene, so MoonRay does not render it; it is not imported.' % short(name))
            return
        if kind == 'RdlMeshGeometry':
            source = mesh(record, owner)
            if source:
                instances.append({'name': title, 'source': source, 'matrix': matrix, 'attributes': merged(picked(carried(record)), outer)})
        elif kind == 'RdlCurveGeometry':
            strands(dict(record, name=name), matrix, outer) if title == label(name) else warnings.append(short(name) + ': instanced curves are not imported')
        elif kind == 'RdlInstancerGeometry':
            repeated(record, matrix, title, depth, outer)
        elif kind in catalog and catalog[kind]['category'] == 'geometry':
            entity(record, matrix, title, owner, outer)
        else:
            warnings.append('%s: %s has no counterpart in Modo and is not imported' % (short(name), kind))

    def repeated(record, parent, title, depth, outer=()):
        a, name = record.get('attributes', {}), record['name']
        references = [r for r in a.get('references', [])]
        if not references:
            warnings.append(short(name) + ': an instancer that repeats nothing')
            return
        method = int(a.get('method', 0))
        if method == 2:
            transforms = [checked_matrix(m, name) for m in a.get('xform_list', [])]
        elif method == 0:
            positions, turns, sizes = a.get('positions', []), a.get('orientations', []), a.get('scales', [])
            if 'orientations' in record.get('unsupported_attributes', []):
                warnings.append(short(name) + ': the turn of each instance could not be read; rebuild the scene reader (tools/build_rdl_reader.py)')
            transforms = [placed(p, turns[i] if len(turns) == len(positions) else None, sizes[i] if len(sizes) == len(positions) else None)
                          for i, p in enumerate(positions)]
        else:
            warnings.append('%s: instancing method %d is not imported' % (short(name), method))
            return
        indices, disabled = a.get('ref_indices', []), set(a.get('disable_indices', []))
        if not transforms and indices:
            transforms = [list(IDENTITY)] * len(indices)
        if a.get('point_file'):
            warnings.append(short(name) + ': instances read from a point file are not imported')
        use_indices = len(indices) == len(transforms)
        if indices and not use_indices:
            warnings.append(short(name) + ': ref_indices does not match the instances; the first prototype is used, as MoonRay does')
        if len(transforms) > INSTANCE_LIMIT:
            warnings.append('%s: only the first %d of its %d instances are imported' % (short(name), INSTANCE_LIMIT, len(transforms)))
            transforms = transforms[:INSTANCE_LIMIT]
        values, total = carried(record), len(transforms)
        own = checked_matrix(a.get('node_xform', IDENTITY), name)
        for index, matrix in enumerate(transforms):
            if index in disabled:
                continue
            chosen = indices[index] if use_indices else 0
            if chosen < 0:
                continue
            reference = references[chosen if chosen < len(references) else 0]
            if reference not in objects:
                continue
            matrix = product(product(matrix, own), parent)
            if a.get('use_reference_xforms', True):
                matrix = product(checked_matrix(objects[reference].get('attributes', {}).get('node_xform', IDENTITY), reference), matrix)
            place(reference, matrix, '%s %d' % (title, index + 1), name, depth + 1, merged(picked(values, index, total), outer))

    # A shape an instancer repeats is not in the picture itself, only where the instancer puts it.
    referenced = {name for v in objects.values() if v['type'] == 'RdlInstancerGeometry' for name in v.get('attributes', {}).get('references', [])}
    for name, record in objects.items():
        kind, a = record['type'], record.get('attributes', {})
        try:
            if kind in ('RdlMeshGeometry', 'RdlCurveGeometry', 'RdlInstancerGeometry') or (kind in catalog and catalog[kind]['category'] == 'geometry'):
                if name in referenced:
                    continue
                matrix = checked_matrix(a.get('node_xform', IDENTITY), name)
                if kind == 'RdlInstancerGeometry':
                    repeated(record, list(IDENTITY), label(name), 0)
                else:
                    place(name, matrix, label(name))
            elif kind == 'PerspectiveCamera':
                cameras.append({'name': label(name), 'matrix': checked_matrix(a.get('node_xform', IDENTITY), name), 'focal': float(a.get('focal', 30)),
                                'film': float(a.get('film_width_aperture', 24)), 'dof': bool(a.get('dof', False)), 'focus': float(a.get('dof_focus_distance', 0)),
                                'aperture': float(a.get('dof_aperture', 0)), 'render': scene.get('camera') == name or scene.get('camera') is None})
                if 'node_xform' in record.get('close', {}):
                    warnings.append('%s moves over the shutter; its place at shutter open is imported.' % short(name))
            elif kind in catalog:
                made = entity(record, checked_matrix(a.get('node_xform', IDENTITY), name))
                if catalog[kind]['category'] == 'camera' and scene.get('camera') == name:
                    made['parameters']['modo_render_camera'] = True
            elif kind.endswith('Geometry') or kind.endswith('Light') or kind.endswith('LightFilter') or kind.endswith('Camera') or kind.endswith('Volume'):
                warnings.append('%s: %s has no counterpart in Modo and is not imported' % (short(name), kind))
        except ValueError as exc:
            warnings.append('%s is not imported: %s' % (short(name), exc))

    # Materials nothing wears come in too, to be assigned in Modo.
    worn = {key.split('|')[0] for key in materials}
    bound = {target for v in objects.values() for target in v.get('bindings', {}).values()}
    for name, record in objects.items():
        if record['type'] in shader_library.catalog() and name not in worn and name not in bound:
            try:
                materials[name] = {'name': short(name), 'graph': graph(name, objects, base, warnings)}
            except (ValueError, KeyError) as exc:
                warnings.append(name + ': material graph could not be converted: ' + str(exc))

    # A mesh placed once keeps its place as the item's own transform; placed more than once, the rest are instances of it.
    first = {}
    for entry in instances:
        first.setdefault(entry['source'], entry)
    for record in meshes:
        entry = first.get(record['name'])
        if entry:
            record['matrix'], record['render'], record['attributes'] = entry['matrix'], True, entry['attributes']
            # The mesh takes the place and the name of its first instance.
            entry['source'] = None
    instances = [entry for entry in instances if entry['source']]

    # The scene's own settings, where it set them.
    settings, set_keys = {}, authored(variables) if 'authored' in variables else set()
    if {'image_width', 'image_height'} & set_keys:
        settings['resolution'] = [int(scene.get('image_width', 1920)), int(scene.get('image_height', 1080))]
    if 'pixel_samples' in set_keys:
        settings['samples'] = max(1, int(scene['pixel_samples']))
    render = {key: scene[key] for key in options.render_values({}) if key in set_keys and key in scene}
    if render:
        try:
            options.render_values(dict(render))
            settings['render'] = render
        except ValueError as exc:
            warnings.append('Render settings are not imported: ' + str(exc))
    aovs, custom, used = [], [], set()
    for name, record in objects.items():
        if record['type'] != 'RenderOutput':
            continue
        a = record.get('attributes', {})
        if not a.get('active', True) or int(a.get('result', 0)) == 0:
            continue
        kind_of = int(a.get('result', 0))
        builtin = next((key for key, (_, wanted, _) in options.AOVS.items() if all(a.get(k) == v for k, v in wanted.items())), None)
        entry = None
        if kind_of == 8 and not (builtin and 'modo_environment' in str(a.get('lpe', ''))):
            entry = {'kind': 'lpe', 'expression': a.get('lpe', '')}
        elif kind_of == 7:
            entry = {'kind': 'material', 'expression': a.get('material_aov', '')}
        elif kind_of == 13:
            entry = {'kind': 'cryptomatte', 'depth': max(1, min(16, int(a.get('cryptomatte_depth', 6)))), 'category': 'object'}
        elif kind_of == 3 and int(a.get('state_variable', 0)) == 12:
            entry = {'kind': 'motion'}
        elif builtin:
            aovs.append(builtin)
            continue
        if entry is None:
            warnings.append('%s: this kind of render output is not imported' % short(name))
            continue
        wanted = re.sub(r'[^A-Za-z0-9_]', '_', a.get('channel_name') or short(name))
        wanted = (wanted if re.match(r'[A-Za-z]', wanted) else 'out_' + wanted)[:60]
        chosen, count = wanted, 1
        while chosen.casefold() in used:
            count += 1
            chosen = '%s_%d' % (wanted, count)
        used.add(chosen.casefold())
        entry.update(name=chosen, precision=1 if int(a.get('channel_format', 0)) == 1 else 0)
        try:
            outputs.values(custom + [entry])
            custom.append(entry)
        except ValueError as exc:
            warnings.append('%s: %s' % (short(name), exc))
    if aovs:
        settings['aovs'] = sorted(set(aovs))
    if custom:
        settings['custom_aovs'] = custom
    if scene.get('motion_steps') and len(scene['motion_steps']) > 1 and any('close' in v for v in objects.values()):
        warnings.append('The scene is imported as it stands at shutter open; Modo holds its motion as animation, which RDL does not carry.')
    return dict(meshes=meshes, curves=curves, instances=instances, entities=items, materials={k: v for k, v in materials.items() if v}, cameras=cameras,
                settings=settings, warnings=list(dict.fromkeys(warnings)), source=str(path))


def summary(data):
    """What a plan makes, in a line."""
    counts = (('mesh', 'meshes', len(data['meshes'])), ('instance', 'instances', len(data['instances'])), ('curve set', 'curve sets', len(data['curves'])),
              ('MoonRay item', 'MoonRay items', len(data['entities'])), ('camera', 'cameras', len(data['cameras'])),
              ('material', 'materials', len(data['materials'])), ('output', 'outputs', len(data['settings'].get('custom_aovs', [])) + len(data['settings'].get('aovs', []))))
    made = ['%d %s' % (count, one if count == 1 else many) for one, many, count in counts if count]
    return ', '.join(made) if made else 'nothing'


def empty(data):
    return not (data['meshes'] or data['curves'] or data['entities'] or data['cameras'] or data['materials'])


def entity_text(spec, value):
    """A value as the text channel of a MoonRay item holds it."""
    import json
    if spec['type'] in ('String', 'SceneObject*'):
        return str(value)
    if spec['type'].startswith('SceneObject') or spec['type'] == 'StringVector':
        return ', '.join(str(v) for v in value)
    return json.dumps(value)


def apply(data, alone=True):
    """Make what a plan describes. alone lights the result as the RDL scene was lit and by nothing else: the lights
    already in the Modo scene are set not to render, and Modo's environment is kept out of MoonRay's picture."""
    import lx
    import modo
    from . import entities, materials, options, primitive_attributes, properties, shader_library
    scene = modo.Scene()
    created, warnings, tags, made = [], list(data['warnings']), {}, {}
    previous_camera, previous_selection = scene.renderCamera, list(scene.selected)

    def pose(item, raw):
        parts = decomposed(raw)
        if parts is None:
            raise ValueError('a transform that shears or mirrors')
        position, turn, sizes = parts
        rotation = modo.Matrix4([row + [0.0] for row in turn] + [[0.0, 0.0, 0.0, 1.0]])
        # An item of one of the plugin's own types, or an instance, comes back without its transform at hand.
        locator = item if hasattr(item, 'position') else modo.LocatorSuperType(item)
        locator.position.set(position)
        locator.rotation.set(rotation.asEuler())
        locator.scale.set(sizes)

    try:
        for key, record in data['materials'].items():
            tag = 'RDL_' + uuid.uuid4().hex[:12]
            tags[key] = tag
            mask = scene.addItem('mask', name='RDL ' + record['name'])
            created.append(mask)
            mask.setParent(scene.renderItem, materials.above_base(scene, mask))
            mask.channel('ptyp').set('Material')
            mask.channel('ptag').set(tag)
            shader = record['graph']['nodes'][record['graph']['root']]['type']
            # The material's own kind of layer where the plugin has one, so that it says what it is in the Shader Tree.
            try:
                layer = scene.addItem(properties.LAYER_PREFIX + shader, name=record['name'])
            except (LookupError, RuntimeError, TypeError):
                layer = scene.addItem('advancedMaterial', name=record['name'])
            created.append(layer)
            layer.setParent(mask, 0)
            properties.write(layer, {'shader': 'DwaBaseMaterial', 'moonshine_override': True, 'native_shader': shader,
                                     'native_parameters': record['graph']['nodes'][record['graph']['root']].get('parameters', {}),
                                     'node_graph': record['graph'], 'node_override': True})
        for record in data['meshes']:
            item = scene.addItem('mesh', name=record['name'])
            created.append(item)
            made[record['name']] = item
            vertices_in = record['vertices']
            keep = record['matrix'] is not None and decomposed(record['matrix']) is not None
            if record['matrix'] is not None and not keep:
                # A place Modo's transform cannot hold is put into the points themselves.
                vertices_in = [transform(v, record['matrix']) for v in vertices_in]
                warnings.append(record['name'] + ': its transform shears or mirrors, so it is applied to the points')
            with item.geometry as geo:
                vertices = [geo.vertices.new(v) for v in vertices_in]
                uv = geo.vmaps.addUVMap('RDL UV') if record['uv'] else None
                offset = 0
                for face_index, face in enumerate(record['faces']):
                    polygon = geo.polygons.new([vertices[i] for i in face], polyType=lx.symbol.iPTYP_SUBD if record['subd'] else lx.symbol.iPTYP_FACE)
                    if record['tags'][face_index] in tags:
                        polygon.materialTag = tags[record['tags'][face_index]]
                    if uv:
                        for corner, index in enumerate(face):
                            polygon.setUV(record['uv'][index if len(record['uv']) == len(vertices) else offset + corner], corner, uv)
                    offset += len(face)
            if keep:
                pose(item, record['matrix'])
            if record['attributes']:
                primitive_attributes.write(item, record['attributes'])
            if not record['render']:
                # Only its instances are in the picture, as in the scene it came from.
                item.channel('render').set('off')
            if record['normals']:
                warnings.append(record['name'] + ': its authored normals are left to Modo, which smooths the mesh itself')
        for record in data['instances']:
            source = made.get(record['source'])
            if source is None:
                continue
            try:
                item = scene.duplicateItem(source, instance=True)
                item.name = record['name']
                created.append(item)
                item.channel('render').set('default')
                pose(item, record['matrix'])
                if record['attributes']:
                    primitive_attributes.write(item, record['attributes'])
            except (ValueError, LookupError, RuntimeError) as exc:
                warnings.append('%s is not imported: %s' % (record['name'], exc))
        for record in data['curves']:
            item = scene.addItem('mesh', name=record['name'])
            created.append(item)
            keep = decomposed(record['matrix']) is not None
            with item.geometry as geo:
                accessor = geo.internalMesh.PolygonAccessor()
                for line in record['lines']:
                    # Each point's ID is taken as the point is made; asked for afterwards, every point gives the same one.
                    points = tuple(geo.vertices.new(p if keep else transform(p, record['matrix'])).id for p in line)
                    storage = lx.object.storage('p', len(points))
                    storage.set(points)
                    made_polygon = accessor.New(lx.symbol.iPTYP_LINE, storage, len(points), 0)
                    if record['material'] in tags:
                        # Tagged as it is made: tagging afterwards passes a polygon over now and then.
                        accessor.Select(made_polygon)
                        lx.object.StringTag(accessor).Set(lx.symbol.i_POLYTAG_MATERIAL, tags[record['material']])
            if record['material'] in tags:
                # Twice: tagging polygons just made passes one over now and then.
                for attempt in range(2):
                    with item.geometry as geo:
                        for index in range(len(geo.polygons)):
                            if geo.polygons[index].materialTag != tags[record['material']]:
                                geo.polygons[index].materialTag = tags[record['material']]
            if keep:
                pose(item, record['matrix'])
            if record['attributes']:
                primitive_attributes.write(item, record['attributes'])
            values = options.object_values(properties.read(item))
            values.update(override=True, curves=True, curve_root_width=record['root_mm'], curve_tip_width=record['tip_mm'], curve_round=record['round'])
            properties.write(item, options.object_values(values))
        for record in data['entities']:
            try:
                item = scene.addItem(entities.item_type(record['class']), name=record['name'])
            except (LookupError, RuntimeError, TypeError):
                warnings.append('%s: the MoonRay item for %s is not available in this Modo' % (record['name'], record['class']))
                continue
            created.append(item)
            parameters = dict(record['parameters'])
            if record['material'] in tags:
                parameters['modo_material'] = tags[record['material']]
            if record['volume']:
                parameters['modo_volume'] = record['volume']
            if record['attributes']:
                primitive_attributes.write(item, record['attributes'])
            spec = entities.catalog()[record['class']]['attributes']
            for key, channel, plan_kind, default, choices in entities.channels(record['class']):
                if key not in parameters:
                    continue
                value = parameters[key]
                try:
                    if plan_kind in ('color', 'xy', 'xyz'):
                        for suffix, part in zip(entities.VECTORS[spec[key]['type']][1:], value):
                            item.channel(channel + suffix).set(float(part))
                    elif plan_kind == 'string':
                        item.channel(channel).set(entity_text(spec[key], value))
                    elif plan_kind == 'boolean':
                        item.channel(channel).set(bool(value))
                    elif plan_kind == 'integer':
                        item.channel(channel).set(int(value))
                    else:
                        item.channel(channel).set(float(value))
                except (TypeError, ValueError, AttributeError, LookupError, RuntimeError) as exc:
                    warnings.append('%s / %s could not be set: %s' % (record['name'], key, exc))
            try:
                pose(item, record['matrix'])
            except ValueError as exc:
                warnings.append('%s: %s is not held by a Modo item; it stands unturned at its position' % (record['name'], exc))
                (item if hasattr(item, 'position') else modo.LocatorSuperType(item)).position.set(record['matrix'][12:15])
        for record in data['cameras']:
            item = scene.addItem('camera', name=record['name'])
            created.append(item)
            pose(item, record['matrix'])
            item.channel('focalLen').set(record['focal'] * .001)
            item.channel('apertureX').set(record['film'] * .001)
            # The film's height follows the picture's shape, so that however Modo fits film to picture the width is the one given.
            wide, high = data['settings'].get('resolution') or (scene.renderItem.channel('resX').get(), scene.renderItem.channel('resY').get())
            item.channel('apertureY').set(record['film'] * .001 * high / max(1, wide))
            if record['dof'] and record['focus'] > 0:
                item.channel('dof').set(True)
                item.channel('focusDist').set(record['focus'])
                if record['aperture'] > 0:
                    item.channel('fStop').set(record['focal'] / record['aperture'])
            if record['render']:
                # By command: the scene object's own setter fails in Modo 16.
                try:
                    lx.eval('render.camera {%s}' % item.id)
                except RuntimeError:
                    scene.renderItem.channel('cameraIndex').set(item.index)
        settings = data['settings']
        if settings:
            stored = dict(properties.scene_settings())
            if 'resolution' in settings:
                scene.renderItem.channel('resX').set(settings['resolution'][0])
                scene.renderItem.channel('resY').set(settings['resolution'][1])
            if 'samples' in settings:
                stored['samples'] = settings['samples']
            if 'render' in settings:
                stored['render'] = dict(stored.get('render') or {}, **settings['render'])
            if 'aovs' in settings:
                stored['aovs'] = sorted(set(stored.get('aovs', ['alpha'])) | set(settings['aovs']))
            if 'custom_aovs' in settings:
                held = list(stored.get('custom_aovs') or [])
                names = {entry.get('name', '').casefold() for entry in held}
                stored['custom_aovs'] = held + [entry for entry in settings['custom_aovs'] if entry['name'].casefold() not in names]
            properties.write(scene.renderItem, stored)
        brought = [record for record in data['entities'] if entities.catalog()[record['class']]['category'] == 'light']
        mine = {item.id for item in created}
        lit = [item for item in scene.items('light') if item.id not in mine and item.channel('render').get() != 'off']
        if brought and alone:
            for item in lit:
                item.channel('render').set('off')
            if lit:
                warnings.append('The lights that were in the Modo scene (%s) are set not to render, so that the scene is lit as it was.' % ', '.join(item.name for item in lit[:4]))
            stored = dict(properties.scene_settings())
            if stored.get('modo_environment', True) and not any(record['class'] == 'EnvLight' for record in brought):
                stored['modo_environment'] = False
                properties.write(scene.renderItem, stored)
                warnings.append("Modo's environment is kept out of MoonRay's picture (MoonRay > Render Settings), as the scene has none of its own.")
        elif brought and lit:
            warnings.append('The lights already in the Modo scene (%s) light the imported scene too.' % ', '.join(item.name for item in lit[:4]))
        scene.select([item for item in created if item.type == 'mesh'])
        said = summary(data)
        return said[:1].upper() + said[1:] + ' imported.\n\n' + '\n'.join(dict.fromkeys(warnings))
    except Exception:
        # The plan is checked before anything is made; a failure inside Modo takes back what was made.
        for item in reversed(created):
            try:
                scene.removeItem(item)
            except Exception:
                pass
        try:
            scene.renderCamera = previous_camera
            scene.select(previous_selection)
        except Exception:
            pass
        raise
