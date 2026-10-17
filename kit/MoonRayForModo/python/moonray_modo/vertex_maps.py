"""A mesh's weight and colour vertex maps, as values its MoonRay shape carries for its materials to read.

Each weight map is a number, each RGB map a colour, and each RGBA map a colour with its alpha as a number of its own
(name_alpha), under the map's own name: what MoonRay's AttributeMap (and a material's primitive attribute input) reads
by that name. A map with one value for each point goes to MoonRay once for each point; a map that holds values set
apart on some polygons (Modo's discontinuous values, a value per face corner) goes once for each corner of each
polygon, so that each face keeps its own. Polygons are counted as the scene reader counts them: surface polygons of
three corners or more.

Reading a map's points is quick; its polygons are only read where it holds values set apart, as that costs a call for
each corner."""
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


def read(mesh):
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
            held['points'] = [list(v)[:size] for v in held['points']]
        else:
            held['corners'] = [[list(v)[:size] for v in face] for face in held['corners']]
    return maps


def for_faces(maps, ordinals):
    """What one shape made of some of the mesh's polygons carries: the point maps whole (the shape holds every point),
    and the corner maps for its own polygons, in its own order (ordinals, as the scene reader counts polygons)."""
    points = {name: {'kind': held['kind'], 'values': held['points']} for name, held in maps.items() if 'points' in held}
    corners = {name: {'kind': held['kind'], 'values': [value for ordinal in ordinals for value in held['corners'][ordinal]]}
               for name, held in maps.items() if 'corners' in held}
    return points, corners
