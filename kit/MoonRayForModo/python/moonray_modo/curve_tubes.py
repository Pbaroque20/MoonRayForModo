"""Curves as tubes of polygons, for MoonLightIPR, which draws only meshes.

MoonRay has curves of its own and is given them as they are. MoonLightIPR's one kind of geometry
is the triangle, so each strand becomes a tube with closed ends whose sides are shaded smooth:
eight-sided while there are few enough points, four-sided for the thousands of strands of hair,
where a strand is too thin to tell. The tubes are kept by what the curves hold, so thousands
of strands are built once.
"""
import hashlib
import itertools
import math
from array import array

# Points beyond which a tube has four sides rather than eight.
MANY = 40000
BUILT = {}


def digest(entry):
    radii = entry.get('radii') or [entry.get('radius', .001)]
    parts = (array('d', itertools.chain.from_iterable(entry['vertices'])), array('q', entry['counts']), array('d', radii),
             array('d', itertools.chain.from_iterable(entry.get('uvs') or [])))
    held = hashlib.sha1()
    for part in parts:
        held.update(part.tobytes())
        held.update(b'|')
    return held.digest()


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def unit(v, fallback):
    length = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return (v[0] / length, v[1] / length, v[2] / length) if length > 1e-12 else fallback


def build(entry):
    """The points, four-sided faces and per-corner UVs of every strand's tube."""
    points, counts = entry['vertices'], entry['counts']
    radii = entry.get('radii') or [entry.get('radius', .001)]
    uvs = entry.get('uvs') or []
    per_point = len(radii) == len(points)
    per_strand = len(radii) == len(counts) and not per_point
    uv_per_point = len(uvs) == len(points)
    SIDES = 8 if len(points) <= MANY else 4
    ring = [(math.cos(2 * math.pi * k / SIDES), math.sin(2 * math.pi * k / SIDES)) for k in range(SIDES)]
    vertices, faces, corners = [], [], []
    start = 0
    for strand, count in enumerate(counts):
        if count < 2:
            start += count
            continue
        first = len(vertices)
        tangent = (0.0, 1.0, 0.0)
        side = None
        for i in range(count):
            here = points[start + i]
            before, after = points[start + max(0, i - 1)], points[start + min(count - 1, i + 1)]
            tangent = unit((after[0] - before[0], after[1] - before[1], after[2] - before[2]), tangent)
            if side is None:
                helper = (1.0, 0.0, 0.0) if abs(tangent[0]) < .9 else (0.0, 1.0, 0.0)
                side = unit(cross(tangent, helper), (0.0, 0.0, 1.0))
            else:
                # Carry the last ring's frame along, so that the tube does not twist.
                along = side[0] * tangent[0] + side[1] * tangent[1] + side[2] * tangent[2]
                side = unit((side[0] - along * tangent[0], side[1] - along * tangent[1], side[2] - along * tangent[2]), side)
            up = cross(tangent, side)
            radius = radii[start + i] if per_point else radii[strand] if per_strand else radii[0]
            for c, s in ring:
                vertices.append([here[0] + radius * (c * side[0] + s * up[0]), here[1] + radius * (c * side[1] + s * up[1]),
                                 here[2] + radius * (c * side[2] + s * up[2])])
        for i in range(count - 1):
            low, high = first + i * SIDES, first + (i + 1) * SIDES
            if uvs:
                near = uvs[start + i] if uv_per_point else uvs[strand]
                far = uvs[start + i + 1] if uv_per_point else uvs[strand]
            for k in range(SIDES):
                following = (k + 1) % SIDES
                faces.append([low + k, low + following, high + following, high + k])
                if uvs:
                    corners += [near, near, far, far]
        # Close the ends, unless the strand comes to a point there.
        for i, turn in ((0, -1), (count - 1, 1)):
            radius = radii[start + i] if per_point else radii[strand] if per_strand else radii[0]
            if radius <= 0:
                continue
            rim = [first + i * SIDES + k for k in range(SIDES)][::turn]
            faces.append(rim)
            if uvs:
                corners += [uvs[start + i] if uv_per_point else uvs[strand]] * SIDES
        start += count
    return vertices, faces, corners


def meshes(extras):
    """The curve geometries among a scene's extra geometry, each as a mesh MoonLightIPR can draw."""
    result = []
    for entry in extras:
        if entry.get('kind') != 'curves' or not entry.get('vertices'):
            continue
        key = digest(entry)
        if key not in BUILT:
            if len(BUILT) >= 16:
                BUILT.pop(next(iter(BUILT)))
            BUILT[key] = build(entry)
        vertices, faces, corners = BUILT[key]
        if not faces:
            continue
        mesh = {'name': entry.get('name', 'Curves'), 'identity': entry['identity'], 'source_item': entry.get('source_item', ''),
                'vertices': vertices, 'faces': faces, 'material': entry.get('material', ''), 'matrix': entry.get('matrix'), 'smooth': True}
        if mesh['matrix'] is None:
            del mesh['matrix']
        if corners:
            mesh['uvs'] = corners
        if 'visibility' in entry:
            mesh['visibility'] = entry['visibility']
        result.append(mesh)
    return result
