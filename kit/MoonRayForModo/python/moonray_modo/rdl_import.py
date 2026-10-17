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
# More instances than this of one instancer are not made into Modo items, which would be too many to work with: the
# rest come in merged into meshes, each of at most MERGED_POINTS points (combined).
INSTANCE_LIMIT = 20000
MERGED_POINTS = 1000000
LINE, BEZIER, BSPLINE = 0, 1, 2
pending = None
result = ''


def files(path):
    """The files of the scene a chosen file belongs to, in the order to read them. A scene is often two files of one
    name: the binary one with the bulk of it, then the text one with what was tuned by hand, which has the last word."""
    path = Path(path)
    both = [path.with_suffix(suffix) for suffix in ('.rdlb', '.rdla')]
    return [str(p) for p in both] if all(p.is_file() for p in both) else [str(path)]


def transform(point, matrix):
    return [sum(point[j] * matrix[j * 4 + i] for j in range(3)) + matrix[12 + i] for i in range(3)]


def normal_transform(matrix):
    """Scale-independent cofactors and determinant of the row-vector linear transform."""
    rows=[matrix[i*4:i*4+3] for i in range(3)]
    scale=max(abs(v) for row in rows for v in row)
    if not math.isfinite(scale) or scale==0:raise ValueError('singular normal transform')
    rows=[[v/scale for v in row] for row in rows]
    def cross(a,b):return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
    cofactors=[cross(rows[1],rows[2]),cross(rows[2],rows[0]),cross(rows[0],rows[1])]
    determinant=sum(a*b for a,b in zip(rows[0],cofactors[0]))
    if not math.isfinite(determinant) or abs(determinant)<=1e-12:
        raise ValueError('singular normal transform')
    return cofactors,determinant


def transformed_normals(normals, matrix):
    """Apply the inverse transpose and normalize; ignore translation."""
    cofactors,determinant=normal_transform(matrix)
    result=[]
    for normal in normals:
        # Preserve the determinant sign for reflections; magnitude cancels on normalization.
        value=[sum(normal[j]*cofactors[j][i] for j in range(3))*(1 if determinant>0 else -1) for i in range(3)]
        length=math.sqrt(sum(v*v for v in value))
        if not math.isfinite(length) or length==0:raise ValueError('invalid transformed normal')
        result.append([v/length for v in value])
    return result


def hard_creases(attributes, faces, vertex_count):
    """Validate RDL creases and return them as Modo's subdivision weights: ([a, b, weight] edges, [point, weight]
    corners, whether any is less than fully sharp). A sharpness of 10 or more is a weight of 1 (100%), and less is a
    tenth of it, as the plugin writes Modo's weights out (host.subdivision_creases)."""
    indices=attributes.get('subd_crease_indices') or []
    weights=attributes.get('subd_crease_sharpnesses') or []
    corners=attributes.get('subd_corner_indices') or []
    corner_weights=attributes.get('subd_corner_sharpnesses') or []
    if len(indices)!=2*len(weights) or len(corners)!=len(corner_weights):
        raise ValueError('Subdivision crease indices and weights have different lengths')
    if any(type(i) is not int or not 0<=i<vertex_count for i in list(indices)+list(corners)):
        raise ValueError('Invalid subdivision crease point index')
    if any(not isinstance(w,(int,float)) or not math.isfinite(w) or w<0 for w in list(weights)+list(corner_weights)):
        raise ValueError('Invalid subdivision crease sharpness')
    edges={tuple(sorted((a,b))) for face in faces for a,b in zip(face,face[1:]+face[:1])}
    pairs=list(zip(indices[::2],indices[1::2]))
    if any(a==b or tuple(sorted((a,b))) not in edges for a,b in pairs):
        raise ValueError('Subdivision crease does not refer to a mesh edge')
    weight=lambda w:min(1.0,float(w)/10.0)
    return ([[a,b,weight(w)] for (a,b),w in zip(pairs,weights) if w>0], [[i,weight(w)] for i,w in zip(corners,corner_weights) if w>0],
            any(0<w<10 for w in list(weights)+list(corner_weights)))


def product(a, b):
    """a then b, for matrices that move a row vector: the order MoonRay writes them in."""
    return [sum(a[row * 4 + k] * b[k * 4 + col] for k in range(4)) for row in range(4) for col in range(4)]


def shaded_normals(vertices, faces, smooth=True):
    """The normals MoonRay shades a polygon mesh with when it is given none: with smooth_normal, at each point the
    faces around it added up by their area (PolyMeshCalcNv), one for each point; without, each face's own, one for each
    corner. A point no face gives a direction keeps straight up."""
    def facing(face):
        # Newell's sum: twice the face's area, along its normal, for a face of any number of sides.
        x = y = z = 0.0
        for i, index in enumerate(face):
            a, b = vertices[index], vertices[face[(i + 1) % len(face)]]
            x += (a[1] - b[1]) * (a[2] + b[2])
            y += (a[2] - b[2]) * (a[0] + b[0])
            z += (a[0] - b[0]) * (a[1] + b[1])
        return [x, y, z]

    def unit(v):
        length = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
        return [v[0] / length, v[1] / length, v[2] / length] if length > 1e-30 else [0.0, 1.0, 0.0]
    if not smooth:
        return [unit(facing(face)) for face in faces for _ in face]
    summed = [[0.0, 0.0, 0.0] for _ in vertices]
    for face in faces:
        direction = facing(face)
        for index in face:
            held = summed[index]
            held[0] += direction[0]; held[1] += direction[1]; held[2] += direction[2]
    return [unit(v) for v in summed]


def moved(point, matrix):
    """A point moved by a matrix that moves a row vector."""
    return [point[0] * matrix[i] + point[1] * matrix[4 + i] + point[2] * matrix[8 + i] + matrix[12 + i] for i in range(3)]


def turned(normal, matrix):
    """A normal turned by a matrix: by the inverse of its transpose, which keeps it square to a stretched surface."""
    a, b, c, d, e, f, g, h, k = (matrix[i] for i in (0, 1, 2, 4, 5, 6, 8, 9, 10))
    # The cofactors of the turning part; their rows, times a row vector, give the normal up to its length.
    rows = [[e * k - f * h, f * g - d * k, d * h - e * g], [c * h - b * k, a * k - c * g, b * g - a * h], [b * f - c * e, c * d - a * f, a * e - b * d]]
    result_ = [sum(normal[j] * rows[j][i] for j in range(3)) for i in range(3)]
    length = math.sqrt(sum(v * v for v in result_))
    return [v / length for v in result_] if length > 1e-20 else list(normal)


def combined(source, copies, title):
    """Copies of one mesh merged into meshes in the scene's own space, each of at most MERGED_POINTS points. Values a
    copy carries for the whole of it become values face by face; those all copies share stay the merged mesh's own."""
    per = max(1, MERGED_POINTS // max(1, len(source['vertices'])))
    shared = [entry for entry in copies[0]['attributes']
              if all(any(other['name'] == entry['name'] and other['value'] == entry['value'] for other in copy['attributes']) for copy in copies)]
    names, varying = {entry['name'] for entry in shared}, {}
    for copy in copies:
        for entry in copy['attributes']:
            if entry['name'] not in names:
                varying.setdefault(entry['name'], entry['type'])
    moving = any('matrix_close' in copy for copy in copies) or 'vertices_close' in source
    count = len(source['faces'])
    made = []
    for start in range(0, len(copies), per):
        chunk = copies[start:start + per]
        record = {'name': '%s merged %d' % (title, start // per + 1), 'vertices': [], 'faces': [], 'uv': [], 'normals': [], 'tags': [],
                  'subd': source['subd'], 'matrix': list(IDENTITY), 'render': True, 'attributes': [dict(entry) for entry in shared],
                  'hard_edges': [], 'hard_corners': [], 'maps': []}
        maps = {name: (word, rate, []) for name, word, rate, values in source.get('maps') or []}
        strings = {name: (rate, []) for name, rate, values in source.get('strings') or []}
        closing = [] if moving else None
        for copy in chunk:
            offset, matrix = len(record['vertices']), copy['matrix']
            record['vertices'] += [moved(p, matrix) for p in source['vertices']]
            record['faces'] += [[i + offset for i in face] for face in source['faces']]
            record['uv'] += [list(v) for v in source['uv']]
            record['normals'] += [turned(n, matrix) for n in source['normals']]
            record['tags'] += source['tags']
            record['hard_edges'] += [[a + offset, b + offset, w] for a, b, w in source['hard_edges']]
            record['hard_corners'] += [[i + offset, w] for i, w in source['hard_corners']]
            for name, word, rate, values in source.get('maps') or []:
                maps[name][2].extend(values)
            for name, rate, values in source.get('strings') or []:
                strings[name][1].extend(values)
            if closing is not None:
                closing += [moved(p, copy.get('matrix_close', matrix)) for p in source.get('vertices_close') or source['vertices']]
            own = {entry['name']: entry['value'] for entry in copy['attributes']}
            for name, kind in varying.items():
                value = own.get(name)
                if kind == 'string':
                    strings.setdefault(name, ('faces', []))[1].extend([str(value if value is not None else '')] * count)
                    continue
                if kind in ('color', 'vec2', 'vec3'):
                    held = [float(v) for v in list(value or [])[:3]]
                    held += [0.0] * (3 - len(held))
                else:
                    held = [float(value or 0)]
                word = kind if kind in ('color', 'vec2', 'vec3') else 'float'
                maps.setdefault(name, (word, 'faces', []))[2].extend([held] * count)
        record['maps'] = [(name, word, rate, values) for name, (word, rate, values) in maps.items()]
        if strings:
            record['strings'] = [(name, rate, values) for name, (rate, values) in strings.items()]
        if closing is not None:
            record['vertices_close'] = closing
        made.append(record)
    return made


def placed(position, orientation=None, scale=None):
    """The matrix of an instance given as a position, a turn (a quaternion x y z w) and a scale, as MoonRay builds it."""
    def components(value, count, name):
        try:
            values = [float(v) for v in value]
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError('Invalid instance ' + name) from exc
        if len(values) != count or not all(math.isfinite(v) for v in values):
            raise ValueError('Invalid instance %s: expected %d finite components' % (name, count))
        return values

    position = components(position, 3, 'position')
    sizes = components((1, 1, 1) if scale is None else scale, 3, 'scale')
    quaternion = components((0, 0, 0, 1) if orientation is None else orientation, 4, 'orientation')
    largest = max(abs(v) for v in quaternion)
    scaled = [v / largest for v in quaternion] if largest else [0, 0, 0, 0]
    length = math.sqrt(sum(v * v for v in scaled))
    if not largest or (largest < 1e-12 and largest * length < 1e-12):
        x, y, z, w = 0.0, 0.0, 0.0, 1.0
    else:
        x, y, z, w = [v / length for v in scaled]
    rows = [[1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y)],
            [2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x)],
            [2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y)]]
    matrix = [value for row, size in zip(rows, sizes) for value in [v * size for v in row] + [0.0]] + position + [1.0]
    return checked_matrix(matrix, 'instance transform')


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


def graph(root, objects, base, warnings, displacement=None, as_map=False):
    """A material and everything wired into it, as a node graph the plugin's materials hold; as_map, a map and what
    is wired into it, as a MoonRay item's attribute holds one (entities.block)."""
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
    if as_map:
        return found
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


def plan(document, path, recover_instancer_materials=False):
    # Recovery is a developer opt-in; normal/UI imports preserve native source visibility.
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

    def unique_name(wanted):
        count, chosen = 1, wanted
        while chosen in taken or ',' in chosen:
            count += 1
            chosen = '%s %d' % (wanted.replace(',', ' '), count)
        taken.add(chosen)
        return chosen

    def label(name):
        if name not in labels:
            labels[name] = unique_name(short(name))
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
    # What lights each shape, which lights it casts no shadow for, and what its shadow does not fall on: MoonRay's
    # light set, shadow set and shadow receiver set, which become the item's Light Links in MoonRay's scene controls.
    # Uniform sets use object controls; differing mesh parts keep sets on distinct material layers.
    sets, part_sets, split_sets, material_links = {}, {}, set(), {}
    for (geometry, part), row in assigned.items():
        members = set(objects.get(row['lights'], {}).get('attributes', {}).get('lights', [])) if row['lights'] else set()
        own = (tuple(sorted(members)) if all_lights and row['lights'] and members != all_lights else None,
               tuple(sorted(set(objects.get(row['shadows'], {}).get('attributes', {}).get('lights', [])))) if row['shadows'] else (),
               tuple(sorted(set(objects.get(row['receivers'], {}).get('attributes', {}).get('geometries', [])))) if row['receivers'] else (),
               tuple(sorted(set(objects.get(row['filters'], {}).get('attributes', {}).get('lightfilters', [])))) if row['filters'] else ())
        part_sets[(geometry, part)] = own
        if geometry in sets and sets[geometry] != own:
            if objects.get(geometry, {}).get('type') == 'RdlMeshGeometry':
                split_sets.add(geometry)
            else:
                warnings.append('%s: differing per-part sets on this geometry type are not imported; the first assignment is retained' % short(geometry))
        sets.setdefault(geometry, own)

    def owners(owner):
        return owner if isinstance(owner, tuple) else ((owner,) if owner else ())

    def material(geometry, part, owner=None):
        """The key of the material a part of a shape is rendered with, made on first use; None for no material."""
        # The shape's own assignment first, then that of the instancer repeating it.
        pairs = [(name, section) for name in (geometry,) + (owners(owner) if recover_instancer_materials else ()) for section in (part, '')]
        rows = [assigned.get(key) for key in pairs]
        row = next((r for r in rows if r and r['surface']), None)
        if not row:
            return None
        surface, displacement = row['surface'], row['displacement']
        if surface not in objects or objects[surface]['type'] not in shader_library.catalog():
            warnings.append('%s: its material %s is of a class the plugin has no material for.' % (short(geometry), short(str(surface))))
            return None
        key = surface if not displacement else surface + '|' + displacement
        assignment = next((pair for pair in pairs if assigned.get(pair) is row), None)
        if assignment and assignment[0] != geometry:
            warnings.append('%s: material assigned only to an instancer is imported as an editable fallback; '
                            'MoonRay ignores that surface assignment, so this changes source visibility' % short(geometry))
        if assignment and (assignment[0] in split_sets or (owner and (objects.get(geometry, {}).get('type') == 'RdlMeshGeometry' or catalog.get(objects.get(geometry, {}).get('type'), {}).get('category') == 'geometry'))):
            key += '|links:' + repr(assignment)
            material_links[key] = (assignment[0], part_sets[assignment])
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

    def closing(record, name):
        """Where a thing placed on its own is at shutter close, when the scene blurs motion and it moves: keyed as Modo
        animation on import. None for one that stays."""
        steps = scene.get('motion_steps') or []
        held = record.get('close', {}).get('node_xform')
        if held is None or len(steps) < 2:
            return None
        return checked_matrix(held, name)

    def note_motion(record, shaped=False):
        """Say so where a shape changes over the shutter and comes in as it opens; shaped, it comes in changing."""
        moving = [key for key in record.get('close', {}) if key != 'node_xform']
        if not shaped and (moving or record.get('attributes', {}).get('vertex_list_1')):
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
        """A shared prototype per face-material assignment; return its name in the plan."""
        key = record['name']
        scope = (key, owner)
        if scope in mesh.scopes:
            return mesh.scopes[scope]
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
        volume = volume_of(record['name'])
        if volume and objects[volume]['type'] in catalog:
            # A mesh MoonRay fills with a volume: its faces wear a material that holds the volume's item, and where the
            # scene gave them no surface, the volume alone (rdla.material_volume).
            fog = label(volume)

            def filled(tag):
                if tag is None:
                    held = 'volume:' + volume
                    materials.setdefault(held, {'name': short(volume) + ' fog', 'graph': None, 'volume': fog, 'volume_only': True})
                    return held
                held = tag + '|volume:' + volume
                if held not in materials and materials.get(tag):
                    materials[held] = dict(materials[tag], volume=fog)
                return held if materials.get(held) else tag
            tags = [filled(tag) for tag in tags]
        elif volume:
            warnings.append('%s: its volume %s is of a class the plugin has no item for' % (short(record['name']), short(volume)))
        cache_key = (key, tuple(tags))
        if cache_key in mesh.cache:
            mesh.scopes[scope] = mesh.cache[cache_key]
            return mesh.cache[cache_key]
        uv = a.get('uv_list', [])
        if uv and len(uv) not in (len(vertices), len(indices)):
            warnings.append(short(record['name']) + ': its UVs are neither one for each point nor one for each corner, and are left out')
            uv = []
        normals = a.get('normal_list', [])
        if normals and (len(normals) not in (len(vertices), len(indices)) or
                        any(len(v)!=3 or any(not math.isfinite(x) for x in v) or not any(v) for v in normals)):
            warnings.append(short(record['name']) + ': invalid authored normals are left out')
            normals = []
        faces, offset = [], 0
        for count in counts:
            faces.append(indices[offset:offset + count])
            offset += count
        if not normals and not bool(a.get('is_subd', False)):
            # Given none, MoonRay works the normals out itself, smooth unless smooth_normal is off; Modo would shade by
            # its material's smoothing angle instead (a cube comes out faceted that MoonRay rounds), so they come in.
            normals = shaded_normals(vertices, faces, bool(a.get('smooth_normal', True)))
        hard_edges,hard_corners,semi_sharp=hard_creases(a,faces,len(vertices))
        # Values that differ point by point, corner by corner or face by face become the mesh's vertex maps: numbers a
        # weight map, colours an RGB map, as MoonRay's auto rate tells them apart, by how many there are.
        painted, strings = [], []
        for name_, kind_, held in carried(record):
            if len(held) <= 1:
                continue
            rate = 'points' if len(held) == len(vertices) else 'corners' if len(held) == len(indices) else 'faces' if len(held) == len(counts) else None
            if kind_ == 'string' and rate is not None:
                # Words have no Modo vertex map: they are kept on the mesh, by point, corner or face (vertex_maps.strings).
                strings.append((name_, rate, [str(v) for v in held]))
                continue
            if kind_ not in ('float', 'int', 'color', 'vec2', 'vec3') or rate is None:
                warnings.append('%s: %s differs from face to face or point to point as %s, which a Modo vertex map cannot hold; it is not imported'
                                % (short(record['name']), name_, 'a %s' % kind_ if rate else 'a count of values matching nothing'))
                continue
            # Vectors go in a colour map, a vec2's third number 0, and the mesh notes which (vertex_maps.as_vectors).
            painted.append((name_, kind_ if kind_ in ('vec2', 'vec3') else 'color' if kind_ == 'color' else 'float', rate,
                            [list(v) + [0.0] * (3 - len(v)) if kind_ in ('color', 'vec2', 'vec3') else [float(v)] for v in held]))
        # Its shape at shutter close, when the scene blurs motion: MoonRay's second list of points, or each point moved by
        # its velocity, in units a second, about the frame (the first list then moved to shutter open too).
        closing_points = None
        steps = scene.get('motion_steps') or []
        if len(steps) >= 2:
            later, speeds = a.get('vertex_list_1'), a.get('velocity_list_0') or a.get('velocity_list')
            if later and len(later) == len(vertices):
                closing_points = [list(v) for v in later]
            elif speeds and len(speeds) == len(vertices):
                fps = float(scene.get('fps', 24) or 24)
                closing_points = [[p[i] + v[i] * steps[-1] / fps for i in range(3)] for p, v in zip(vertices, speeds)]
                vertices = [[p[i] + v[i] * steps[0] / fps for i in range(3)] for p, v in zip(vertices, speeds)]
        note_motion(record, closing_points is not None)
        name = label(key) if key not in mesh.made else unique_name(short(key))
        meshes.append({'name': name, 'vertices': vertices, 'faces': faces, 'uv': uv, 'normals': normals, 'tags': tags, 'subd': bool(a.get('is_subd', False)),
                       'matrix': None, 'render': False, 'attributes': [], 'hard_edges':hard_edges, 'hard_corners':hard_corners, 'maps': painted,
                       **({'strings': strings} if strings else {}),
                       **({'vertices_close': closing_points} if closing_points is not None else {})})
        mesh.made.setdefault(key, name)
        mesh.cache[cache_key] = mesh.scopes[scope] = name
        return name
    mesh.made, mesh.cache, mesh.scopes = {}, {}, {}

    def strands(record, matrix, outer=(), title=None, owner=None, close=None):
        """Curves into the scene at a matrix; title names a copy an instancer makes, which is an item of its own."""
        a = record.get('attributes', {})
        counts, points, radii = a.get('curves_vertex_count', []), a.get('vertex_list_0', []), a.get('radius_list', [])
        if not counts or sum(counts) != len(points) or any(type(n) != int or n < 2 for n in counts):
            raise ValueError('Invalid curve counts: ' + record['name'])
        kind = int(a.get('curve_type', 0))
        if kind not in (LINE, BEZIER, BSPLINE):
            warnings.append('%s: curve type %d is imported as straight lines' % (short(record['name']), kind))
            kind = LINE
        lines, offset, roots, tips, smooth = [], 0, [], [], True
        for count in counts:
            # A curve keeps its control points where there are enough for MoonRay to draw it from them; the item is then
            # set to render its lines as that curve. Too few, and the path the curve takes is imported in their place.
            enough = count >= 4 and (kind != BEZIER or (count - 1) % 3 == 0)
            smooth = smooth and (kind == LINE or enough)
            lines.append(points[offset:offset + count])
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
        # Their shape at shutter close, when the scene blurs motion and the curves keep their own points: MoonRay's
        # second list of points, or each point moved by its velocity (units a second) about the frame.
        closing_lines = None
        steps = scene.get('motion_steps') or []
        if smooth and len(steps) >= 2:
            later, speeds = a.get('vertex_list_1'), a.get('velocity_list_0') or a.get('velocity_list')
            closing_points = None
            if later and len(later) == len(points):
                closing_points = [list(v) for v in later]
            elif speeds and len(speeds) == len(points):
                fps = float(scene.get('fps', 24) or 24)
                closing_points = [[q[i] + v[i] * steps[-1] / fps for i in range(3)] for q, v in zip(points, speeds)]
                opening = [[q[i] + v[i] * steps[0] / fps for i in range(3)] for q, v in zip(points, speeds)]
                lines, offset = [], 0
                for count in counts:
                    lines.append(opening[offset:offset + count]); offset += count
            if closing_points is not None:
                closing_lines, offset = [], 0
                for count in counts:
                    closing_lines.append(closing_points[offset:offset + count]); offset += count
        note_motion(record, closing_lines is not None)
        if not smooth:
            lines, kind = [followed(line, kind) for line in lines], LINE
        values = carried(record)
        # Curves that differ in what they carry, or in width, are imported as an item each, so that each keeps its own.
        apart = any(len(held) == len(lines) and len(held) > 1 for name_, kind_, held in values) or (len(roots) == len(lines) and (max(roots) - min(roots) > 1e-6 * max(roots) or max(tips) - min(tips) > 1e-6 * max(max(tips), 1e-9)))
        for index in (range(len(lines)) if apart and len(lines) <= 64 else [None]):
            base = title or record['name']
            named = (title if title else label(record['name'])) if index is None else (('%s %d' % (title, index + 1)) if title else label('%s %d' % (record['name'], index + 1)))
            curves.append({'name': named,
                           'lines': lines if index is None else [lines[index]], 'kind': kind, 'round': int(a.get('curves_subtype', 0)) == 1, 'matrix': matrix,
                           **({'matrix_close': close} if close is not None else {}),
                           **({'lines_close': closing_lines if index is None else [closing_lines[index]]} if closing_lines is not None else {}),
                           'material': material(record['name'], '', owner), 'attributes': merged(picked(values, index, len(lines)), outer),
                           'root_mm': (mean(roots) if index is None else roots[index]) * 2000.0, 'tip_mm': (mean(tips) if index is None else tips[index]) * 2000.0})

    def entity(record, matrix, name=None, owner=None, outer=(), close=None):
        """A MoonRay item of the object's class, holding the attributes the scene set."""
        kind, spec = record['type'], catalog[record['type']]['attributes']
        a, parameters, bound = record.get('attributes', {}), {}, {}
        # What the scene set, and what it wired a map into, whose value counts whether set or left as it was.
        for key in sorted(authored(record) | set(record.get('bindings', {}))):
            if key == 'node_xform' or key not in spec or key not in a:
                continue
            value = a[key]
            if key in record.get('bindings', {}):
                # A map wired into it: the map's graph, which the item keeps beside the value (entities.block binds them).
                target = record['bindings'][key]
                from . import map_library
                if target in objects and objects[target]['type'] in map_library.catalog():
                    try:
                        bound[key] = graph(target, objects, base, warnings, as_map=True)
                    except (ValueError, KeyError) as exc:
                        warnings.append('%s: the map wired into %s could not be held (%s)' % (short(record['name']), key, exc))
                else:
                    warnings.append('%s: what is wired into %s is not a map the plugin holds' % (short(record['name']), key))
            if spec[key]['type'].startswith('SceneObject'):
                names = [value] if isinstance(value, str) else [v for v in (value or []) if v]
                held = [label(v) for v in names if v in objects and (objects[v]['type'] in catalog or
                        (kind=='MeshLight' and key=='geometry' and objects[v]['type']=='RdlMeshGeometry'))]
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
                **({'bindings': bound} if bound else {}),
                'attributes': merged(picked(carried(record)), outer) if catalog[kind]['category'] == 'geometry' else []}
        parameters.pop('primitive_attributes', None)
        if catalog[kind]['category'] == 'geometry':
            made['material'] = material(record['name'], '', owner)
            volume = next((volume_of(name) for name in owners(owner) + (record['name'],) if volume_of(name)), None)
            if volume and objects[volume]['type'] in catalog:
                made['volume'] = label(volume)
            elif volume:
                warnings.append('%s: its volume %s is of a class the plugin has no item for' % (short(record['name']), short(volume)))
        if kind == 'EnvLight':
            # It is the scene's environment; Modo's own would be added to it.
            parameters['modo_replace_environment'] = True
        if close is not None:
            # Its place at shutter close, keyed as Modo animation (apply). One an instancer repeats is said by place.
            made['matrix_close'] = close
        items.append(made)
        return made

    emitter_geometries={v.get('attributes',{}).get('geometry') for v in objects.values() if v['type']=='MeshLight'}

    left_out = {}

    def place(name, matrix, title, owner=None, depth=0, outer=(), close=None, merge=None):
        """Put one object into the scene at a matrix: a mesh, a MoonRay shape, curves, or everything an instancer repeats.
        With merge, it is one of the copies past INSTANCE_LIMIT, merged into meshes named after merge (combined)."""
        record = objects.get(name)
        if record is None:
            return
        kind, a = record['type'], record.get('attributes', {})
        if depth > 8:
            warnings.append(short(name) + ': instancers nested more than eight deep are not followed')
            return
        if kind != 'RdlInstancerGeometry' and name not in emitter_geometries and not any((row['surface'] and (geometry == name or recover_instancer_materials)) or row['volume']
                for (geometry, part), row in assigned.items() if geometry in (name,) + owners(owner)):
            # MoonRay leaves out a shape the layer gives no material; brought in, it would be in the picture where it was not.
            warnings.append('%s is given no material by the scene, so MoonRay does not render it; it is not imported.' % short(name))
            return
        if kind == 'RdlMeshGeometry':
            source = mesh(record, owner)
            if source:
                instances.append({'name': title, 'source': source, 'matrix': matrix, 'attributes': merged(picked(carried(record)), outer),
                                  **({'matrix_close': close} if close is not None else {}), **({'merge': merge} if merge is not None else {})})
        elif kind == 'RdlInstancerGeometry':
            repeated(record, matrix, title, depth, outer, owner, close, merge)
        elif merge is not None:
            # Only meshes merge; a copy of anything else past the limit is left out, and counted.
            left_out[merge] = left_out.get(merge, 0) + 1
        elif kind == 'RdlCurveGeometry':
            strands(dict(record, name=name), matrix, outer, None if title == label(name) else title, owner, close)
        elif kind in catalog and catalog[kind]['category'] == 'geometry':
            entity(record, matrix, title, owner, outer, close)
        else:
            warnings.append('%s: %s has no counterpart in Modo and is not imported' % (short(name), kind))

    def repeated(record, parent, title, depth, outer=(), owner=None, parent_close=None, merge=None):
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
        # Where each copy is at shutter close, when the scene blurs motion: from the closing transforms MoonRay is given
        # (xform_list_close), from each copy's velocity, in units a second, about the frame; or as it opens.
        steps = scene.get('motion_steps') or []
        closes = None
        if len(steps) >= 2:
            fps = float(scene.get('fps', 24) or 24)
            if method == 2 and len(a.get('xform_list_close') or []) == len(transforms):
                closes = [checked_matrix(m, name) for m in a['xform_list_close']]
            elif method == 0 and len(a.get('velocities') or []) == len(transforms):
                moved = lambda p, v, step: [p[i] + v[i] * step / fps for i in range(3)]
                velocities = a['velocities']
                closes = [placed(moved(p, velocities[i], steps[-1]), turns[i] if len(turns) == len(positions) else None,
                                 sizes[i] if len(sizes) == len(positions) else None) for i, p in enumerate(positions)]
                transforms = [placed(moved(p, velocities[i], steps[0]), turns[i] if len(turns) == len(positions) else None,
                                     sizes[i] if len(sizes) == len(positions) else None) for i, p in enumerate(positions)]
        use_indices = len(indices) == len(transforms)
        if indices and not use_indices:
            warnings.append(short(name) + ': ref_indices does not match the instances; the first prototype is used, as MoonRay does')
        # Per-instance attribute arrays describe the original list, including skipped entries.
        values, total = carried(record), len(transforms)
        if len(transforms) > INSTANCE_LIMIT and merge is None:
            warnings.append('%s: of its %d instances, the first %d come in as Modo instances and the rest merged into meshes'
                            % (short(name), len(transforms), INSTANCE_LIMIT))
        # A referenced instancer's node transform is already included by its parent
        # when use_reference_xforms is enabled; otherwise it must stay excluded.
        own = checked_matrix(a.get('node_xform', IDENTITY), name) if depth == 0 else IDENTITY
        own_close = (closing(record, name) or own) if depth == 0 else IDENTITY
        moving = closes is not None or own_close is not own or parent_close is not None
        for index, matrix in enumerate(transforms):
            if index in disabled:
                continue
            chosen = indices[index] if use_indices else 0
            if chosen < 0:
                continue
            reference = references[chosen if chosen < len(references) else 0]
            if reference not in objects:
                continue
            base = product(product(matrix, own), parent)
            close = product(product(closes[index] if closes else matrix, own_close), parent_close or parent) if moving else None
            matrix = base
            if a.get('use_reference_xforms', False):
                held = objects[reference]
                at_open = checked_matrix(held.get('attributes', {}).get('node_xform', IDENTITY), reference)
                at_close = closing(held, reference)
                matrix = product(at_open, base)
                if close is not None or at_close is not None:
                    close = product(at_close or at_open, close if close is not None else base)
            place(reference, matrix, '%s %d' % (title, index + 1), (name,) + owners(owner), depth + 1, merged(picked(values, index, total), outer), close,
                  merge if merge is not None else title if index >= INSTANCE_LIMIT else None)

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
                    place(name, matrix, label(name), close=closing(record, name))
            elif kind == 'PerspectiveCamera':
                cameras.append({'name': label(name), 'matrix': checked_matrix(a.get('node_xform', IDENTITY), name), 'focal': float(a.get('focal', 30)),
                                'film': float(a.get('film_width_aperture', 24)), 'dof': bool(a.get('dof', False)), 'focus': float(a.get('dof_focus_distance', 0)),
                                'aperture': float(a.get('dof_aperture', 0)), 'render': scene.get('camera') == name or scene.get('camera') is None,
                                **({'matrix_close': closing(record, name)} if closing(record, name) is not None else {})})
            elif kind in catalog:
                made = entity(record, checked_matrix(a.get('node_xform', IDENTITY), name), close=closing(record, name))
                if catalog[kind]['category'] == 'camera' and scene.get('camera') == name:
                    made['parameters']['modo_render_camera'] = True
            elif kind.endswith('Geometry') or kind.endswith('Light') or kind.endswith('LightFilter') or kind.endswith('Camera') or kind.endswith('Volume'):
                warnings.append('%s: %s has no counterpart in Modo and is not imported' % (short(name), kind))
        except ValueError as exc:
            warnings.append('%s is not imported: %s' % (short(name), exc))

    # The scene can say that its lights are seen by the camera. The plugin has no such setting for the whole scene, so
    # each light that left the matter to the scene is told so itself.
    if scene.get('lights_visible_in_camera'):
        for made in items:
            if catalog[made['class']]['category'] == 'light' and 'visible_in_camera' not in made['parameters']:
                made['parameters']['visible_in_camera'] = 1

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
    first, merging = {}, {}
    for entry in instances:
        if 'merge' in entry:
            merging.setdefault((entry['merge'], entry['source']), []).append(entry)
        else:
            first.setdefault(entry['source'], entry)
    for record in meshes:
        entry = first.get(record['name'])
        if entry:
            record['matrix'], record['render'], record['attributes'] = entry['matrix'], True, entry['attributes']
            if 'matrix_close' in entry:
                record['matrix_close'] = entry['matrix_close']
            # The mesh takes the place and the name of its first instance.
            entry['source'] = None
    instances = [entry for entry in instances if entry['source'] and 'merge' not in entry]
    # The copies past INSTANCE_LIMIT, merged into meshes: a set for each instancer, and for each mesh it repeats.
    sources = {record['name']: record for record in meshes}
    for (title, source), copies in merging.items():
        named = title if sum(1 for key in merging if key[0] == title) == 1 else '%s %s' % (title, source)
        for record in combined(sources[source], copies, named):
            record['name'] = unique_name(record['name'])
            meshes.append(record)
    for title, count in left_out.items():
        warnings.append('%s: %d of its copies past the first %d are not meshes, which alone merge, and are not imported' % (title, count, INSTANCE_LIMIT))

    # The scene's own settings, where it set them.
    settings, set_keys = {}, authored(variables) if 'authored' in variables else set()
    if {'image_width', 'image_height'} & set_keys:
        settings['resolution'] = [int(scene.get('image_width', 1920)), int(scene.get('image_height', 1080))]
    if 'pixel_samples' in set_keys:
        settings['samples'] = max(1, int(scene['pixel_samples']))
    # Where the scene left one of the plugin's render settings alone, MoonRay's own value for it is what the scene was
    # made with, and the plugin's may differ: an older reader does not say which were set, and then none are taken.
    render = {key: scene[key] for key in options.render_values({}) if 'authored' in variables and key in scene}
    # The rest of what the scene says of itself as a whole, kept beside the plugin's settings and written back out.
    apart = ('image_width', 'image_height', 'pixel_samples', 'camera', 'layer', 'output_file', 'res', 'fps', 'enable_dof', 'enable_motion_blur',
             'two_stage_output', 'texture_cache_size', 'texture_file_handles', 'machine_id', 'num_machines', 'task_distribution_type', 'tmp_dir',
             'batch_tile_order', 'progressive_tile_order', 'checkpoint_tile_order', 'resume_render', 'resumable_output', 'on_resume_script', 'stats_file')
    extra = {key: scene[key] for key in sorted(set_keys | ({'scene_scale'} if 'authored' in variables else set()))
             if key in scene and key not in apart and key not in render and isinstance(scene[key], (bool, int, float))
             and not key.startswith(('checkpoint', 'debug', 'deep_', 'fatal_', 'cryptomatte'))}
    if extra:
        settings['scene_variables'] = extra
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
        elif kind_of == 9:
            entry = {'kind': 'visibility', 'expression': a.get('visibility_aov', '')}
        elif kind_of == 4 and int(a.get('primitive_attribute_type', 3)) in (0, 3) and a.get('primitive_attribute') and not builtin \
                and not str(a['primitive_attribute']).startswith('modo_'):
            entry = {'kind': 'attribute' if int(a.get('primitive_attribute_type', 3)) == 0 else 'attribute_color', 'expression': a['primitive_attribute']}
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
        # What moves is keyed at the shutter's two ends around the current frame, and the camera's shutter set to them.
        settings['motion_steps'] = [float(scene['motion_steps'][0]), float(scene['motion_steps'][-1])]
    links = []
    native_geometries = {e['name'] for e in items if catalog[e['class']]['category'] == 'geometry'}
    available_filters = {e['name'] for e in items if catalog[e['class']]['category'] == 'lightfilter'}
    def supported_references(name, seen=()):
        if name in seen or len(seen) > 8:
            return False
        record = objects.get(name, {})
        kind = record.get('type')
        if kind == 'RdlInstancerGeometry':
            refs = record.get('attributes', {}).get('references', [])
            return bool(refs) and all(supported_references(ref, seen + (name,)) for ref in refs)
        return kind == 'RdlMeshGeometry' or catalog.get(kind, {}).get('category') == 'geometry'

    # Supported instancer descendants carry their links on scoped material layers.
    scoped_instancers = {geometry for geometry, own in material_links.values()
                         if objects.get(geometry, {}).get('type') == 'RdlInstancerGeometry'
                         and supported_references(geometry)}
    linked_rows = [(geometry, None, own) for geometry, own in sets.items()
                   if geometry not in split_sets and geometry not in scoped_instancers]
    linked_rows += [(geometry, key, own) for key, (geometry, own) in material_links.items() if materials.get(key)]
    for geometry, material_key, (lit, unshadowed, spared, filters) in linked_rows:
        if lit is None and not unshadowed and not spared and not filters:
            continue
        def lights(names):
            # A mesh light exports under the emitting mesh's identity, not its light item.
            result=[]
            for name in names:
                if name not in objects:continue
                record=objects[name]
                if record['type']=='MeshLight':
                    target=mesh.made.get(record.get('attributes',{}).get('geometry'))
                    if not target:
                        warnings.append('%s: linked mesh light has no imported emitter mesh' % short(name))
                        continue
                else:target=label(name)
                if target not in result:result.append(target)
            return result
        for name in filters:
            if label(name) not in available_filters:
                warnings.append('%s: light filter %s has no imported counterpart and is omitted' % (short(geometry), short(name)))
        native_geometry = label(geometry) if label(geometry) in native_geometries else None
        receivers = []
        for name in spared:
            targets = [v for (source, tags), v in mesh.cache.items() if source == name]
            if not targets and label(name) in native_geometries:
                targets = [label(name)]
            receivers.extend(target for target in targets if target not in receivers)
        links.append({'material': material_key, 'geometry': mesh.made.get(geometry) or native_geometry, 'named': short(geometry), 'lights': None if lit is None else lights(lit),
                      'filters': [label(name) for name in filters if label(name) in available_filters],
                      'shadows': lights(unshadowed), 'receivers': receivers})
    return dict(meshes=meshes, curves=curves, instances=instances, entities=items, materials={k: v for k, v in materials.items() if v}, cameras=cameras,
                settings=settings, links=links, warnings=list(dict.fromkeys(warnings)), source=str(path))


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


class Cancelled(Exception):
    """The user stopped an import part way; what it had made is taken back."""


def apply(data, alone=True, progress=None):
    """Make what a plan describes. alone lights the result as the RDL scene was lit and by nothing else: the lights
    already in the Modo scene are set not to render, and Modo's environment is kept out of MoonRay's picture.
    progress(done, total, what) is told how far the meshes have come, in polygons, and returns False to stop."""
    import lx
    import modo
    from . import entities, materials, options, primitive_attributes, properties, shader_library
    scene = modo.Scene()
    created, warnings, tags, made = [], list(data['warnings']), {}, {}
    # The MoonRay items made, by name: the lights among them are what light and shadow sets name.
    brought_in, material_items = {}, {}
    previous_camera, previous_selection = scene.renderCamera, list(scene.selected)

    # A scene that blurs motion: what moves is keyed at the shutter's two ends, in frames about the current one.
    steps = data['settings'].get('motion_steps')
    now, fps = lx.service.Selection().GetTime(), float(scene.fps)

    def pose(item, raw, close=None):
        # An item of one of the plugin's own types, or an instance, comes back without its transform at hand.
        locator = item if hasattr(item, 'position') else modo.LocatorSuperType(item)
        keyed = close is not None and steps
        for matrix, step in ((raw, steps[0]), (close, steps[-1])) if keyed else ((raw, None),):
            parts = decomposed(matrix)
            if parts is None:
                raise ValueError('a transform that shears or mirrors')
            position, turn, sizes = parts
            rotation = modo.Matrix4([row + [0.0] for row in turn] + [[0.0, 0.0, 0.0, 1.0]]).asEuler()
            when = dict(time=now + step / fps, key=True) if keyed else {}
            locator.position.set(position, **when)
            locator.rotation.set(rotation, **when)
            locator.scale.set(sizes, **when)

    def shutter_morph(item, opened, closing):
        """A shape that changes over the shutter: the change a morph map, and a Morph Influence keyed from none at
        shutter open to all of it at shutter close. opened and closing are its points in the order they were made."""
        with item.geometry as geo:
            morph = geo.vmaps.addMorphMap('RDL shutter close', False)
            for index, (before, after) in enumerate(zip(opened, closing)):
                change = tuple(float(b) - float(a) for a, b in zip(before, after))
                if any(change):
                    morph[index] = change
        deformer = scene.addItem('morphDeform', name=item.name + ' over the shutter')
        created.append(deformer)
        deformer.channel('mapName').set('RDL shutter close')
        deformer.itemGraph('deformers') >> item.itemGraph('deformers')
        deformer.channel('strength').set(0.0, time=now + steps[0] / fps, key=True)
        deformer.channel('strength').set(1.0, time=now + steps[-1] / fps, key=True)

    try:
        for key, record in data['materials'].items():
            tag = 'RDL_' + uuid.uuid4().hex[:12]
            tags[key] = tag
            mask = scene.addItem('mask', name='RDL ' + record['name'])
            created.append(mask)
            mask.setParent(scene.renderItem, materials.above_base(scene, mask))
            mask.channel('ptyp').set('Material')
            mask.channel('ptag').set(tag)
            if record.get('graph') is None:
                # A volume alone: a material layer that names the MoonRay volume item filling the mesh, with no surface.
                layer = scene.addItem('advancedMaterial', name=record['name'])
                created.append(layer)
                layer.setParent(mask, 0)
                material_items[key] = layer
                properties.write(layer, {'moonray_volume': record['volume'], 'volume_only': True})
                continue
            shader = record['graph']['nodes'][record['graph']['root']]['type']
            # The material's own kind of layer where the plugin has one, so that it says what it is in the Shader Tree.
            try:
                layer = scene.addItem(properties.LAYER_PREFIX + shader, name=record['name'])
            except (LookupError, RuntimeError, TypeError):
                layer = scene.addItem('advancedMaterial', name=record['name'])
            created.append(layer)
            layer.setParent(mask, 0)
            material_items[key] = layer
            # Where the scene left a setting at MoonRay's default that the plugin starts otherwise (a toon's ramp), it
            # is MoonRay's default here: the material is the scene's.
            from .node_defaults import keep_moonray_defaults
            keep_moonray_defaults(record['graph'])
            properties.write(layer, {'shader': 'DwaBaseMaterial', 'moonshine_override': True, 'native_shader': shader,
                                     'native_parameters': record['graph']['nodes'][record['graph']['root']].get('parameters', {}),
                                     'node_graph': record['graph'], 'node_override': True,
                                     **({'moonray_volume': record['volume']} if record.get('volume') else {})})
        built, total = 0, sum(len(record['faces']) for record in data['meshes'])
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
            reverse_winding=False
            if record['matrix'] is not None and not keep:
                try:reverse_winding=normal_transform(record['matrix'])[1]<0
                except ValueError:pass
            normals_in=record['normals']
            if normals_in and record['matrix'] is not None and not keep:
                try:normals_in=transformed_normals(normals_in,record['matrix'])
                except ValueError:
                    normals_in=[]
                    warnings.append(record['name'] + ': authored normals on a singular transform are not imported')
            with item.geometry as geo:
                # Through the mesh's own accessors: the scripting layer's vertex and polygon objects cost some ten times
                # as much for each one made, which is minutes for a heavy mesh.
                mesh = geo.internalMesh
                point, polygon = lx.object.Point(mesh.PointAccessor()), lx.object.Polygon(mesh.PolygonAccessor())
                vertices = [point.New(v) for v in vertices_in]
                uv, pair = None, lx.object.storage('f', 2)
                if record['uv']:
                    uv = lx.object.MeshMap(mesh.MeshMapAccessor()).New(lx.symbol.i_VMAP_TEXTUREUV, 'RDL UV')
                by_point = len(record['uv']) == len(vertices)
                if uv and by_point:
                    # One value for each point, wherever the point is used.
                    for identity, value in zip(vertices, record['uv']):
                        point.Select(identity)
                        pair.set((value[0], value[1]))
                        point.SetMapValue(uv, pair)
                normal_map=None;normal_value=lx.object.storage('f',3)
                normals_by_point=len(normals_in)==len(vertices)
                if normals_in:
                    normal_map=lx.object.MeshMap(mesh.MeshMapAccessor()).New(lx.symbol.i_VMAP_NORMAL,'RDL Normals')
                    if normals_by_point:
                        for identity,value in zip(vertices,normals_in):
                            point.Select(identity);normal_value.set(tuple(value));point.SetMapValue(normal_map,normal_value)
                creased=bool(record.get('hard_edges') or record.get('hard_corners'))
                kind = (lx.symbol.iPTYP_PSUB if creased else lx.symbol.iPTYP_SUBD) if record['subd'] else lx.symbol.iPTYP_FACE
                tagger, uvs, face_tags = lx.object.StringTag(polygon), record['uv'], record['tags']
                made_polygons = []
                offset, corners, sized = 0, {}, 0
                for face_index, face in enumerate(record['faces']):
                    count = len(face)
                    if count != sized:
                        corners[count] = corners.get(count) or lx.object.storage('p', count)
                        sized = count
                    storage = corners[count]
                    ordered=list(enumerate(face))
                    if reverse_winding:ordered.reverse()
                    storage.set(tuple(vertices[i] for _,i in ordered))
                    made_polygon = polygon.New(kind, storage, count, 0)
                    if record.get('maps'):
                        made_polygons.append((made_polygon, ordered))
                    wears = tags.get(face_tags[face_index])
                    if wears or (uv and not by_point) or (normal_map and not normals_by_point):
                        polygon.Select(made_polygon)
                        if wears:
                            tagger.Set(lx.symbol.i_POLYTAG_MATERIAL, wears)
                        if uv and not by_point:
                            for corner, index in ordered:
                                value = uvs[offset + corner]
                                pair.set((value[0], value[1]))
                                polygon.SetMapValue(vertices[index], uv, pair)
                        if normal_map and not normals_by_point:
                            for corner,index in ordered:
                                normal_value.set(tuple(normals_in[offset+corner]))
                                polygon.SetMapValue(vertices[index],normal_map,normal_value)
                    offset += count
                    if progress and not face_index % 20000 and progress(built + face_index, total, record['name']) is False:
                        raise Cancelled()
                # The values a MoonRay shape carried for its materials, as vertex maps: at each point, or set apart on
                # each polygon's corners (Modo's discontinuous values), which is how a face keeps a value of its own.
                for map_name, word, rate, values in record.get('maps') or []:
                    painted = lx.object.MeshMap(mesh.MeshMapAccessor()).New(lx.symbol.i_VMAP_WEIGHT if word == 'float' else lx.symbol.i_VMAP_RGB, map_name)
                    value = lx.object.storage('f', 1 if word == 'float' else 3)
                    if rate == 'points':
                        for identity, held in zip(vertices, values):
                            point.Select(identity); value.set(tuple(held)); point.SetMapValue(painted, value)
                        continue
                    offset = 0
                    for face_index, (made_polygon, ordered) in enumerate(made_polygons):
                        polygon.Select(made_polygon)
                        for corner, index in ordered:
                            value.set(tuple(values[offset + corner] if rate == 'corners' else values[face_index]))
                            polygon.SetMapValue(vertices[index], painted, value)
                        offset += len(ordered)
            # Commit topology before asking Modo for edge accessors. Newly created
            # polygons do not yet have a stable edge cache in the construction edit.
            if record['subd'] and creased:
                with item.geometry as geo:
                    mesh=geo.internalMesh
                    vertices=[v._id for v in geo.vertices]
                    weight_map=lx.object.MeshMap(mesh.MeshMapAccessor()).New(lx.symbol.i_VMAP_SUBDIV,'Subdivision')
                    weight=lx.object.storage('f',1)
                    # Each crease at its own weight (hard_creases): 1 for fully sharp, a tenth of the sharpness below.
                    edge=lx.object.Edge(mesh.EdgeAccessor())
                    for a,b,value in record.get('hard_edges',[]):
                        weight.set((float(value),));edge.SelectEndpoints(vertices[a],vertices[b]);edge.SetMapValue(weight_map,weight)
                    point=lx.object.Point(mesh.PointAccessor())
                    for index,value in record.get('hard_corners',[]):
                        weight.set((float(value),));point.Select(vertices[index]);point.SetMapValue(weight_map,weight)
            if record.get('vertices_close') and steps:
                # A shape that changes over the shutter: the change a morph map, and a Morph Influence keyed from none
                # at shutter open to all of it at shutter close.
                closing = record['vertices_close']
                if record['matrix'] is not None and not keep:
                    closing = [transform(v, record['matrix']) for v in closing]
                shutter_morph(item, vertices_in, closing)
            built += len(record['faces'])
            if keep:
                pose(item, record['matrix'], record.get('matrix_close'))
            if record['attributes']:
                primitive_attributes.write(item, record['attributes'])
            vectors = {map_name: word for map_name, word, rate, values in record.get('maps') or [] if word in ('vec2', 'vec3')}
            if record.get('strings'):
                stored = dict(properties.read(item))
                stored['string_attributes'] = {name_: {'rate': rate, 'values': values} for name_, rate, values in record['strings']}
                properties.write(item, stored)
            if vectors:
                # Which of its colour maps hold vectors, for them to go out to MoonRay as vectors (vertex_maps.as_vectors).
                stored = dict(properties.read(item))
                stored['vertex_map_kinds'] = dict(stored.get('vertex_map_kinds') or {}, **vectors)
                properties.write(item, stored)
            if not record['render']:
                # Only its instances are in the picture, as in the scene it came from.
                item.channel('render').set('off')
        for record in data['instances']:
            source = made.get(record['source'])
            if source is None:
                continue
            try:
                item = scene.duplicateItem(source, instance=True)
                item.name = record['name']
                created.append(item)
                item.channel('render').set('default')
                pose(item, record['matrix'], record.get('matrix_close'))
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
            if record.get('lines_close') and steps:
                place_point = (lambda p: p) if keep else (lambda p: transform(p, record['matrix']))
                shutter_morph(item, [place_point(p) for line in record['lines'] for p in line],
                              [place_point(p) for line in record['lines_close'] for p in line])
            if keep:
                pose(item, record['matrix'], record.get('matrix_close'))
            if record['attributes']:
                primitive_attributes.write(item, record['attributes'])
            values = options.object_values(properties.read(item))
            values.update(override=True, curves=True, curve_root_width=record['root_mm'], curve_tip_width=record['tip_mm'], curve_round=record['round'], curve_basis=record['kind'])
            properties.write(item, options.object_values(values))
        for record in data['entities']:
            try:
                item = scene.addItem(entities.item_type(record['class']), name=record['name'])
            except (LookupError, RuntimeError, TypeError):
                warnings.append('%s: the MoonRay item for %s is not available in this Modo' % (record['name'], record['class']))
                continue
            created.append(item)
            brought_in[record['name']] = item
            if record.get('bindings'):
                # Maps wired into its values, kept on the item for the scene to bind (entities.block).
                stored = dict(properties.read(item))
                stored['map_bindings'] = record['bindings']
                properties.write(item, stored)
            parameters = dict(record['parameters'])
            # A new item starts with values of the plugin's own choosing (a light fifty times as bright as MoonRay's
            # default, and smaller). A scene that left one of those at MoonRay's default does not name it, and it is
            # put at that default here: the item is the scene's, not a new one.
            for key in entities.starting(record['class']):
                known = entities.catalog()[record['class']]['attributes'].get(key)
                if known is not None and key not in parameters and 'default' in known:
                    parameters[key] = known['default']
            if record['class']=='MeshLight' and parameters.get('geometry') in made:
                parameters['geometry']=made[parameters['geometry']].id
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
                pose(item, record['matrix'], record.get('matrix_close'))
            except ValueError as exc:
                warnings.append('%s: %s is not held by a Modo item; it stands unturned at its position' % (record['name'], exc))
                (item if hasattr(item, 'position') else modo.LocatorSuperType(item)).position.set(record['matrix'][12:15])
        # A material filled with a MoonRay volume names its item by identity, which stays the item's whatever name Modo
        # gives it among the rest.
        for key, record in data['materials'].items():
            held = brought_in.get(record.get('volume'))
            if held is not None and key in material_items:
                stored = dict(properties.read(material_items[key]))
                stored['moonray_volume'] = held.id
                properties.write(material_items[key], stored)
        for record in data['cameras']:
            item = scene.addItem('camera', name=record['name'])
            created.append(item)
            pose(item, record['matrix'], record.get('matrix_close'))
            if steps:
                # The shutter as the scene's: open to close, in frames about the frame (motion.capture's endpoints).
                item.channel('blurLen').set(float(steps[-1]) - float(steps[0]))
                item.channel('blurOff').set((float(steps[-1]) + float(steps[0])) / 2.0)
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
        if data.get('links'):
            # MoonRay's light, shadow and shadow receiver sets, as each mesh's Light Links.
            stored = dict(properties.scene_settings())
            production = dict(stored.get('production') or {})
            held = dict(production.get('objects') or {})
            linked_items=dict(brought_in,**made)
            for link in data['links']:
                material_key = link.get('material')
                item = material_items.get(material_key) if material_key else linked_items.get(link['geometry'])
                if item is None:
                    warnings.append('%s: its light and shadow sets are not imported because its geometry is unavailable.' % link['named'])
                    continue
                entry = {} if material_key else dict(held.get(item.id) or {})
                if link['lights'] is not None:
                    entry.update(link_enabled=True, lights=[linked_items[name].id for name in link['lights'] if name in linked_items])
                if link['shadows']:
                    entry['shadow_exclude'] = [linked_items[name].id for name in link['shadows'] if name in linked_items]
                if link.get('filters'):
                    entry['light_filters'] = [linked_items[name].id for name in link['filters'] if name in linked_items]
                if link['receivers']:
                    entry['shadow_receivers'] = [linked_items[name].id for name in link['receivers'] if name in linked_items]
                if material_key:
                    saved = dict(properties.read(item))
                    saved['rdl_layer_links'] = entry
                    properties.write(item, saved)
                else:
                    held[item.id] = entry
            production['objects'] = held
            stored['production'] = production
            properties.write(scene.renderItem, stored)
        settings = data['settings']
        if settings:
            stored = dict(properties.scene_settings())
            if 'resolution' in settings:
                scene.renderItem.channel('resX').set(settings['resolution'][0])
                scene.renderItem.channel('resY').set(settings['resolution'][1])
            if 'samples' in settings:
                stored['samples'] = settings['samples']
            if settings.get('motion_steps'):
                # The scene blurs what moves, so renders of it do too (Render Settings, Motion Blur).
                stored['final_motion'] = True
            if 'render' in settings:
                stored['render'] = dict(stored.get('render') or {}, **settings['render'])
            if 'scene_variables' in settings:
                stored['scene_variables'] = dict(stored.get('scene_variables') or {}, **settings['scene_variables'])
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
