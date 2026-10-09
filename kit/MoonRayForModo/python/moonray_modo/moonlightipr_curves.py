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


def segments(entry):
    """(control points, a radius for each, the first control point of every segment, a strand for every control point,
    whether the segments are straight)."""
    points, counts = entry['vertices'], entry['counts']
    radii = entry.get('radii') or [entry.get('radius', .001)]
    per_point = len(radii) == len(points)
    per_strand = len(radii) == len(counts) and not per_point
    kind = int(entry.get('curve_type', LINEAR))
    # One geometry holds one kind of segment; strands too short for a cubic make all of it straight.
    if kind == BSPLINE and not all(count >= 4 for count in counts if count >= 2):
        kind = LINEAR
    if kind == BEZIER and not all(count >= 4 and (count - 1) % 3 == 0 for count in counts if count >= 2):
        kind = LINEAR
    controls, widths, firsts, strands = [], [], [], []
    start = 0
    for strand, count in enumerate(counts):
        here = points[start:start + count]
        wide = radii[start:start + count] if per_point else [radii[strand] if per_strand else radii[0]] * count
        start += count
        if count < 2:
            continue

        def add(four, four_wide):
            firsts.append(len(controls))
            controls.extend(four)
            widths.extend(max(0.0, w) for w in four_wide)
            strands.extend([strand] * 4)
        if kind == BSPLINE:
            # The strand's own control points, shared between the segments that follow one another.
            first = len(controls)
            controls.extend(here)
            widths.extend(max(0.0, w) for w in wide)
            strands.extend([strand] * count)
            firsts.extend(range(first, first + count - 3))
        elif kind == BEZIER:
            for i in range(0, count - 1, 3):
                b, w = here[i:i + 4], wide[i:i + 4]
                # The B-spline control points of the cubic these four Bezier points make.
                mix = ((6, -7, 2, 0), (0, 2, -1, 0), (0, -1, 2, 0), (0, 2, -7, 6))
                add([[sum(m * p[axis] for m, p in zip(row, b)) for axis in range(3)] for row in mix],
                    [sum(m * v for m, v in zip(row, w)) for row in mix])
        else:
            first = len(controls)
            controls.extend(here)
            widths.extend(max(0.0, w) for w in wide)
            strands.extend([strand] * count)
            firsts.extend(range(first, first + count - 1))
    return controls, widths, firsts, strands, kind == LINEAR


def payload(entry, slot):
    """One curve geometry for the session: (key, payload, has coordinates, straight). slot is the scene-wide coordinate slot
    its strands' coordinates serve, or None; a strand has one coordinate, or one for each of its points."""
    held = hashlib.sha1()
    for part in (array('d', itertools.chain.from_iterable(entry['vertices'])), array('q', entry['counts']),
                 array('d', entry.get('radii') or [entry.get('radius', .001)]), array('d', itertools.chain.from_iterable(entry.get('uvs') or [])),
                 array('q', [int(entry.get('curve_type', LINEAR)), -1 if slot is None else slot])):
        held.update(part.tobytes())
        held.update(b'|')
    signature = held.digest()
    if signature in BUILT:
        return BUILT[signature]
    controls, widths, firsts, strands, straight = segments(entry)
    if not firsts:
        return None
    positions, radii, indices = array('f', itertools.chain.from_iterable(controls)), array('f', widths), array('I', firsts)
    if not math.isfinite(sum(positions)) or not math.isfinite(sum(radii)):
        raise ValueError('Curves %s contain a non-finite number' % entry.get('name', ''))
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
    if coordinates and not math.isfinite(sum(coordinates)):
        raise ValueError('Curves %s have invalid texture coordinates' % entry.get('name', ''))
    data = struct.pack('<2I', len(radii), len(indices)) + positions.tobytes() + radii.tobytes() + indices.tobytes() + coordinates.tobytes()
    key = hashlib.blake2b(b'curves' + struct.pack('<2I', 1 if coordinates else 0, 1 if straight else 0) + data, digest_size=8).digest()
    if len(BUILT) >= 16:
        BUILT.pop(next(iter(BUILT)))
    BUILT[signature] = (key, data, bool(coordinates), straight)
    return BUILT[signature]
