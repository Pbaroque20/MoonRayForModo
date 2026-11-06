"""Curves as MoonLightIPR draws them: round segments, which the GPU intersects as curves.

MoonRay takes a strand as the line through its points, as Bezier control points or as B-spline control points.
MoonLightIPR has two kinds of segment. The line through a strand's points is straight segments from each point
to the next, which meet in a rounded joint. The others are cubic B-spline segments: a B-spline strand is used as
it is, and a Bezier piece becomes the four B-spline control points of the same cubic. Each segment names its
first control point; the ones after it complete it.
"""
import hashlib
import itertools
import math
import struct
from array import array

LINEAR, BEZIER, BSPLINE = 0, 1, 2
BUILT = {}
# What was built for an entry whose lists are the very lists seen before, found without reading them through.
SAME = {}


def segments(entry, points=None):
    """(control points, a radius for each, the first control point of every segment, a strand for every control point,
    whether the segments are straight, how far along its strand every control point is). points stands in for the
    entry's own, for where they are at another moment."""
    points, counts = entry['vertices'] if points is None else points, entry['counts']
    radii = entry.get('radii') or [entry.get('radius', .001)]
    per_point = len(radii) == len(points)
    per_strand = len(radii) == len(counts) and not per_point
    kind = int(entry.get('curve_type', LINEAR))
    # One geometry holds one kind of segment; strands too short for a cubic make all of it straight.
    if kind == BSPLINE and not all(count >= 4 for count in counts if count >= 2):
        kind = LINEAR
    if kind == BEZIER and not all(count >= 4 and (count - 1) % 3 == 0 for count in counts if count >= 2):
        kind = LINEAR
    controls, widths, firsts, strands, alongs = [], [], [], [], []
    start = 0
    for strand, count in enumerate(counts):
        here = points[start:start + count]
        wide = radii[start:start + count] if per_point else [radii[strand] if per_strand else radii[0]] * count
        start += count
        if count < 2:
            continue
        if kind == BEZIER:
            pieces = (count - 1) // 3
            for piece, i in enumerate(range(0, count - 1, 3)):
                b, w = here[i:i + 4], wide[i:i + 4]
                # The B-spline control points of the cubic these four Bezier points make.
                mix = ((6, -7, 2, 0), (0, 2, -1, 0), (0, -1, 2, 0), (0, 2, -7, 6))
                firsts.append(len(controls))
                controls.extend([sum(m * p[axis] for m, p in zip(row, b)) for axis in range(3)] for row in mix)
                widths.extend(max(0.0, sum(m * v for m, v in zip(row, w))) for row in mix)
                strands.extend([strand] * 4)
                # The piece runs between its two middle control points.
                alongs.extend([piece / pieces, piece / pieces, (piece + 1) / pieces, (piece + 1) / pieces])
        else:
            # The strand's own points, shared between the segments that follow one another.
            first = len(controls)
            controls.extend(here)
            widths.extend(max(0.0, w) for w in wide)
            strands.extend([strand] * count)
            alongs.extend(i / (count - 1) for i in range(count))
            firsts.extend(range(first, first + count - (3 if kind == BSPLINE else 1)))
    return controls, widths, firsts, strands, kind == LINEAR, alongs


def chance(strand):
    """A number from 0 up to 1 that is a strand's own, for what differs from one hair to the next."""
    return int.from_bytes(hashlib.blake2b(struct.pack('<I', strand), digest_size=4).digest(), 'little') / 4294967296.0


def payload(entry, slot):
    """One curve geometry for the session: (key, payload, has coordinates, straight, moves). slot is the scene-wide
    coordinate slot its strands' coordinates serve, or None; a strand has one coordinate, or one for each of its
    points. With motion blur the entry says where its points are when the shutter closes, under vertices_close."""
    closing = entry.get('vertices_close')
    if closing is not None and (closing is entry['vertices'] or closing == entry['vertices']):
        closing = None
    if closing is not None and len(closing) != len(entry['vertices']):
        raise ValueError('Motion samples of %s must have equal point counts' % entry.get('name', ''))
    lists = (entry['vertices'], entry['counts'], entry.get('radii'), entry.get('uvs'), closing)
    plain = (len(entry['vertices']), entry.get('radius', .001), int(entry.get('curve_type', LINEAR)), slot)
    same = SAME.get(tuple(id(part) for part in lists))
    if same is not None and all(a is b for a, b in zip(same[0], lists)) and same[1] == plain:
        return same[2]
    held = hashlib.sha1()
    points = _doubles(entry['vertices'], 3)
    for part in (points, array('q', entry['counts']),
                 array('d', entry.get('radii') or [entry.get('radius', .001)]), _doubles(entry.get('uvs') or [], 2),
                 array('q', [int(entry.get('curve_type', LINEAR)), -1 if slot is None else slot]),
                 _doubles(closing or [], 3)):
        held.update(part.tobytes())
        held.update(b'|')
    signature = held.digest()
    def remembered(built):
        if len(SAME) >= 16:
            SAME.pop(next(iter(SAME)))
        SAME[tuple(id(part) for part in lists)] = (lists, plain, built)
        return built
    if signature in BUILT:
        return remembered(BUILT[signature])
    native = built_natively(entry, slot, closing, points)
    if native is not None:
        if native is False:
            return None
        positions, radii, indices, strand_values, coordinates, moved, straight = native
        return remembered(_packed(signature, positions, radii, indices, strand_values, coordinates, moved, straight, entry))
    controls, widths, firsts, strands, straight, alongs = segments(entry)
    if not firsts:
        return None
    positions, radii, indices = array('f', itertools.chain.from_iterable(controls)), array('f', widths), array('I', firsts)
    moved = array('f', itertools.chain.from_iterable(segments(entry, closing)[0])) if closing is not None else array('f')
    # How far along its strand each control point is, and its strand's own number.
    numbers = {strand: chance(strand) for strand in set(strands)}
    strand_values = array('f', itertools.chain.from_iterable(
        (along, numbers[strand], 0.0) for along, strand in zip(alongs, strands)))
    uvs = entry.get('uvs') or []
    coordinates = array('f')
    if uvs and slot is not None and len(uvs) == len(entry['counts']):
        coordinates = array('f', itertools.chain.from_iterable(uvs[strand] for strand in strands))
    elif uvs and slot is not None and len(uvs) == len(entry['vertices']):
        # One for each point: the strand's first is where it grows from, which is what colours it.
        first, start = [], 0
        for count in entry['counts']:
            first.append(uvs[start])
            start += count
        coordinates = array('f', itertools.chain.from_iterable(first[strand] for strand in strands))
    return remembered(_packed(signature, positions, radii, indices, strand_values, coordinates, moved, straight, entry))


def _packed(signature, positions, radii, indices, strand_values, coordinates, moved, straight, entry):
    if not math.isfinite(sum(positions)) or not math.isfinite(sum(radii)) or not math.isfinite(sum(moved)):
        raise ValueError('Curves %s contain a non-finite number' % entry.get('name', ''))
    if coordinates and not math.isfinite(sum(coordinates)):
        raise ValueError('Curves %s have invalid texture coordinates' % entry.get('name', ''))
    data = (struct.pack('<2I', len(radii), len(indices)) + positions.tobytes() + radii.tobytes() + indices.tobytes()
            + strand_values.tobytes() + coordinates.tobytes() + moved.tobytes())
    key = hashlib.blake2b(b'curves' + struct.pack('<3I', 1 if coordinates else 0, 1 if straight else 0, 1 if moved else 0) + data,
                          digest_size=8).digest()
    if len(BUILT) >= 16:
        BUILT.pop(next(iter(BUILT)))
    BUILT[signature] = (key, data, bool(coordinates), straight, bool(moved))
    return BUILT[signature]


CHANCES = {}


def chances(count):
    """chance() of strands 0 to count - 1, as doubles, kept for as many strands as there are."""
    held = CHANCES.get(count)
    if held is None:
        if len(CHANCES) >= 16:
            CHANCES.clear()
        held = CHANCES[count] = array('d', (chance(strand) for strand in range(count)))
    return held


def _doubles(values, width):
    """A list of points or UVs as one run of doubles: the run itself where they came as one (rows.Rows)."""
    from . import rows
    held = rows.numbers(values, width, 'd')
    return held if held is not None else array('d', itertools.chain.from_iterable(values))


def built_natively(entry, slot, closing, points=None):
    """segments() and what payload() packs of them, by the geometry adapter (curves.cpp): (positions, radii, segment
    firsts, strand values, coordinates, positions at the shutter's close, straight) as payload makes them; False where
    there are no segments; None where it cannot."""
    import ctypes
    from . import rows
    native = rows._native()
    if native is None or not hasattr(native, 'MR_curve_segments'):
        return None
    try:
        points = _doubles(entry['vertices'], 3) if points is None else points
        counts = array('i', entry['counts'])
        radii_in = array('d', entry.get('radii') or [entry.get('radius', .001)])
        late = _doubles(closing, 3) if closing is not None else None
    except (TypeError, ValueError, OverflowError):
        return None
    total = len(entry['vertices'])
    if len(points) != 3 * total or sum(counts) != total or (late is not None and len(late) != len(points)) or any(c < 0 for c in counts):
        return None
    kind = int(entry.get('curve_type', LINEAR))
    if kind == BSPLINE and not all(count >= 4 for count in counts if count >= 2):
        kind = LINEAR
    if kind == BEZIER and not all(count >= 4 and (count - 1) % 3 == 0 for count in counts if count >= 2):
        kind = LINEAR
    if kind not in (LINEAR, BEZIER, BSPLINE):
        return None
    if kind == BEZIER:
        room = sum(4 * ((c - 1) // 3) for c in counts if c >= 2)
        segment_room = sum((c - 1) // 3 for c in counts if c >= 2)
    else:
        room = sum(c for c in counts if c >= 2)
        segment_room = sum(c - (3 if kind == BSPLINE else 1) for c in counts if c >= 2)
    if not room or segment_room <= 0:
        return False
    uvs = entry.get('uvs') or []
    strand_uvs = None
    if uvs and slot is not None and len(uvs) == len(counts):
        strand_uvs = array('d', itertools.chain.from_iterable(uvs[strand] for strand in range(len(counts))))
    elif uvs and slot is not None and len(uvs) == total and rows.numbers(uvs, 2, 'd') is not None and all(counts):
        # The first UV of each strand, picked from the run by the adapter.
        from itertools import accumulate
        strand_uvs = rows.gather(rows.numbers(uvs, 2, 'd'), 16, array('I', accumulate(counts[:-1], initial=0)))
        if strand_uvs is None:
            return None
    elif uvs and slot is not None and len(uvs) == total:
        firsts_of, start = [], 0
        for count in counts:
            firsts_of.append(uvs[start] if count else [0.0, 0.0])
            start += count
        strand_uvs = array('d', itertools.chain.from_iterable(firsts_of))
    if strand_uvs is not None and len(strand_uvs) != 2 * len(counts):
        return None
    table = chances(len(counts))
    pointer = ctypes.c_void_p
    function = native.MR_curve_segments
    function.restype = ctypes.c_int
    function.argtypes = [pointer, pointer, ctypes.c_longlong, pointer, ctypes.c_longlong, ctypes.c_longlong, ctypes.c_int,
                         pointer, pointer, pointer, pointer, pointer, pointer, pointer, ctypes.c_longlong, ctypes.c_longlong, pointer]
    address = rows._address

    def run(where, uv_table):
        positions, widths = array('f', bytes(12 * room)), array('f', bytes(4 * room))
        values, coordinates = array('f', bytes(12 * room)), array('f', bytes(8 * room)) if uv_table is not None else array('f')
        firsts, made = array('I', bytes(4 * segment_room)), (ctypes.c_longlong * 2)()
        if function(address(where), address(counts), len(counts), address(radii_in), len(radii_in), total, kind,
                    address(table) if len(table) else None, address(uv_table) if uv_table is not None else None,
                    address(positions), address(widths), address(values), address(coordinates) if uv_table is not None else None,
                    address(firsts), room, segment_room, ctypes.addressof(made)):
            return None
        if made[0] != room or made[1] != segment_room:
            return None
        return positions, widths, firsts, values, coordinates
    first = run(points, strand_uvs)
    if first is None:
        return None
    positions, widths, firsts, values, coordinates = first
    moved = array('f')
    if late is not None:
        second = run(late, None)
        if second is None:
            return None
        moved = second[0]
    return positions, widths, firsts, values, coordinates, moved, kind == LINEAR
