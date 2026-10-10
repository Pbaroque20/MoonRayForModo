"""Modo's physically based daylight, read from a table of Modo's own renders of it.

Modo does not publish its sky model, so the sky is not computed here: tools/probe_modo_sky_table.py
has Modo render its sky over a grid of sun heights and haze amounts, and tools/build_modo_sky.py
stores each as radiance by height above the horizon and angle from the sun. Those two angles keep
the horizon and the glow around the sun in the same place in every entry, so that a sky between
two entries is a blend of them rather than a double image. The physical sun's colour and strength
come from the same kind of measurement, of a white card lit by the sun alone.

What is held: the sky from 6 degrees below the horizon to overhead and haze 1 to 10, without the
solar disc (the sun light supplies the sun); the scale of Modo's brightness clamp for each entry;
the sun from the horizon to overhead, haze 1 to 8, thinned or not. Outside those ranges the
nearest entry is used.
"""
import bisect
import json
import math
import struct
from pathlib import Path

# The table's own axes: height above the horizon and angle from the sun, in degrees, both
# closer together where the sky changes fastest (at the horizon and around the sun).
ALTITUDES = [90.0 * (i / 15.0) ** 2 for i in range(16)]
ANGLES = [180.0 * (j / 23.0) ** 2 for j in range(24)]
CELL = len(ALTITUDES) * len(ANGLES) * 3
# How much of the sky's red, green and blue comes back off the ground and down again.
GROUND_BOUNCE = (.75, .46, .49)
HORIZON_BLEND = 0.5
_held = {}
_blends = {}


def table():
    if not _held:
        folder = Path(__file__).resolve().parent
        _held.update(json.loads((folder / 'modo_daylight.json').read_text()))
        data = (folder / 'modo_daylight.bin').read_bytes()
        _held['sky'] = struct.unpack('<%de' % (len(data) // 2), data)
    return _held


def between(axis, value):
    """The two entries of an axis a value lies between, and how far it is from the first to the second."""
    value = min(axis[-1], max(axis[0], value))
    upper = min(len(axis) - 1, max(1, bisect.bisect_left(axis, value)))
    span = axis[upper] - axis[upper - 1]
    return upper - 1, upper, (value - axis[upper - 1]) / span if span else 0.0


_disc = {}


def disc(elevation, haze, inscatter=0.0, normalize=False):
    """The radiance at the middle of Modo's solar disc, as its own renderer draws it: for a sun that many degrees
    up, a haze amount, and Disc In-Scatter from 0 to 1. Measured over a grid of all three (tools/probe_modo_disc.py,
    tools/build_modo_disc.py) and read between its entries, since what in-scatter does is not a straight line: with
    the sun high it adds light, and with the sun low in thick haze the disc at half of it is darker than at either
    end. The disc's size, the sky's gamma and the sun's thinning leave it alone. With Clamp Sky Brightness the disc
    is its colour with the strongest part made 1."""
    if not _disc:
        _disc.update(json.loads((Path(__file__).resolve().parent / 'modo_disc.json').read_text()))
    values = _disc['disc']
    e0, e1, et = between(_disc['elevations'], elevation)
    h0, h1, ht = between(_disc['hazes'], haze)
    a0, a1, at = between(_disc['amounts'], inscatter)
    found = [0.0, 0.0, 0.0]
    for e, ew in ((e0, 1 - et), (e1, et)):
        for h, hw in ((h0, 1 - ht), (h1, ht)):
            for a, aw in ((a0, 1 - at), (a1, at)):
                for c in range(3):
                    found[c] += values[e][h][a][c] * ew * hw * aw
    if normalize:
        strongest = max(found)
        found = [v / strongest for v in found] if strongest > 0 else found
    return found


def sky(elevation, haze):
    """The sky for a sun height in degrees and a haze amount: (radiance by height and angle, clamp scale)."""
    key = (round(elevation, 3), round(haze, 3))
    if key not in _blends:
        held = table()
        e0, e1, e = between(held['elevations'], elevation)
        h0, h1, h = between(held['hazes'], haze)
        count = len(held['elevations'])
        blend = [0.0] * CELL
        scale = 0.0
        for row, column, weight in ((h0, e0, (1 - h) * (1 - e)), (h0, e1, (1 - h) * e), (h1, e0, h * (1 - e)), (h1, e1, h * e)):
            if weight <= 0:
                continue
            start = (row * count + column) * CELL
            part = held['sky'][start:start + CELL]
            blend = [a + weight * b for a, b in zip(blend, part)]
            scale += weight * held['clamp'][row * count + column]
        if len(_blends) > 32:
            _blends.clear()
        _blends[key] = (blend, scale)
    return _blends[key]


def color(direction, environment):
    """The sky in a direction, as Modo's environment gives it: the ground's colour below the horizon,
    and above it the sky, divided by Modo's own scale and shaped by its gamma where the brightness is clamped."""
    if direction[1] < 0:
        # Below the horizon Modo shows the ground's colour, reached from the horizon's over half a radian.
        ground = list(environment.get('ground_albedo', [.5] * 3))
        below = math.asin(min(1.0, -direction[1]))
        flat = math.hypot(direction[0], direction[2])
        if below >= HORIZON_BLEND or flat <= 0:
            return ground
        horizon = color([direction[0] / flat, 0.0, direction[2] / flat], environment)
        return [g + (h - g) * (1 - below / HORIZON_BLEND) for g, h in zip(ground, horizon)]
    sun = environment['sun_direction']
    length = math.sqrt(sum(v * v for v in sun))
    if length <= 0:
        raise ValueError('Invalid sun direction')
    sun = [v / length for v in sun]
    values, scale = sky(math.degrees(math.asin(max(-1.0, min(1.0, sun[1])))), float(environment.get('haze', 2.0)))
    altitude = math.degrees(math.asin(max(0.0, min(1.0, direction[1]))))
    apart = math.degrees(math.acos(max(-1.0, min(1.0, sum(a * b for a, b in zip(direction, sun))))))
    # Both axes are spaced by the square, so the place along each is a square root.
    i = (len(ALTITUDES) - 1) * math.sqrt(altitude / 90.0)
    j = (len(ANGLES) - 1) * math.sqrt(apart / 180.0)
    i0, j0 = min(len(ALTITUDES) - 2, int(i)), min(len(ANGLES) - 2, int(j))
    fi, fj = i - i0, j - j0
    width = len(ANGLES) * 3
    a, b = i0 * width + j0 * 3, (i0 + 1) * width + j0 * 3
    result = [(values[a + c] * (1 - fj) + values[a + 3 + c] * fj) * (1 - fi) + (values[b + c] * (1 - fj) + values[b + 3 + c] * fj) * fi
              for c in range(3)]
    albedo = environment.get('ground_albedo')
    if albedo and any(abs(v - .5) > 1e-6 for v in albedo):
        # The table is of a mid-grey ground. Light off the ground brightens the sky above it; this
        # follows Modo's own skies over other grounds overhead, and less closely around the sun.
        result = [v * (1 - .5 * s) / max(.05, 1 - min(1.0, max(0.0, a)) * s) for v, a, s in zip(result, albedo, GROUND_BOUNCE)]
    if environment.get('normalize') and scale > 0:
        gamma = max(.01, float(environment.get('sky_gamma', 1.0)))
        result = [max(0.0, v / scale) ** (1.0 / gamma) for v in result]
    return result


def sun_measure(elevation, haze, thinning):
    """What Modo's physical sun sheds on a surface facing it, before its clamp and gamma."""
    held = table()
    rows = sorted((row for row in held['sun'] if row['thinning'] == bool(thinning)), key=lambda row: row['haze'])
    found = []
    for row in rows:
        heights = row['elevations']
        if elevation <= heights[0]:
            # Below the lowest measurement the sun fades out to the horizon.
            found.append([v * max(0.0, elevation) / heights[0] for v in row['values'][0]])
            continue
        low, high, t = between(heights, elevation)
        found.append([a + (b - a) * t for a, b in zip(row['values'][low], row['values'][high])])
    hazes = [row['haze'] for row in rows]
    upper = min(len(hazes) - 1, max(1, bisect.bisect_left(hazes, haze)))
    t = (haze - hazes[upper - 1]) / (hazes[upper] - hazes[upper - 1])
    # Haze thins the sun by a power, so the blend, and the reach beyond the table, are of logarithms.
    result = []
    for a, b in zip(found[upper - 1], found[upper]):
        result.append(math.exp(math.log(a) + (math.log(b) - math.log(a)) * t) if a > 1e-9 and b > 1e-9 else max(0.0, a + (b - a) * min(1.0, max(0.0, t))))
    return result


def sun_light(elevation, haze, thinning=True, gamma=2.2, clamp='clamp', radiance=3.0):
    """The colour and strength of Modo's physical sun: (colour, intensity).

    Modo takes the sun's colour from its height and the haze, brightest channel 1, and softens it
    by the sun's gamma. Its clamp setting then says how strong: 'clamp' makes it 1, 'replace' the
    light's own radiance, and 'none' leaves the physical strength.
    """
    measured = sun_measure(elevation, haze, thinning)
    peak = max(measured)
    if peak <= 0:
        return [0.0, 0.0, 0.0], 0.0
    tint = [max(0.0, v / peak) ** (1.0 / max(.01, gamma)) for v in measured]
    return tint, {'clamp': 1.0, 'replace': float(radiance)}.get(clamp, peak)
