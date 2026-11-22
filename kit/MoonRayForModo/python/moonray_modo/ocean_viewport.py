"""An Ocean Plane's waves in Modo's viewport: points where the sea's surface stands, so that the sea's look (how big its
waves are, how they run with the wind, the swell) shows before it is rendered, and moves with the timeline. Before, the
plane was a flat grid of lines.

The points are the renders' own sea (ocean_plane.material, nodes.expand_ocean): its tiles (ocean.swell_values,
ocean.cascade_values), each laid on the plane as the renders lay it. Only its long waves: modo_ocean.dll's
modo_ocean_preview sums each tile's waves of fewer than PREVIEW / 2 cycles across it, in memory, with the full tile's own
random numbers, so the points stand where the render's long waves put the surface (the same to a float for all but the
finest of the four tiles, whose ripples, under a metre, are left out). Nothing is written to disk, and a frame of the
timeline costs a few milliseconds.

The geometry adapter keeps the tiles (MR_ocean_preview_load, native-modo/ocean_viewport.cpp) and draws the points on the
viewport's stroke object (MR_ocean_preview_draw): around the eye of the viewport being drawn, in levels each twice as
sparse as the one inside it, on the world's grid so that they stay put as the view moves, none past Point Distance and
at most MOST_POINTS of them, so that a sea reaching the horizon costs the same as a pond. They are coloured by their
height, deep blue in the troughs to light blue on the crests; the grid keeps the item's colour, which shows it
selected. A plane whose material tag names a Modo material, whose sea that material's
Ocean node makes, is drawn as its grid alone.
"""
import ctypes
import json

from . import ocean

# Points across each tile's long waves: waves of up to 32 cycles across it, about a metre long on the finest tile.
PREVIEW = 64
# The most points a plane draws, whatever its distance and spacing.
MOST_POINTS = 40000

_loaded = {}    # a plane's identity -> what the sea the adapter keeps for it was made from
# Each plane's last drawing, for probes: how many points, around which eye (x, y, z) in which kind of view (ILxView's
# Type: 3 perspective, 4 camera, 2 front, top or side), at what moment, in how many ms.
LAST = {}
# And every drawing's eye and kind of view, the latest few, as each viewport draws its own.
import collections
DRAWS = collections.deque(maxlen=256)


def _library():
    """modo_ocean.dll with modo_ocean_preview, or None (an older one, or none)."""
    held = ocean.library()
    if held is None or not hasattr(held, 'modo_ocean_preview'):
        return None
    held.modo_ocean_preview.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_double), ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_float)]
    held.modo_ocean_preview.restype = ctypes.c_int
    return held


def _adapter():
    """The geometry adapter with the ocean's points, or None (an adapter older than the kit draws none)."""
    try:
        from .evaluated import _adapter as loaded
        bridge = loaded()
    except Exception:
        return None
    if bridge is None or not hasattr(bridge, 'MR_ocean_preview_draw'):
        return None
    bridge.MR_ocean_preview_load.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
                                             ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_float)]
    bridge.MR_ocean_preview_load.restype = ctypes.c_int
    bridge.MR_ocean_preview_forget.argtypes = [ctypes.c_char_p]
    bridge.MR_ocean_preview_forget.restype = None
    bridge.MR_ocean_preview_points.argtypes = [ctypes.c_char_p] + [ctypes.c_double] * 7 + [ctypes.c_int, ctypes.POINTER(ctypes.c_float)]
    bridge.MR_ocean_preview_points.restype = ctypes.c_int
    bridge.MR_ocean_preview_draw.argtypes = ([ctypes.c_void_p, ctypes.c_char_p] + [ctypes.c_double] * 5 + [ctypes.c_int]
                                             + [ctypes.c_double] * 3 + [ctypes.POINTER(ctypes.c_double)])
    bridge.MR_ocean_preview_draw.restype = ctypes.c_int
    return bridge


def tiles(params, time):
    """The sea's tiles of long waves for an Ocean node's settings (params) at the scene's time (seconds), as the
    renders lay them: (width, height, tiles of it to one of the sea's, turn in degrees, width x height x 3 floats) each,
    the swell's one row high; None where modo_ocean.dll cannot make them."""
    held = _library()
    if held is None:
        return None
    value = ocean.settings(params)
    made = []
    for part in ocean.swell_values(value) + ocean.cascade_values(value):
        ratio, turn = ocean.FITTED_SIZE / float(part['size']), float(part.get('turn', 0.0))
        if part.get('swell'):
            # One wave along the tile's U: every row the same (ocean.swell_fields).
            width = int(part['resolution'])
            row = ocean.swell_fields(part, time)[0][:width]
            made.append((width, 1, ratio, turn, (ctypes.c_float * (3 * width))(*(c for v in row for c in v))))
            continue
        size = min(PREVIEW, int(part['resolution']))
        numbers = ocean.values(part, time)
        out = (ctypes.c_float * (size * size * 3))()
        if held.modo_ocean_preview(int(part['resolution']), (ctypes.c_double * len(numbers))(*numbers), len(numbers), size, out) != 0:
            return None
        made.append((size, size, ratio, turn, out))
    return made


def load(name, made):
    """The tiles (tiles) kept by the adapter under name; whether they were."""
    bridge = _adapter()
    if bridge is None or made is None:
        return False
    count = len(made)
    total = sum(width * height * 3 for width, height, _, _, _ in made)
    values = (ctypes.c_float * max(total, 1))()
    at = 0
    for width, height, _, _, floats in made:
        size = width * height * 3
        ctypes.memmove(ctypes.addressof(values) + at * 4, floats, size * 4)
        at += size
    return bool(bridge.MR_ocean_preview_load(name.encode('utf-8'), count, (ctypes.c_int * count)(*(m[0] for m in made)),
                                             (ctypes.c_int * count)(*(m[1] for m in made)), (ctypes.c_double * count)(*(m[2] for m in made)),
                                             (ctypes.c_double * count)(*(m[3] for m in made)), values))


def ready(name, params, time):
    """The sea for these settings at this moment kept under name, made where what is kept was made from others; whether
    it is there to draw."""
    key = json.dumps([params, round(float(time), 6)], sort_keys=True, default=str)
    if _loaded.get(name) == key:
        return True
    if not load(name, tiles(params, time)):
        return False
    _loaded[name] = key
    return True


def forget(name):
    """Lets go of the sea kept under name."""
    _loaded.pop(name, None)
    bridge = _adapter()
    if bridge is not None:
        bridge.MR_ocean_preview_forget(name.encode('utf-8'))


def points(name, centre, height, tile, spacing, distance, most=MOST_POINTS):
    """The points of the sea kept under name around centre (x, z), as drawn: [(x, y, z, height above the plane)], or
    None where none is kept. For tests and probes."""
    bridge = _adapter()
    if bridge is None:
        return None
    out = (ctypes.c_float * (4 * max(int(most), 1)))()
    count = bridge.MR_ocean_preview_points(name.encode('utf-8'), float(centre[0]), float(centre[1]), float(height), float(tile),
                                           float(tile) / ocean.FITTED_SIZE, float(spacing), float(distance), int(most), out)
    if count < 0:
        return None
    return [tuple(out[4 * i:4 * i + 4]) for i in range(count)]


def draw(stroke, name, params, time, height, tile, spacing, distance, colour):
    """Draws an Ocean Plane's waves (its Ocean settings params, at time) on a viewport's stroke object (lx.object.StrokeDraw,
    in world space): the plane at height, its tiles Tile Size wide, points Point Spacing apart next to the eye, out to
    Point Distance. How many points were drawn; None where none could be."""
    bridge = _adapter()
    if bridge is None or not ready(name, params, time):
        return None
    import time as clock
    began = clock.perf_counter()
    red, green, blue = (float(c) for c in tuple(colour)[:3])
    eye = (ctypes.c_double * 9)()
    count = bridge.MR_ocean_preview_draw(ctypes.c_void_p(stroke.__peekobj__()), name.encode('utf-8'), float(height), float(tile),
                                         float(tile) / ocean.FITTED_SIZE, float(spacing), float(distance), MOST_POINTS, red, green, blue, eye)
    LAST[name] = {'count': count, 'eye': (eye[0], eye[1], eye[2]), 'view': int(eye[3]), 'centre': (eye[4], eye[5], eye[6]),
                  'distances': (eye[7], eye[8]), 'time': float(time), 'height': float(height),
                  'ms': round((clock.perf_counter() - began) * 1e3, 2)}
    DRAWS.append((name, tuple(round(v, 2) for v in eye[:3]), int(eye[3])))
    return count if count >= 0 else None
