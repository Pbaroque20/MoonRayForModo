"""The VDB volume under a point of the preview's picture, for Select Volume Here.

A volume is found where it is thick, not anywhere in its box: the ray through the point is marched through the coarse
copy of each VDB's grid the viewport already keeps (vdb_preview: POINT_CELLS cells along its longest edge, its values and
the transform from the unit cube into the grid's own space), placed as the item is, and a volume is met at the first
cell at least THICK of its thickest, as the viewport draws its points. Both kinds of VDB are looked through: the kit's
own MoonRay items (Load VDB File; a sequence by the frame's own file) and VDB volumes read with a MoonRay scene.
"""
import math
import struct
from array import array
from pathlib import Path

from .focus import IDENTITY, ray

THICK = 0.05


def candidates(scene):
    """[(the item's identity, its name, the VDB file, its density grid, its placement)] for the scene's VDB volumes."""
    found = []
    for entry in scene.get('extra_geometry', []):
        if entry.get('kind') == 'vdb' and entry.get('file'):
            found.append((str(entry.get('identity') or ''), entry.get('name', 'Volume'), entry['file'],
                          entry.get('density_grid') or 'density', entry.get('matrix') or IDENTITY))
    if scene.get('entities'):
        from .entities import checked, value
        for entity in checked(scene):
            if entity.get('class') == 'VdbGeometry' and value(entity, 'model'):
                found.append((str(entity.get('identity') or ''), entity.get('name', 'VDB'), value(entity, 'model'),
                              value(entity, 'density_grid') or 'density', entity.get('matrix') or IDENTITY))
    return found


def coarse(path, grid):
    """The viewport's coarse copy of a grid: (counts, largest, the 16 numbers from the unit cube into the grid's space,
    the values, x fastest), or None while it is still being read (it is asked for then) or where it cannot be."""
    from . import vdb_preview
    target = vdb_preview.coarse_file(path, grid)
    if target is None:
        return None
    data = Path(target).read_bytes()
    if len(data) < 84 or data[:4] != b'MLV1':
        return None
    counts = struct.unpack_from('<3I', data, 4)
    largest = struct.unpack_from('<f', data, 16)[0]
    matrix = list(struct.unpack_from('<16f', data, 20))
    cells = counts[0] * counts[1] * counts[2]
    if not cells or len(data) < 84 + cells * 4:
        return None
    values = array('f')
    values.frombytes(data[84:84 + cells * 4])
    return counts, largest, matrix, values


def product(a, b):
    """Two placements one after the other, basis vectors in rows as Modo holds them."""
    return [sum(a[row * 4 + k] * b[k * 4 + column] for k in range(4)) for row in range(4) for column in range(4)]


def inverse4(m):
    """The inverse of a placement (rows of basis vectors, then the offset), or None if it is flat."""
    from .focus import inverse
    back = inverse(m)
    if back is None:
        return None
    offset = m[12:15]
    moved = [-(offset[0] * back[k] + offset[1] * back[3 + k] + offset[2] * back[6 + k]) for k in range(3)]
    return [back[0], back[1], back[2], 0.0, back[3], back[4], back[5], 0.0, back[6], back[7], back[8], 0.0] + moved + [1.0]


def march(eye, direction, counts, largest, unit, placed, nearest):
    """How far along the ray (in its own units, as focus.hit counts depth) the first thick cell is, or None."""
    world = product(unit, [float(v) for v in placed])
    back = inverse4(world)
    if back is None:
        return None
    o = [eye[0] * back[k] + eye[1] * back[4 + k] + eye[2] * back[8 + k] + back[12 + k] for k in range(3)]
    d = [direction[0] * back[k] + direction[1] * back[4 + k] + direction[2] * back[8 + k] for k in range(3)]
    start, end = 0.0, nearest
    for k in range(3):
        if abs(d[k]) < 1e-15:
            if o[k] < 0.0 or o[k] > 1.0:
                return None
            continue
        one, two = (0.0 - o[k]) / d[k], (1.0 - o[k]) / d[k]
        if one > two:
            one, two = two, one
        start, end = max(start, one), min(end, two)
        if start > end:
            return None
    nx, ny, nz = counts
    length = math.sqrt(sum(v * v for v in d))
    if length <= 0.0:
        return None
    # Half a cell at a time, in the unit cube.
    step = 0.5 / (max(counts) * length)
    threshold = THICK * largest
    t = start + step * 0.5
    return t, step, end, o, d, threshold, (nx, ny, nz)


def thick_at(found, values):
    t, step, end, o, d, threshold, (nx, ny, nz) = found
    while t <= end:
        x, y, z = o[0] + d[0] * t, o[1] + d[1] * t, o[2] + d[2] * t
        i, j, k = min(nx - 1, max(0, int(x * nx))), min(ny - 1, max(0, int(y * ny))), min(nz - 1, max(0, int(z * nz)))
        if values[(k * ny + j) * nx + i] >= threshold:
            return t
        t += step
    return None


def volume_at(scene, u, v):
    """The nearest VDB volume thick under (u, v), 0..1 from the picture's top left: (its depth, its identity, its name),
    or (None, the names of volumes not yet read) where none is found."""
    eye, direction = ray(scene['camera'], scene['width'], scene['height'], u, v)
    nearest, struck, waiting = math.inf, None, []
    for identity, name, path, grid, placed in candidates(scene):
        try:
            held = coarse(path, grid)
        except OSError:
            continue
        if held is None:
            waiting.append(name)
            continue
        counts, largest, unit, values = held
        if not largest > 0:
            continue
        found = march(eye, direction, counts, largest, unit, placed, nearest)
        if found is None:
            continue
        depth = thick_at(found, values)
        if depth is not None and depth < nearest:
            nearest, struck = depth, (depth, identity, name)
    return struck if struck is not None else (None, waiting)
