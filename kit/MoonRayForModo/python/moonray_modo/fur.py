"""Modo's Fur material, grown as curves for MoonRay.

Modo grows fur itself, inside its own renderer, and hands nobody the fibres. So the plugin reads what the Fur material
says (how far apart the fibres are, how long, how wide, how they taper, bend and vary) and grows fibres of its own over
the polygons the material is on. It is fur of the same kind, not the same fibres: the count, the length, the width and
the lean are Modo's; where each fibre stands is not. Curls, clumps, kink, frizz and strays are grown after Modo's
settings for them, and the weight maps that vary density, length, clumping, curling and bending across the surface
are followed. Remove Base Surface is followed: the surface the fur grows from is then left out of the render. Guides,
the vector map and the width map are not read, and where they are used the plugin says so.
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
            'sclJitter': .5, 'nrmJitter': .25, 'maxSegment': 8, 'density': 1.0, 'rootBend': 0.0, 'bendDirection': 'down', 'seed': 1234,
            'curls': 0.0, 'curlMode': 'curls', 'curlRadius': 1.0, 'clumps': 0.0, 'clumpSize': .05, 'kinkAmp': 0.0, 'kinkAmpTip': 0.0, 'kinkScl': 1.0,
            'kinkOff': 0.0, 'frizAmp': 0.0, 'frizAmpTip': 0.0, 'strays': .01, 'straysAmp': 1.0}
# What Modo leaves to follow another where it is not set: the tip's kink and frizz are the root's.
FOLLOWS = {'kinkAmpTip': 'kinkAmp', 'frizAmpTip': 'frizAmp'}
# The weight maps that are followed: the Fur material's channel naming the map, and what it varies.
WEIGHTS = {'densityMap': 'density', 'lengthMap': 'length', 'clumpMap': 'clump', 'curlMap': 'curl', 'bendMap': 'bend'}
# What is not read: the channel, and what it is called. Each is said once where it is not at rest.
UNREAD = (('guides', 'none', 'guides'),)
MAPS = (('vectorMap', 'its vector map'), ('widthMap', 'its width map'))
GROWN = {}


def settings(read):
    """A Fur material's values, by the names above. read(channel) gives one channel's value, or raises."""
    held, follows = {}, []
    for key, default in CHANNELS.items():
        try:
            value = read(key)
        except Exception:
            value = default
        # Modo keeps -666 where a value is left to follow another.
        if isinstance(default, float):
            if key in FOLLOWS and (value is None or float(value) <= -600):
                follows.append(key)
            value = default if value is None or float(value) <= -600 else float(value)
        elif isinstance(default, int):
            value = int(value)
        held[key] = value
    for key in follows:
        held[key] = held[FOLLOWS[key]]
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
    for key, name in MAPS:
        try:
            if read(key):
                found.append(name)
        except Exception:
            pass
    return found


def _across(v):
    """Two directions square to a direction and to each other."""
    x, y, z = v
    a = (0.0, -z, y) if abs(x) < .6 else (-z, 0.0, x)
    size = math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2]) or 1.0
    a = (a[0] / size, a[1] / size, a[2] / size)
    return a, (y * a[2] - z * a[1], z * a[0] - x * a[2], x * a[1] - y * a[0])


def grow(triangles, held, maps=None):
    """The fibres of one mesh's fur: (strands, radius at the root, radius at the tip, how many Modo would grow, the
    triangle each strand stands on).
    triangles are [(a, b, c, na, nb, nc)]: three corners and the surface's normal at each, in the mesh's own space.
    maps are the weights that vary the fur over the surface, by what they vary ('density', 'length', 'clump', 'curl',
    'bend'): for each, the weight at the three corners of every triangle."""
    held = dict(CHANNELS, **held)
    maps = maps or {}
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
    # A fibre is as thick as the Fur material says, however many of Modo's are grown: fewer of them are thinner
    # fur, not wider fibres.
    root = held['widthAbs'] / 2 if held['widthMode'] == 'absolute' else apart * max(0.0, held['width']) / 2
    tip = root * max(.02, 1.0 - min(1.0, max(0.0, held['taper'])))
    curls, clumps = max(0.0, held['curls']), min(1.0, max(0.0, held['clumps']))
    kinked, frizzed = max(abs(held['kinkAmp']), abs(held['kinkAmpTip'])) > 0, max(abs(held['frizAmp']), abs(held['frizAmpTip'])) > 0
    steps = max(2, min(8, int(held['maxSegment'])))
    if curls > 0 or kinked or frizzed:
        # A fibre that winds or wanders needs more joints to do it with.
        steps = max(steps, 12)
    lean = {'down': (0.0, -1.0, 0.0), 'up': (0.0, 1.0, 0.0)}.get(held['bendDirection'], (0.0, -1.0, 0.0))
    chance = random.Random(int(held['seed']))
    # What the extras draw from is kept apart, so that fur with none of them stands as it always did.
    other = random.Random(int(held['seed']) * 7919 + 1).random
    uniform, strands, stands = chance.random, [], []

    def weight(what, picked, r, s, t):
        found = maps.get(what)
        if not found:
            return 1.0
        wa, wb, wc = found[picked]
        return min(1.0, max(0.0, wa * r + wb * s + wc * t))

    def fibre(x, y, z, dx, dy, dz, length, bend):
        """A fibre from its root, the way it sets out, its length and how far it gives way."""
        step = length / steps
        strand = [[x, y, z]]
        for j in range(1, steps + 1):
            # It bends more the further it gets from its root: stiff at the bottom, giving way toward the tip.
            pull = held['rootBend'] + held['flex'] * bend * j / steps
            bx, by, bz = dx + lean[0] * pull, dy + lean[1] * pull, dz + lean[2] * pull
            size = math.sqrt(bx * bx + by * by + bz * bz) or 1.0
            x, y, z = x + bx / size * step, y + by / size * step, z + bz / size * step
            strand.append([x, y, z])
        return strand

    def place(pick):
        picked = min(len(triangles) - 1, bisect.bisect_left(areas, pick() * total))
        a, b, c, na, nb, nc = triangles[picked]
        s, t = pick(), pick()
        if s + t > 1.0:
            s, t = 1.0 - s, 1.0 - t
        r = 1.0 - s - t
        return (picked, r, s, t, a[0] * r + b[0] * s + c[0] * t, a[1] * r + b[1] * s + c[1] * t, a[2] * r + b[2] * s + c[2] * t,
                na[0] * r + nb[0] * s + nc[0] * t, na[1] * r + nb[1] * s + nc[1] * t, na[2] * r + nb[2] * s + nc[2] * t)

    # Kink: a slow wandering that neighbouring fibres share. Which way a fibre wanders comes from where its root is,
    # so that those beside it go much the same way; it swings from one such way to another along its length.
    reach = max(1e-5, held['length'] * max(.05, held['kinkScl']) * 3)
    waves = [(other() * 2 - 1, other() * 2 - 1, other() * 2 - 1, other() * 6.2832) for _ in range(6)]
    swing = [(math.cos(3.1416 * j / steps), math.sin(3.1416 * j / steps),
              (held['kinkAmp'] + (held['kinkAmpTip'] - held['kinkAmp']) * j / steps) * .35 * j / steps) for j in range(steps + 1)]
    sine = math.sin

    def kink(strand, length):
        p = strand[0]
        u, v, w = p[0] / reach + held['kinkOff'], p[1] / reach + held['kinkOff'], p[2] / reach + held['kinkOff']
        ways = [sine(6.2832 * (u * kx + v * ky + w * kz) + phase) for kx, ky, kz, phase in waves]
        for j in range(1, steps + 1):
            c, s, much = swing[j]
            much *= length
            p = strand[j]
            p[0] += much * (ways[0] * c + ways[3] * s)
            p[1] += much * (ways[1] * c + ways[4] * s)
            p[2] += much * (ways[2] * c + ways[5] * s)

    # Curls: two and a quarter turns from root to tip, coming to their full width a little way up.
    wound = [(math.cos(14.137 * j / steps), math.sin(14.137 * j / steps), min(1.0, 2.5 * j / steps)) for j in range(steps + 1)]
    flat = held['curlMode'] != 'curls'
    # Clumps: tufts, each about a fibre of its own that those near it lean in to, more toward their tips.
    tufts, cells, size = [], {}, max(1e-4, held['clumpSize'])
    if clumps > 0 and total / (size * size) < count:
        for _ in range(min(count, max(1, int(total / (size * size))))):
            picked, r, s, t, x, y, z, dx, dy, dz = place(other)
            near = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
            length = held['length'] * (1.0 - held['sclJitter'] * .5) * weight('length', picked, r, s, t)
            middle = fibre(x, y, z, dx / near, dy / near, dz / near, length, weight('bend', picked, r, s, t))
            if kinked:
                kink(middle, length)
            cells.setdefault((int(x // size), int(y // size), int(z // size)), []).append(len(tufts))
            tufts.append(middle)

    for _ in range(count):
        picked, r, s, t, x, y, z, nx, ny, nz = place(uniform)
        # The way the fibre grows: out along the surface's normal, thrown off it a little.
        off = held['nrmJitter']
        dx, dy, dz = nx + off * (2 * uniform() - 1), ny + off * (2 * uniform() - 1), nz + off * (2 * uniform() - 1)
        length = held['length'] * (1.0 - held['sclJitter'] * uniform()) * (1.0 - held['growthJitter'] * uniform() * .5)
        if maps.get('density') and other() > weight('density', picked, r, s, t):
            continue
        length *= weight('length', picked, r, s, t)
        if length <= 0:
            continue
        # A stray goes its own way: off the normal by more, and into no tuft.
        stray = other() < held['strays']
        if stray:
            wild = .6 * held['straysAmp']
            dx, dy, dz = dx + wild * (2 * other() - 1), dy + wild * (2 * other() - 1), dz + wild * (2 * other() - 1)
        near = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
        dx, dy, dz = dx / near, dy / near, dz / near
        strand = fibre(x, y, z, dx, dy, dz, length, weight('bend', picked, r, s, t))
        if kinked:
            kink(strand, length)
        if tufts and not stray:
            cx, cy, cz = int(x // size), int(y // size), int(z // size)
            best, least = None, 1e30
            for i in (cx - 1, cx, cx + 1):
                for j in (cy - 1, cy, cy + 1):
                    for k in (cz - 1, cz, cz + 1):
                        for at in cells.get((i, j, k), ()):
                            q = tufts[at][0]
                            far = (q[0] - x) ** 2 + (q[1] - y) ** 2 + (q[2] - z) ** 2
                            if far < least:
                                best, least = at, far
            if best is not None:
                middle, much = tufts[best], clumps * weight('clump', picked, r, s, t)
                for j in range(1, steps + 1):
                    p, q, lean_in = strand[j], middle[j], much * j / steps
                    p[0] += (q[0] - p[0]) * lean_in
                    p[1] += (q[1] - p[1]) * lean_in
                    p[2] += (q[2] - p[2]) * lean_in
        if curls > 0:
            # A curl winds the fibre about the way it grows; a wave only sways it from side to side.
            wide = curls * weight('curl', picked, r, s, t) * max(0.0, held['curlRadius']) * length * .12
            e1, e2 = _across((dx, dy, dz))
            phase = other() * 6.2832
            cp, sp = math.cos(phase), math.sin(phase)
            for j in range(1, steps + 1):
                ct, st, out = wound[j]
                out *= wide
                # The turn so far, added to where this fibre's winding began.
                c, w = (0.0 if flat else cp * ct - sp * st - cp) * out, (sp * ct + cp * st - sp) * out
                p = strand[j]
                p[0] += e1[0] * c + e2[0] * w
                p[1] += e1[1] * c + e2[1] * w
                p[2] += e1[2] * c + e2[2] * w
        if frizzed:
            # Frizz is each fibre's own: every joint thrown a little, more toward the tip.
            for j in range(1, steps + 1):
                along = j / steps
                much = (held['frizAmp'] + (held['frizAmpTip'] - held['frizAmp']) * along) * length * .2 * along
                p = strand[j]
                p[0] += much * (2 * other() - 1)
                p[1] += much * (2 * other() - 1)
                p[2] += much * (2 * other() - 1)
        stands.append(picked)
        strands.append(strand)
    return strands, root, tip, wanted, stands


def kept(triangles, held, maps=None):
    """As grow, kept by what the fur grew from: the same lists come back while nothing about it has changed."""
    mark = hashlib.sha1()
    for a, b, c, na, nb, nc in triangles:
        mark.update(struct.pack('<18d', *a, *b, *c, *na, *nb, *nc))
    mark.update(repr(sorted(held.items())).encode())
    for what, weights in sorted((maps or {}).items()):
        mark.update(what.encode())
        for trio in weights:
            mark.update(struct.pack('<3d', *trio))
    key = mark.digest()
    if key not in GROWN:
        if len(GROWN) >= 6:
            GROWN.pop(next(iter(GROWN)))
        GROWN[key] = grow(triangles, held, maps)
    return GROWN[key]
