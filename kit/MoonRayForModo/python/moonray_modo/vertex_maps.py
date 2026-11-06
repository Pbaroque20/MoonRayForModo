"""A mesh's weight and colour vertex maps, as values its MoonRay shape carries for its materials to read.

Each weight map is a number, each RGB map a colour, and each RGBA map a colour with its alpha as a number of its own
(name_alpha), under the map's own name: what MoonRay's AttributeMap (and a material's primitive attribute input) reads
by that name. A map with one value for each point goes to MoonRay once for each point; a map that holds values set
apart on some polygons (Modo's discontinuous values, a value per face corner) goes once for each corner of each
polygon, so that each face keeps its own. Polygons are counted as the scene reader counts them: surface polygons of
three corners or more.

Reading a map's points is quick; its polygons are only read where it holds values set apart, as that costs a call for
each corner."""
import ctypes
import os
import struct
import tempfile
from array import array

import lx
import lxifc
import lxu.utils

KINDS = {lx.symbol.i_VMAP_WEIGHT: ('float', 1), lx.symbol.i_VMAP_RGB: ('color', 3), lx.symbol.i_VMAP_RGBA: ('color', 4)}
NOT_SURFACE = ('CURV', 'BEZR', 'BSPL', 'LINE', 'OPNT')


def listed(mesh):
    """The mesh's weight, RGB and RGBA maps, as (name, map type, its ID), in name order."""
    accessor = lx.object.MeshMap(mesh.MeshMapAccessor())
    if not accessor.test():
        return []
    found = []

    class Maps(lxifc.Visitor):
        def vis_Evaluate(self):
            kind = accessor.Type()
            if kind in KINDS:
                found.append((accessor.Name(), kind, int(accessor.ID())))
    accessor.Enumerate(lx.symbol.iMARK_ANY, Maps(), 0)
    return sorted(found)


def set_apart(mesh, map_id):
    """Whether a map holds values set apart on some polygon (Modo's discontinuous values)."""
    accessor = lx.object.MeshMap(mesh.MeshMapAccessor())
    accessor.Select(map_id)
    seen = []

    class Any(lxifc.Visitor):
        def vis_Evaluate(self):
            seen.append(True)
    # Modo walks the map's discontinuous values with a point and a polygon accessor of its own.
    accessor.EnumerateDiscontinuous(Any(), lx.object.Point(mesh.PointAccessor()), lx.object.Polygon(mesh.PolygonAccessor()))
    return bool(seen)


def point_values(mesh, map_id, size):
    """The map's value at each point, in point order; a point with none has zeros."""
    points = lx.object.Point(mesh.PointAccessor())
    storage = lx.object.storage('f', size)
    values = []
    for index in range(mesh.PointCount()):
        points.SelectByIndex(index)
        values.append(list(storage.get()) if points.MapEvaluate(map_id, storage) else [0.0] * size)
    return values


def corner_values(mesh, map_id, size):
    """The map's value at each corner of each surface polygon, in the order the scene reader counts polygons; a corner
    with none has zeros."""
    polygons = lx.object.Polygon(mesh.PolygonAccessor())
    storage = lx.object.storage('f', size)
    result = []
    for index in range(mesh.PolygonCount()):
        polygons.SelectByIndex(index)
        if lxu.utils.decodeID4(polygons.Type()) in NOT_SURFACE:
            continue
        count = polygons.VertexCount()
        if count < 3:
            continue
        corners = []
        for corner in range(count):
            corners.append(list(storage.get()) if polygons.MapEvaluate(map_id, polygons.VertexByIndex(corner), storage) else [0.0] * size)
        result.append(corners)
    return result


def read_by_python(mesh):
    """Every weight and colour map of the mesh: {name: {'kind', 'points': [value at each point]} or
    {'kind', 'corners': [[value at each corner] for each surface polygon]}}, a value being a list of numbers. An RGBA
    map is a colour and its alpha, each under a name of its own."""
    result = {}
    for name, kind, map_id in listed(mesh):
        word, size = KINDS[kind]
        apart = set_apart(mesh, map_id)
        values = corner_values(mesh, map_id, size) if apart else point_values(mesh, map_id, size)
        key = 'corners' if apart else 'points'
        if size == 4:
            split = lambda value, part: value[:3] if part == 'color' else value[3:4]
            for part, own in (('color', name), ('float', name + '_alpha')):
                result[own] = {'kind': part, key: [[split(v, part) for v in face] for face in values] if apart else [split(v, part) for v in values]}
        else:
            result[name] = {'kind': word, key: values}
    return result


class Corners:
    """A map's values at each corner of each surface polygon, as the adapter read them: one run (rows.Rows, or
    rows.Singles for a number) cut by each polygon's number of corners; read as the list of each polygon's values."""
    __slots__ = ('values', 'counts', '_starts')

    def __init__(self, values, counts):
        self.values, self.counts, self._starts = values, counts, None

    def starts(self):
        if self._starts is None:
            from itertools import accumulate
            self._starts = array('q', accumulate(self.counts, initial=0))
        return self._starts

    def __len__(self):
        return len(self.counts)

    def __getitem__(self, face):
        starts = self.starts()
        return [self.values[k] for k in range(starts[face], starts[face + 1])]

    def __iter__(self):
        return (self[face] for face in range(len(self.counts)))


def _library():
    from . import mesh_reader
    library = mesh_reader.bridge()
    if library is None:
        return None
    try:
        reader = library.MR_vertex_maps
    except AttributeError:
        return None
    reader.argtypes, reader.restype = [ctypes.c_void_p, ctypes.c_char_p], ctypes.c_char_p
    return reader


def read_natively(mesh):
    """read() by the geometry adapter in one call (native-modo/vertex_maps.cpp); None where it cannot."""
    reader = _library()
    if reader is None:
        return None
    try:
        address = mesh.__peekobj__()
    except AttributeError:
        return None
    handle, name = tempfile.mkstemp(prefix='MoonRay-maps-', suffix='.bin')
    os.close(handle)
    try:
        if reader(ctypes.c_void_p(address), name.encode('utf-8')):
            return None
        with open(name, 'rb') as stream:
            return _parse(stream.read())
    except (OSError, ValueError, struct.error):
        return None
    finally:
        try:
            os.unlink(name)
        except OSError:
            pass


def _parse(data):
    """The adapter's file (vertex_maps.cpp) as read() gives the maps."""
    from hashlib import blake2b
    from .rows import run
    if data[:4] != b'MVM1':
        raise ValueError('Not vertex maps from the geometry adapter')
    at = 4

    def whole():
        nonlocal at
        value, = struct.unpack_from('<i', data, at)
        at += 4
        return value

    def numbers(kind, count):
        nonlocal at
        values = array(kind)
        size = values.itemsize * count
        values.frombytes(data[at:at + size])
        if len(values) != count:
            raise ValueError('The geometry adapter wrote less than it said')
        at += size
        return values
    point_count, faces = whole(), whole()
    counts = numbers('i', faces)
    corner_total = sum(counts)
    result = {}
    for _ in range(whole()):
        size = whole()
        name = data[at:at + size].decode('utf-8', errors='replace')
        at += size
        kind, width, apart = whole(), whole(), whole()
        values = numbers('f', width * (corner_total if apart else point_count))
        held = run(values, width, 'map:%d:%s' % (width, blake2b(memoryview(values), digest_size=16).hexdigest()))
        word = 'color' if kind == 1 else 'float'
        result[name] = {'kind': word, 'corners': Corners(held, counts)} if apart else {'kind': word, 'points': held}
    return result


# Below this many points a mesh's maps are read in Python: the adapter's file costs about a millisecond, Python a few
# microseconds a value (a mesh of 21,600 polygons and six maps: 1.04 s in Python, 0.08 s by the adapter).
NATIVE_POINTS = 100


def read(mesh):
    """read_by_python()'s maps, read by the geometry adapter where it can be (a point's values as rows.Rows, a
    corner's as Corners), else by Python."""
    held = read_natively(mesh) if mesh.PointCount() >= NATIVE_POINTS else None
    return held if held is not None else read_by_python(mesh)


def strings(maps, held, polygon_sizes, point_count):
    """Add the words a mesh keeps for MoonRay (held: {name: {'rate', 'values'}}), as a MoonRay scene brought in had
    them, to its maps as the kind 'string': by point, or by each corner of each surface polygon (a word by face is
    given to each of its corners). Those whose count no longer matches the mesh are left out and named."""
    missed = []
    for name, entry in (held or {}).items():
        rate, values = entry.get('rate'), list(entry.get('values') or [])
        if rate == 'points' and len(values) == point_count:
            maps[name] = {'kind': 'string', 'points': [[v] for v in values]}
        elif rate == 'faces' and len(values) == len(polygon_sizes):
            maps[name] = {'kind': 'string', 'corners': [[[v]] * size for v, size in zip(values, polygon_sizes)]}
        elif rate == 'corners' and len(values) == sum(polygon_sizes):
            corners, offset = [], 0
            for size in polygon_sizes:
                corners.append([[v] for v in values[offset:offset + size]]); offset += size
            maps[name] = {'kind': 'string', 'corners': corners}
        else:
            missed.append(name)
    return missed


def as_vectors(maps, kinds):
    """Give back as vectors the colour maps that hold them (kinds: {name: 'vec2' or 'vec3'}, kept on the mesh where a
    MoonRay scene's vectors came in as colour maps); a vec2 keeps the first two of each colour's three numbers."""
    for name, kind in kinds.items():
        held = maps.get(name)
        if not held or held['kind'] != 'color' or kind not in ('vec2', 'vec3'):
            continue
        size = 2 if kind == 'vec2' else 3
        held['kind'] = kind
        if 'points' in held:
            held['points'] = _first(held['points'], size) or [list(v)[:size] for v in held['points']]
        elif isinstance(held['corners'], Corners):
            corners = held['corners']
            held['corners'] = Corners(_first(corners.values, size) or [list(v)[:size] for v in corners.values], corners.counts)
        else:
            held['corners'] = [[list(v)[:size] for v in face] for face in held['corners']]
    return maps


def _first(values, size):
    """The first size numbers of each of a colour's runs of three (rows.Rows), as a run of its own; None where the
    values are not such a run."""
    from .rows import Rows, numbers
    flat = numbers(values, 3)
    if flat is None:
        return None
    if size == 3:
        return values
    kept = array('f', bytes(4 * size * len(values)))
    for k in range(size):
        kept[k::size] = flat[k::3]
    return Rows(kept, size, '%s:first%d' % (values.digest, size))


def for_faces(maps, ordinals):
    """What one shape made of some of the mesh's polygons carries: the point maps whole (the shape holds every point),
    and the corner maps for its own polygons, in its own order (ordinals, as the scene reader counts polygons)."""
    points = {name: {'kind': held['kind'], 'values': held['points']} for name, held in maps.items() if 'points' in held}
    corners = {}
    places = {}
    for name, held in maps.items():
        if 'corners' not in held:
            continue
        own = held['corners']
        values = None
        if isinstance(own, Corners):
            values = _gathered(own, ordinals, places)
        if values is None:
            values = [value for ordinal in ordinals for value in own[ordinal]]
        corners[name] = {'kind': held['kind'], 'values': values}
    return points, corners


def _gathered(own, ordinals, places):
    """A Corners' values for some of its polygons, in their order, as a run of their own (by the adapter): the run itself
    where they are every polygon in order. places keeps the corners chosen, the same for every map of the mesh."""
    from hashlib import blake2b
    from .rows import Rows, gather, run
    values = own.values
    if not isinstance(values, Rows) or values.width > 4:
        return None
    count = len(own.counts)
    if len(ordinals) == count and (not count or (ordinals[0] == 0 and ordinals[-1] == count - 1 and list(ordinals) == list(range(count)))):
        return values
    key = id(own.counts)
    if key not in places:
        starts = own.starts()
        chosen = array('I')
        for ordinal in ordinals:
            chosen.extend(range(starts[ordinal], starts[ordinal + 1]))
        places[key] = chosen
    kept = gather(values.data, values.data.itemsize * values.width, places[key])
    if kept is None:
        return None
    return run(kept, values.width, 'map:%d:%s' % (values.width, blake2b(memoryview(kept), digest_size=16).hexdigest()))
