"""Modo's Smooth Positions (the render item's dispSmooth, on by default) for a displaced polygon mesh.

Modo cuts a displaced polygon cage onto a smooth surface, not its flat faces: read through its render cache with Smooth
Positions on, a 16-sided cylinder's cut points lie on Phong tessellation's surface at a shape factor of a half (each
point the mean of its place on the flat face and Phong's: the flat point taken to each corner's tangent plane, weighed
as the corners are), to within 0.0001 of its radius across each side; with it off, on the flat sides
(tools/probe_cl_smooth_positions.py). MoonRay (and XPU2, and MoonLightIPR's split) displace a polygon mesh from its flat
faces, so a coarse cage cut finely came out faceted, with dark ticks along its edges, where Modo's was round.

MoonRay has no such setting, so the kit hands it the cage already split onto that surface (refine): each face into
n x n (a triangle into n x n triangles), its points placed as Modo places them, its corners' UVs, normals and maps and
its points' maps carried to the new places, the points on an edge made once for both its faces (no cracks); MoonRay then
cuts it n times less finely (resolution), so the triangles it makes come to the same. n follows how far the cage's
normals turn from its faces (a degree for each split), within a budget of triangles and never past MoonRay's own cut.
Every engine reads the same split cage."""
import ctypes
import math
from array import array
from collections import OrderedDict

# Modo's shape factor: the cut point the mean of the flat point and Phong's.
SHAPE = 0.5
# Splits: one for each this many degrees the cage's normals turn from its faces at the most; at most MOST.
DEGREES = 1.0
MOST = 16
# Triangles a cage may be split into, at the most: by the geometry adapter (MR_smooth_split), NATIVE_TRIANGLES; in Python,
# where the adapter is older than the kit (once for the same lists, kept: a 128-face column into 32,768 faces took about a
# second), TRIANGLES.
TRIANGLES = 250000
NATIVE_TRIANGLES = 4000000
_MADE = OrderedDict()
KEPT = 64


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _unit(a):
    length = math.sqrt(_dot(a, a))
    return (a[0] / length, a[1] / length, a[2] / length) if length > 1e-30 else (0.0, 0.0, 0.0)


def _point(v):
    return (float(v[0]), float(v[1]), float(v[2]))


def _faces(mesh):
    return [[int(k) for k in face] for face in mesh['faces']]


def _face_normal(points):
    """Newell's normal of a polygon (its area's direction, twice its area long)."""
    n = [0.0, 0.0, 0.0]
    for i, a in enumerate(points):
        b = points[(i + 1) % len(points)]
        n[0] += (a[1] - b[1]) * (a[2] + b[2])
        n[1] += (a[2] - b[2]) * (a[0] + b[0])
        n[2] += (a[0] - b[0]) * (a[1] + b[1])
    return tuple(n)


def point_normals(vertices, faces):
    """Each point's normal: its faces' normals weighed by their areas, as MoonRay's smooth normals."""
    sums = [[0.0, 0.0, 0.0] for _ in range(len(vertices))]
    for face in faces:
        n = _face_normal([vertices[k] for k in face])
        for k in face:
            s = sums[k]
            s[0] += n[0]; s[1] += n[1]; s[2] += n[2]
    return [_unit(s) for s in sums]


def corner_normals(mesh, vertices, faces):
    """Each face's corners' normals: the mesh's own (Modo's, by its smoothing angle) where it has them, else its points'."""
    total = sum(map(len, faces))
    given = mesh.get('normals')
    if given is not None and len(given) == total:
        found, at = [], 0
        for face in faces:
            found.append([_unit(_point(given[at + i])) for i in range(len(face))])
            at += len(face)
        return found
    by_point = point_normals(vertices, faces)
    return [[by_point[k] for k in face] for face in faces]


def splits(mesh, resolution):
    """How many times to split each edge of a displaced polygon mesh before MoonRay cuts it (resolution: MoonRay's cut
    of it as it stands): a degree's turn of its normals from its faces for each, at most MOST, at most resolution,
    within TRIANGLES. 1 where it needs none (a flat or dense cage) or cannot be split here."""
    for entry in list((mesh.get('point_attributes') or {}).values()) + list((mesh.get('corner_attributes') or {}).values()):
        if entry.get('kind') == 'string':
            return 1
    try:
        count = len(mesh['faces'])
    except (TypeError, KeyError):
        return 1
    if int(resolution) < 2 or count * 2 > budget():
        return 1
    key = (id(mesh['vertices']), id(mesh['faces']), id(mesh.get('normals')), int(resolution))
    held = _SPLITS.get(key)
    if held is not None and held[0] is mesh['vertices'] and held[1] is mesh['faces']:
        return held[2]
    found = _splits(mesh, resolution)
    _SPLITS[key] = (mesh['vertices'], mesh['faces'], found)
    while len(_SPLITS) > KEPT:
        _SPLITS.popitem(last=False)
    return found


_SPLITS = OrderedDict()


def _splits(mesh, resolution):
    turn = _native_turn(mesh)
    if turn is None:
        try:
            vertices = [_point(v) for v in mesh['vertices']]
            faces = _faces(mesh)
        except (TypeError, ValueError, IndexError, KeyError):
            return 1
        if not faces or min(map(len, faces)) < 3:
            return 1
        normals = corner_normals(mesh, vertices, faces)
        turn = 0.0
        for face, corners in zip(faces, normals):
            n = _unit(_face_normal([vertices[k] for k in face]))
            for c in corners:
                turn = max(turn, math.degrees(math.acos(max(-1.0, min(1.0, _dot(n, c))))))
    elif turn < 0:
        return 1
    if turn >= 89.0:
        # A corner's normal across its face (a fold): nothing to smooth by.
        return 1
    from .rows import counts as face_counts
    sizes = face_counts(mesh['faces'])
    triangles = int(sum(sizes) - 2 * len(sizes)) if sizes is not None else sum(len(face) - 2 for face in mesh['faces'])
    wanted = int(math.ceil(turn / DEGREES - 1e-9))
    room = int(math.sqrt(budget() / max(1, triangles)))
    return max(1, min(wanted, MOST, int(resolution), room))


def resolution(held, n):
    """MoonRay's cut of a cage split n times (refine), for the cut held of the cage itself."""
    return max(1, int(math.ceil(float(held) / max(1, n))))


def _phong(p, corners, normals, weights):
    """The point p of a face (weights: its corners') as Modo's Smooth Positions places it."""
    x = y = z = 0.0
    for c, n, w in zip(corners, normals, weights):
        d = (p[0] - c[0]) * n[0] + (p[1] - c[1]) * n[1] + (p[2] - c[2]) * n[2]
        x += w * (p[0] - d * n[0]); y += w * (p[1] - d * n[1]); z += w * (p[2] - d * n[2])
    return ((1 - SHAPE) * p[0] + SHAPE * x, (1 - SHAPE) * p[1] + SHAPE * y, (1 - SHAPE) * p[2] + SHAPE * z)


def _mix(values, weights):
    """The weighed sum of a corner's or point's values (numbers, or rows of them)."""
    first = values[0]
    if isinstance(first, (int, float)):
        return sum(v * w for v, w in zip(values, weights))
    return [sum(v[i] * w for v, w in zip(values, weights)) for i in range(len(first))]


def _layout(size, n):
    """For a face of size corners (3 or 4) split n times: its places [(i, j)], each place's weights on the corners, its
    new faces (as places), and, for a place on an edge, (corner a, corner b, step from a) - else None."""
    places, weights, edges = [], [], []
    if size == 4:
        for j in range(n + 1):
            for i in range(n + 1):
                s, t = i / n, j / n
                places.append((i, j))
                weights.append(((1 - s) * (1 - t), s * (1 - t), s * t, (1 - s) * t))
                edges.append((0, 1, i) if j == 0 else (1, 2, j) if i == n else (3, 2, i) if j == n else (0, 3, j) if i == 0 else None)
        at = {p: k for k, p in enumerate(places)}
        faces = [[at[(i, j)], at[(i + 1, j)], at[(i + 1, j + 1)], at[(i, j + 1)]] for j in range(n) for i in range(n)]
    else:
        for j in range(n + 1):
            for i in range(n + 1 - j):
                places.append((i, j))
                weights.append(((n - i - j) / n, i / n, j / n))
                edges.append((0, 1, i) if j == 0 else (1, 2, j) if i + j == n else (0, 2, j) if i == 0 else None)
        at = {p: k for k, p in enumerate(places)}
        faces = []
        for j in range(n):
            for i in range(n - j):
                faces.append([at[(i, j)], at[(i + 1, j)], at[(i, j + 1)]])
                if i + j < n - 1:
                    faces.append([at[(i + 1, j)], at[(i + 1, j + 1)], at[(i, j + 1)]])
    return places, weights, edges, faces


def refine(mesh, n):
    """The mesh split n times onto Modo's smooth surface (see the module); the mesh itself where n is 1. Its faces of
    more than four corners as fans of triangles first. Kept for the same lists (by their identity), as the scene text
    keeps the lists it wrote."""
    if n <= 1:
        return mesh
    reads = [(name, mesh.get(name)) for name in ('vertices', 'faces', 'normals', 'uvs', 'uv_sets', 'corner_attributes',
                                                  'point_attributes', 'vertices_close', 'face_materials')]
    key = (tuple((name, id(value)) for name, value in reads), n, SHAPE)
    held = _MADE.get(key)
    if held is not None and all(a is b for (_, a), b in zip(reads, held[0])):
        _MADE.move_to_end(key)
        return dict(mesh, **held[1])
    made = _native_refine(mesh, n)
    if made is None:
        made = _refine(mesh, n)
    _MADE[key] = ([value for _, value in reads], made)
    while len(_MADE) > KEPT:
        _MADE.popitem(last=False)
    return dict(mesh, **made)


def _refine(mesh, n):
    vertices = [_point(v) for v in mesh['vertices']]
    source = _faces(mesh)
    total = sum(map(len, source))
    # Fans of the faces of more than four corners: (face, its corners as places in the source face).
    pieces, from_face = [], []
    for index, face in enumerate(source):
        ways = [list(range(len(face)))] if len(face) <= 4 else [[0, i, i + 1] for i in range(1, len(face) - 1)]
        for way in ways:
            pieces.append((index, way))
    starts, at = [], 0
    for face in source:
        starts.append(at)
        at += len(face)
    normals = corner_normals(mesh, vertices, source)
    closing = mesh.get('vertices_close')
    closing = [_point(v) for v in closing] if closing is not None and len(closing) == len(vertices) else None
    closing_normals = corner_normals({}, closing, source) if closing is not None else None
    corner_lists = {}
    for name in ('normals', 'uvs'):
        if mesh.get(name) is not None and len(mesh[name]) == total:
            corner_lists[name] = mesh[name]
    for name, values in (mesh.get('uv_sets') or {}).items():
        if len(values) == total:
            corner_lists['uv_sets:' + name] = values
    for name, entry in (mesh.get('corner_attributes') or {}).items():
        if len(entry['values']) == total:
            corner_lists['corner_attributes:' + name] = entry['values']
    point_lists = {'point_attributes:' + name: entry['values'] for name, entry in (mesh.get('point_attributes') or {}).items()
                   if len(entry['values']) == len(vertices)}
    out_points = list(vertices)
    out_closing = list(closing) if closing is not None else None
    out_point_lists = {name: list(values) for name, values in point_lists.items()}
    out_faces, out_from = [], []
    out_corners = {name: [] for name in corner_lists}
    on_edges = {}
    layouts = {}
    for index, way in pieces:
        face = [source[index][c] for c in way]
        size = len(face)
        if (size, n) not in layouts:
            layouts[(size, n)] = _layout(size, n)
        places, weights, edges, sub_faces = layouts[(size, n)]
        corners = [vertices[k] for k in face]
        bent = [normals[index][c] for c in way]
        if closing is not None:
            corners_close = [closing[k] for k in face]
            bent_close = [closing_normals[index][c] for c in way]
        made = []
        for place, w, edge in zip(places, weights, edges):
            corner = next((c for c in range(size) if w[c] == 1.0), None)
            if corner is not None:
                made.append(face[corner])
                continue
            if edge is not None:
                a, b, step = face[edge[0]], face[edge[1]], edge[2]
                edge_key = (a, b, step) if a < b else (b, a, n - step)
                if edge_key in on_edges:
                    made.append(on_edges[edge_key])
                    continue
            p = (sum(c[0] * x for c, x in zip(corners, w)), sum(c[1] * x for c, x in zip(corners, w)), sum(c[2] * x for c, x in zip(corners, w)))
            out_points.append(_phong(p, corners, bent, w))
            if out_closing is not None:
                q = (sum(c[0] * x for c, x in zip(corners_close, w)), sum(c[1] * x for c, x in zip(corners_close, w)),
                     sum(c[2] * x for c, x in zip(corners_close, w)))
                out_closing.append(_phong(q, corners_close, bent_close, w))
            for name, values in point_lists.items():
                out_point_lists[name].append(_mix([values[k] for k in face], w))
            made.append(len(out_points) - 1)
            if edge is not None:
                on_edges[edge_key] = made[-1]
        out_faces.extend([made[k] for k in sub] for sub in sub_faces)
        out_from.extend([index] * len(sub_faces))
        for name, values in corner_lists.items():
            # Each place's values once, then each new corner its place's.
            held = [values[starts[index] + c] for c in way]
            mixed = [_mix(held, w) for w in weights]
            if name == 'normals':
                mixed = [list(_unit(m)) for m in mixed]
            out_corners[name].extend(mixed[k] for sub in sub_faces for k in sub)
    result = {'vertices': out_points, 'faces': out_faces, 'smooth_split': n}
    if out_closing is not None:
        result['vertices_close'] = out_closing
    for name in ('normals', 'uvs'):
        if name in out_corners:
            result[name] = out_corners[name]
    if any(name.startswith('uv_sets:') for name in out_corners):
        result['uv_sets'] = {name: out_corners['uv_sets:' + name] for name in mesh['uv_sets'] if 'uv_sets:' + name in out_corners}
    if mesh.get('corner_attributes'):
        result['corner_attributes'] = {name: dict(entry, values=out_corners['corner_attributes:' + name])
                                       for name, entry in mesh['corner_attributes'].items() if 'corner_attributes:' + name in out_corners}
    if mesh.get('point_attributes'):
        result['point_attributes'] = {name: dict(entry, values=out_point_lists['point_attributes:' + name])
                                      for name, entry in mesh['point_attributes'].items() if 'point_attributes:' + name in out_point_lists}
    if mesh.get('face_materials') is not None and len(mesh['face_materials']) == len(source):
        result['face_materials'] = [mesh['face_materials'][i] for i in out_from]
    return result

# ---- By the geometry adapter (native-modo/smooth_split.cpp) ----

def _library():
    """The adapter with MR_smooth_split, made ready to be called; None where it has it not (older than the kit)."""
    from . import rows
    native = rows._native()
    if native is None or not hasattr(native, 'MR_smooth_split'):
        return None
    if native.MR_smooth_split.restype is not ctypes.c_void_p:
        p, q, i, d = ctypes.c_void_p, ctypes.c_longlong, ctypes.c_int, ctypes.c_double
        native.MR_smooth_split.argtypes = [p, q, p, p, q, p, i, d]
        native.MR_smooth_split.restype = p
        native.MR_smooth_split_sizes.argtypes = [p, p]
        native.MR_smooth_split_sizes.restype = None
        native.MR_smooth_split_geometry.argtypes = [p, p, p, p, p]
        native.MR_smooth_split_geometry.restype = None
        native.MR_smooth_split_corners.argtypes = [p, p, i, p, i]
        native.MR_smooth_split_corners.restype = None
        native.MR_smooth_split_points.argtypes = [p, p, i, p]
        native.MR_smooth_split_points.restype = None
        native.MR_smooth_split_moved.argtypes = [p, p, d, p]
        native.MR_smooth_split_moved.restype = None
        native.MR_smooth_split_free.argtypes = [p]
        native.MR_smooth_split_free.restype = None
        native.MR_smooth_split_turn.argtypes = [p, q, p, p, q, p]
        native.MR_smooth_split_turn.restype = d
    return native


def budget():
    """The most triangles a cage is split into: more where the adapter splits it."""
    return NATIVE_TRIANGLES if _library() is not None else TRIANGLES


def _flat(values, width):
    """A list of rows (or Rows) as one run of 32-bit floats of width each; None where they are not so."""
    from .rows import numbers
    held = numbers(values, width)
    if held is not None:
        return held
    try:
        made = array('f', [float(v) for row in values for v in (row if isinstance(row, (list, tuple)) else row[:width])])
    except (TypeError, ValueError):
        return None
    return made if len(made) == width * len(values) else None


def _width(values):
    from .rows import Rows
    if isinstance(values, Rows):
        return values.width
    first = values[0]
    return 1 if isinstance(first, (int, float)) else len(first)


def _inputs(mesh):
    """The mesh's points, corners, counts and its corners' normals (or None) as runs, for the adapter; None where they
    cannot be had."""
    from .rows import corners as flat_corners, counts as face_counts
    points = _flat(mesh['vertices'], 3)
    corners, sizes = flat_corners(mesh['faces']), face_counts(mesh['faces'])
    if corners is None or sizes is None:
        try:
            faces = [list(face) for face in mesh['faces']]
            corners = array('i', [int(k) for face in faces for k in face])
            sizes = array('i', [len(face) for face in faces])
        except (TypeError, ValueError):
            return None
    corners = corners if corners.itemsize == 4 and corners.typecode in ('i', 'l', 'I', 'L') else array('i', corners)
    sizes = sizes if sizes.itemsize == 4 and sizes.typecode in ('i', 'l', 'I', 'L') else array('i', sizes)
    normals = mesh.get('normals')
    normals = _flat(normals, 3) if normals is not None and len(normals) == len(corners) else None
    if points is None or not len(sizes):
        return None
    return points, corners, sizes, normals


def _address(held):
    return held.buffer_info()[0] if held is not None and len(held) else None


def _native_turn(mesh):
    """The most the mesh's corner normals turn from their faces, in degrees, by the adapter; -1 where its faces are
    wrong; None where the adapter cannot be asked."""
    native = _library()
    held = _inputs(mesh) if native is not None else None
    if held is None:
        return None
    points, corners, sizes, normals = held
    return float(native.MR_smooth_split_turn(_address(points), len(points) // 3, _address(corners), _address(sizes), len(sizes),
                                             _address(normals)))


def _native_refine(mesh, n):
    """_refine by the adapter: the split mesh's lists as runs (Rows, Faces); None where the adapter cannot."""
    native = _library()
    held = _inputs(mesh) if native is not None else None
    if held is None:
        return None
    from hashlib import blake2b
    from .rows import Faces, run
    points, corners, sizes, normals = held
    handle = native.MR_smooth_split(_address(points), len(points) // 3, _address(corners), _address(sizes), len(sizes),
                                    _address(normals), int(n), float(SHAPE))
    if not handle:
        return None
    try:
        counted = (ctypes.c_longlong * 3)()
        native.MR_smooth_split_sizes(handle, counted)
        point_count, face_count, corner_count = counted[0], counted[1], counted[2]
        out_points = array('f', bytes(12 * point_count))
        out_corners, out_counts, out_from = (array('i', bytes(4 * k)) for k in (corner_count, face_count, face_count))
        native.MR_smooth_split_geometry(handle, _address(out_points), _address(out_corners), _address(out_counts), _address(out_from))
        tag = lambda data: 'smooth:' + blake2b(memoryview(data), digest_size=16).hexdigest()

        def by_corner(values, unit=False):
            width = _width(values)
            flat = _flat(values, width)
            if flat is None:
                raise ValueError('corner values')
            out = array('f', bytes(4 * width * corner_count))
            native.MR_smooth_split_corners(handle, _address(flat), width, _address(out), int(unit))
            return run(out, width, tag(out))

        def by_point(values):
            width = _width(values)
            flat = _flat(values, width)
            if flat is None:
                raise ValueError('point values')
            out = array('f', bytes(4 * width * point_count))
            native.MR_smooth_split_points(handle, _address(flat), width, _address(out))
            return run(out, width, tag(out))
        total = len(corners)
        result = {'vertices': run(out_points, 3, tag(out_points)), 'faces': Faces(out_corners, out_counts, tag(out_corners)),
                  'smooth_split': n}
        closing = mesh.get('vertices_close')
        if closing is not None and len(closing) == len(points) // 3:
            flat_closing = _flat(closing, 3)
            if flat_closing is None:
                raise ValueError('closing points')
            moved = array('f', bytes(12 * point_count))
            native.MR_smooth_split_moved(handle, _address(flat_closing), float(SHAPE), _address(moved))
            result['vertices_close'] = run(moved, 3, tag(moved))
        for name in ('normals', 'uvs'):
            if mesh.get(name) is not None and len(mesh[name]) == total:
                result[name] = by_corner(mesh[name], name == 'normals')
        if mesh.get('uv_sets'):
            result['uv_sets'] = {name: by_corner(values) for name, values in mesh['uv_sets'].items() if len(values) == total}
        if mesh.get('corner_attributes'):
            result['corner_attributes'] = {name: dict(entry, values=by_corner(entry['values']))
                                           for name, entry in mesh['corner_attributes'].items() if len(entry['values']) == total}
        if mesh.get('point_attributes'):
            result['point_attributes'] = {name: dict(entry, values=by_point(entry['values']))
                                          for name, entry in mesh['point_attributes'].items() if len(entry['values']) == len(points) // 3}
        if mesh.get('face_materials') is not None and len(mesh['face_materials']) == len(sizes):
            tags = mesh['face_materials']
            result['face_materials'] = [tags[i] for i in out_from]
        return result
    except (ValueError, TypeError, IndexError):
        return None
    finally:
        native.MR_smooth_split_free(handle)
