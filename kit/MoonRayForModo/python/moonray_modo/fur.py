"""Modo's Fur material, grown as curves for MoonRay.

Modo grows fur itself, inside its own renderer, and hands nobody the fibres. So the plugin reads what the Fur material
says (how far apart the fibres are, how long, how wide, how they taper, bend and vary) and grows fibres of its own over
the polygons the material is on. It is fur of the same kind, not the same fibres: the count, the length, the width and
the lean are Modo's; where each fibre stands is not. Curls, clumps, kinks, frizz, strays, guides and the maps that
vary any of these across the surface are not read, and the first time they are used the plugin says so.
"""
import bisect
import hashlib
import math
import random
import struct

# The most fibres grown for one mesh. Past this they are grown fewer and wider, to cover the surface as well.
MOST = 60000
# What the Fur material says, by its channel, with what Modo starts each at.
CHANNELS = {'dist': .005, 'length': .05, 'width': .5, 'widthMode': 'relative', 'widthAbs': .0025, 'taper': 1.0, 'flex': .5, 'growthJitter': .25,
            'sclJitter': .5, 'nrmJitter': .25, 'maxSegment': 8, 'density': 1.0, 'rootBend': 0.0, 'bendDirection': 'down', 'seed': 1234}
# What is not read: the channel, and what it is called. Each is said once where it is not at rest.
UNREAD = (('curls', 0.0, 'curls'), ('clumps', 0.0, 'clumps'), ('kinkAmp', 0.0, 'kink'), ('frizAmp', 0.0, 'frizz'), ('guides', 'none', 'guides'))
MAPS = ('densityMap', 'lengthMap', 'vectorMap', 'clumpMap', 'curlMap', 'bendMap', 'widthMap')
GROWN = {}


def settings(read):
    """A Fur material's values, by the names above. read(channel) gives one channel's value, or raises."""
    held = {}
    for key, default in CHANNELS.items():
        try:
            value = read(key)
        except Exception:
            value = default
        # Modo keeps -666 where a value is left to follow another.
        if isinstance(default, float):
            value = default if value is None or float(value) <= -600 else float(value)
        elif isinstance(default, int):
            value = int(value)
        held[key] = value
    return held


def unread(read):
    """What of a Fur material is set and not read, in words."""
    found = []
    for key, rest, name in UNREAD:
        try:
            if read(key) not in (rest, None):
                found.append(name)
        except Exception:
            pass
    try:
        if any(read(key) for key in MAPS):
            found.append('its maps')
    except Exception:
        pass
    return found


def grow(triangles, held):
    """The fibres of one mesh's fur: (strands, radius at the root, radius at the tip, how many Modo would grow, the
    triangle each strand stands on).
    triangles are [(a, b, c, na, nb, nc)]: three corners and the surface's normal at each, in the mesh's own space."""
    areas, total = [], 0.0
    for a, b, c, _, _, _ in triangles:
        u, v = (b[0] - a[0], b[1] - a[1], b[2] - a[2]), (c[0] - a[0], c[1] - a[1], c[2] - a[2])
        n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        total += .5 * math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2])
        areas.append(total)
    apart = max(1e-5, held['dist'])
    wanted = int(total / (apart * apart) * max(0.0, held['density']))
    count = min(wanted, MOST)
    if count <= 0 or total <= 0:
        return [], 0.0, 0.0, wanted, []
    # Fewer fibres than Modo's stand further apart, and are wider by as much.
    apart *= math.sqrt(wanted / count)
    root = held['widthAbs'] / 2 if held['widthMode'] == 'absolute' else apart * max(0.0, held['width']) / 2
    tip = root * max(.02, 1.0 - min(1.0, max(0.0, held['taper'])))
    steps = max(2, min(8, int(held['maxSegment'])))
    lean = {'down': (0.0, -1.0, 0.0), 'up': (0.0, 1.0, 0.0)}.get(held['bendDirection'], (0.0, -1.0, 0.0))
    chance = random.Random(int(held['seed']))
    uniform, strands, stands = chance.random, [], []
    for _ in range(count):
        picked = min(len(triangles) - 1, bisect.bisect_left(areas, uniform() * total))
        a, b, c, na, nb, nc = triangles[picked]
        stands.append(picked)
        s, t = uniform(), uniform()
        if s + t > 1.0:
            s, t = 1.0 - s, 1.0 - t
        r = 1.0 - s - t
        x, y, z = a[0] * r + b[0] * s + c[0] * t, a[1] * r + b[1] * s + c[1] * t, a[2] * r + b[2] * s + c[2] * t
        # The way the fibre grows: out along the surface's normal, thrown off it a little.
        off = held['nrmJitter']
        dx = na[0] * r + nb[0] * s + nc[0] * t + off * (2 * uniform() - 1)
        dy = na[1] * r + nb[1] * s + nc[1] * t + off * (2 * uniform() - 1)
        dz = na[2] * r + nb[2] * s + nc[2] * t + off * (2 * uniform() - 1)
        size = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
        dx, dy, dz = dx / size, dy / size, dz / size
        length = held['length'] * (1.0 - held['sclJitter'] * uniform()) * (1.0 - held['growthJitter'] * uniform() * .5)
        step = length / steps
        strand = [[x, y, z]]
        for j in range(1, steps + 1):
            # It bends more the further it gets from its root: stiff at the bottom, giving way toward the tip.
            pull = held['rootBend'] + held['flex'] * j / steps
            bx, by, bz = dx + lean[0] * pull, dy + lean[1] * pull, dz + lean[2] * pull
            size = math.sqrt(bx * bx + by * by + bz * bz) or 1.0
            x, y, z = x + bx / size * step, y + by / size * step, z + bz / size * step
            strand.append([x, y, z])
        strands.append(strand)
    return strands, root, tip, wanted, stands


def kept(triangles, held):
    """As grow, kept by what the fur grew from: the same lists come back while nothing about it has changed."""
    mark = hashlib.sha1()
    for a, b, c, na, nb, nc in triangles:
        mark.update(struct.pack('<18d', *a, *b, *c, *na, *nb, *nc))
    mark.update(repr(sorted(held.items())).encode())
    key = mark.digest()
    if key not in GROWN:
        if len(GROWN) >= 6:
            GROWN.pop(next(iter(GROWN)))
        GROWN[key] = grow(triangles, held)
    return GROWN[key]
