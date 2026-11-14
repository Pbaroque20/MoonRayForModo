"""UVs for Modo's evaluated geometry where Modo gives none.

Modo's render cache hands over only the UV maps its own Shader Tree textures read: a mesh shaded by a MoonRay graph
alone (an Ocean, a graph image) comes through it with no UVs at all, so a realtime preview read the ocean at one place
and could not fit it to the mesh (the sea blown out). Here such a surface borrows its mesh's own UV maps: each of its
triangles finds the triangle of the mesh it lies on (closest by its middle) and its corners take that triangle's UVs
where they stand on it. Modo's subdividing and cutting of the mesh keep them; a deformer that moves points far from
the mesh's points as read (deformed) leaves them as close as it can."""
import math

TXUV = 0x54585556
# Graph nodes that read a mesh's UVs without a descriptor of their own (coordinates.descriptors names the others).
UV_NODES = {'ocean', 'ocean_foam', 'image', 'texcoord', 'normalmap'}


def wanted(material):
    """Whether a material reads its mesh's UVs."""
    from . import coordinates
    try:
        if any(d.get('projection', 'uv') == 'uv' for d in coordinates.descriptors({'': material}).values()):
            return True
    except Exception:
        pass
    if material.get('uv_map'):
        return True
    for row in material.get('material_stack') or [material]:
        for source in [row] + list(row.get('native_dependencies') or []):
            for node in ((source.get('node_graph') or {}).get('nodes') or {}).values():
                if node.get('type') in UV_NODES:
                    return True
    return False


def source_mesh(item):
    """The mesh item an evaluated surface's item stands for: itself, or an instance's source."""
    seen = set()
    while item is not None and item.type == 'meshInst':
        if item.id in seen:
            return None
        seen.add(item.id)
        links = item.itemGraph('source').forward()
        item = links[0] if len(links) == 1 else None
    return item if item is not None and item.type == 'mesh' else None


def read_mesh(item):
    """The mesh as read for its UVs (deformed): a dict of its points, the UV maps' names and each map's (u, v) at
    every corner, each polygon's corners' start, each point's place and which polygons each point is a corner of; its
    triangles (its polygons fanned) made when first needed (fanned). None where it has no UV maps or cannot be read."""
    import modo
    from . import mesh_reader
    try:
        held = mesh_reader.read(modo.meshgeometry.MeshProvider.meshFromMeshChannel(item._item, 'deformed'))
    except Exception:
        held = None
    if held is None or not held.uv_names:
        return None
    from itertools import accumulate
    flat = list(held.vertices.data) if hasattr(held.vertices, 'data') else [c for v in held.vertices for c in v]
    points = list(zip(flat[0::3], flat[1::3], flat[2::3]))
    indices = list(held.indices)
    counts = list(held.counts)
    starts = list(accumulate(counts, initial=0))
    owners = [[] for _ in points]
    for polygon, count in enumerate(counts):
        first = starts[polygon]
        for i in indices[first:first + count]:
            owners[i].append(polygon)
    return {'points': points, 'names': list(held.uv_names), 'counts': counts, 'starts': starts, 'indices': indices,
            'uvs': [list(v.data) if hasattr(v, 'data') else [c for uv in v for c in uv] for v in held.uv_values],
            'place': {p: i for i, p in enumerate(points)}, 'owners': owners}


def fanned(held):
    """The mesh's polygons fanned into triangles: their points, and each map's three (u, v) of each."""
    if 'triangles' not in held:
        triangles, maps = [], [[] for _ in held['names']]
        indices, starts = held['indices'], held['starts']
        for polygon, count in enumerate(held['counts']):
            at = starts[polygon]
            for k in range(1, count - 1):
                corners = (at, at + k, at + k + 1)
                triangles.append(tuple(indices[c] for c in corners))
                for m, values in enumerate(held['uvs']):
                    maps[m].append(tuple((values[2 * c], values[2 * c + 1]) for c in corners))
        held['triangles'], held['maps'] = triangles, maps
    return held['triangles'], held['maps']


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _closest(p, a, b, c):
    """The squared distance from p to triangle abc (Ericson's closest point)."""
    ab, ac, ap = _sub(b, a), _sub(c, a), _sub(p, a)
    d1, d2 = _dot(ab, ap), _dot(ac, ap)
    if d1 <= 0 and d2 <= 0:
        q = a
    else:
        bp = _sub(p, b)
        d3, d4 = _dot(ab, bp), _dot(ac, bp)
        cp = _sub(p, c)
        d5, d6 = _dot(ab, cp), _dot(ac, cp)
        vc, vb, va = d1 * d4 - d3 * d2, d5 * d2 - d1 * d6, d3 * d6 - d5 * d4
        if d3 >= 0 and d4 <= d3:
            q = b
        elif vc <= 0 and d1 >= 0 and d3 <= 0:
            t = d1 / (d1 - d3)
            q = (a[0] + t * ab[0], a[1] + t * ab[1], a[2] + t * ab[2])
        elif d6 >= 0 and d5 <= d6:
            q = c
        elif vb <= 0 and d2 >= 0 and d6 <= 0:
            t = d2 / (d2 - d6)
            q = (a[0] + t * ac[0], a[1] + t * ac[1], a[2] + t * ac[2])
        elif va <= 0 and (d4 - d3) >= 0 and (d5 - d6) >= 0:
            t = (d4 - d3) / ((d4 - d3) + (d5 - d6))
            q = (b[0] + t * (c[0] - b[0]), b[1] + t * (c[1] - b[1]), b[2] + t * (c[2] - b[2]))
        else:
            denominator = 1.0 / (va + vb + vc)
            v, w = vb * denominator, vc * denominator
            q = (a[0] + ab[0] * v + ac[0] * w, a[1] + ab[1] * v + ac[1] * w, a[2] + ab[2] * v + ac[2] * w)
    d = _sub(p, q)
    return _dot(d, d)


def _weights(p, a, b, c):
    """p's barycentric weights on abc's plane (beyond its edges as far as p is)."""
    v0, v1, v2 = _sub(b, a), _sub(c, a), _sub(p, a)
    d00, d01, d11, d20, d21 = _dot(v0, v0), _dot(v0, v1), _dot(v1, v1), _dot(v2, v0), _dot(v2, v1)
    denominator = d00 * d11 - d01 * d01
    if abs(denominator) < 1e-30:
        return 1.0, 0.0, 0.0
    v = (d11 * d20 - d01 * d21) / denominator
    w = (d00 * d21 - d01 * d20) / denominator
    return 1.0 - v - w, v, w


class Finder:
    """The mesh's triangles in a grid of cells, for the one closest to a point."""

    def __init__(self, points, triangles):
        self.points, self.triangles = points, triangles
        if not triangles:
            self.size, self.cells = 1.0, {}
            return
        low = [min(p[i] for p in points) for i in range(3)]
        high = [max(p[i] for p in points) for i in range(3)]
        span = max(high[i] - low[i] for i in range(3)) or 1.0
        # About two triangles a cell across the mesh's surface.
        self.size = max(span / max(1.0, math.sqrt(len(triangles) / 2.0)), span * 1e-4)
        self.cells = {}
        for t, (i, j, k) in enumerate(triangles):
            a, b, c = points[i], points[j], points[k]
            lo = [int(math.floor(min(a[d], b[d], c[d]) / self.size)) for d in range(3)]
            hi = [int(math.floor(max(a[d], b[d], c[d]) / self.size)) for d in range(3)]
            for x in range(lo[0], hi[0] + 1):
                for y in range(lo[1], hi[1] + 1):
                    for z in range(lo[2], hi[2] + 1):
                        self.cells.setdefault((x, y, z), []).append(t)
        self.reach = max(int(math.ceil(span / self.size)) + 1, 1)

    def closest(self, p):
        if not self.triangles:
            return None
        cell = [int(math.floor(p[d] / self.size)) for d in range(3)]
        best, found, ring = None, None, 0
        while ring <= self.reach:
            for x in range(cell[0] - ring, cell[0] + ring + 1):
                for y in range(cell[1] - ring, cell[1] + ring + 1):
                    for z in range(cell[2] - ring, cell[2] + ring + 1):
                        if max(abs(x - cell[0]), abs(y - cell[1]), abs(z - cell[2])) != ring:
                            continue
                        for t in self.cells.get((x, y, z), ()):
                            i, j, k = self.triangles[t]
                            d = _closest(p, self.points[i], self.points[j], self.points[k])
                            if best is None or d < best:
                                best, found = d, t
            # A triangle found in this ring may be beaten by one in the next (the cells are cubes, the distance round).
            if found is not None and math.sqrt(best) <= ring * self.size:
                break
            ring += 1
        return found


def borrowed(segment, held, finder):
    """One evaluated segment's UV sets from the mesh as read (read_mesh): for each map, a (u, v) at each corner. A face
    whose corners are all the mesh's points, and of one polygon, takes that polygon's own corners' UVs (exact, and
    quick: a mesh Modo only cut into triangles); any other finds the triangle it lies on (finder: a list, given its
    Finder when one is first needed)."""
    from .rows import corners as flat_corners, counts as flat_counts, numbers
    points = held['points']
    place, owners, starts, indices, uvs = held['place'], held['owners'], held['starts'], held['indices'], held['uvs']
    vertices, faces = segment['vertices'], segment['faces']
    flat = numbers(vertices, 3)
    flat = list(flat) if flat is not None else [c for v in vertices for c in v]
    at_point = [place.get(p) for p in zip(flat[0::3], flat[1::3], flat[2::3])]
    corners, sizes = flat_corners(faces), flat_counts(faces)
    if corners is None or sizes is None:
        sizes = [len(face) for face in faces]
        corners = [i for face in faces for i in face]
    corners = list(corners)
    if 'threes' not in held:
        held['threes'] = {tuple(sorted(indices[s:s + 3])): s for s, n in zip(starts, held['counts']) if n == 3}
    threes = held['threes']
    result = [[] for _ in uvs]
    at = 0
    for size in sizes:
        own = [at_point[corners[at + k]] for k in range(size)]
        polygon = None
        if size == 3 and None not in own:
            # One of the mesh's own triangles, as Modo mostly gives them back.
            first = threes.get(tuple(sorted(own)))
            if first is not None:
                for i in own:
                    c = first if indices[first] == i else first + 1 if indices[first + 1] == i else first + 2
                    for values, source in zip(result, uvs):
                        values.append(source[2 * c:2 * c + 2])
                at += size
                continue
        if None not in own:
            rest = [owners[i] for i in own[1:]]
            for candidate in owners[own[0]]:
                if all(candidate in held_by for held_by in rest):
                    polygon = candidate
                    break
        if polygon is not None:
            first, last = starts[polygon], starts[polygon + 1]
            for i in own:
                c = indices.index(i, first, last)
                for values, source in zip(result, uvs):
                    values.append(source[2 * c:2 * c + 2])
            at += size
            continue
        places = [(flat[3 * corners[at + k]], flat[3 * corners[at + k] + 1], flat[3 * corners[at + k] + 2]) for k in range(size)]
        middle = tuple(sum(p[d] for p in places) / size for d in range(3))
        if not finder:
            # Built only where a face is not one of the mesh's own (its grid is a while for a big mesh).
            finder.append(Finder(points, fanned(held)[0]))
        triangles, maps = fanned(held)
        t = finder[0].closest(middle)
        for p in places:
            if t is None:
                for values in result:
                    values.append([0.0, 0.0])
                continue
            i, j, k = triangles[t]
            wa, wb, wc = _weights(p, points[i], points[j], points[k])
            for m, values in enumerate(result):
                ua, ub, uc = maps[m][t]
                values.append([wa * ua[0] + wb * ub[0] + wc * uc[0], wa * ua[1] + wb * ub[1] + wc * uc[1]])
        at += size
    return result


def fill(prototype, item, readings):
    """The prototype with its mesh's UV maps where Modo gave it none (features and each segment's uv_sets, a value at
    each corner); the prototype as it was where the mesh has none or cannot be read. readings: the meshes read so far
    by item id, to read each once."""
    if any(f['type'] == TXUV for f in prototype['features']):
        return prototype
    mesh = source_mesh(item)
    if mesh is None:
        return prototype
    if mesh.id not in readings:
        held = read_mesh(mesh)
        readings[mesh.id] = (held, [])
    held, finder = readings[mesh.id]
    if held is None:
        return prototype
    segments = []
    for segment in prototype['segments']:
        if segment['faces'] and len(segment['faces'][0]) >= 3:
            sets = borrowed(segment, held, finder)
            if not segment.get('face_varying'):
                # A value at each point, where Modo gives the segment's values so: the first corner's at each.
                from .rows import corners as flat_corners
                corners = flat_corners(segment['faces'])
                corners = corners if corners is not None else [i for face in segment['faces'] for i in face]
                count = len(segment['vertices'])
                points = []
                for values in sets:
                    each = [None] * count
                    for c, i in enumerate(corners):
                        if each[i] is None:
                            each[i] = values[c]
                    points.append([v if v is not None else [0.0, 0.0] for v in each])
                sets = points
            segment = dict(segment, uv_sets=sets)
        segments.append(segment)
    features = list(prototype['features']) + [{'type': TXUV, 'name': name, 'offset': -1} for name in held['names']]
    return dict(prototype, features=features, segments=segments)
