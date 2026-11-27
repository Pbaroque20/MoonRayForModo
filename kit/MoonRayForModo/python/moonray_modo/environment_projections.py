"""Modo's Texture Locator projections for an environment's images and procedurals, as Modo's own renderer lays them
(Preferences > MoonRay > Source Overrides > Environment images in every projection, native.environment_projections).

An environment has no surface: Modo looks an environment layer up by the direction of the ray alone. Each projection
below was read from Modo's own renders (tools/probe_cl_environment_projections.py: a spherical camera at the origin
seeing an image whose colour is its own coordinates, under each projection, axis and placement; the arithmetic here
gives Modo's coordinate to within its filtering, tools/check_environment_projections.py). d is the ray's direction in
the world, R the locator's turn (its rows made unit length) and s its size (the rows' lengths); q = d R^-1 is the
direction in the locator's frame. (a, b, h) are q's components taken by the axis: X (z, y, x), Y (x, z, y), Z (x, y, z).

- Planar: q / s; u = 0.5 + a, v = 0.5 + b. Horizontal and Vertical Wrap do nothing.
- Cylindrical: u = 0.5 + atan2(a, b) / 2pi of q / s^2, v = 0.5 + h of q / s; u times Horizontal Wrap, v times
  Vertical Wrap about its middle.
- Spherical: q / s^2; u = 0.5 + atan2(a, b) / 2pi, v = 0.5 + asin(h / |.|) / pi; times the Wraps. (Axis Y is the plain
  latitude-longitude image the plugin has always handed MoonRay whole; with this override an X or Z axis, or a locator
  sized unevenly, is laid here.)
- Cubic (and Solid, which lays an image as Cubic does): the face of q's largest component; q / s on it, as a cube's
  faces seen from inside. The axis does nothing.
- Box: the face of d's largest component, in the world (the locator's turn does nothing), divided by its X and Y sizes.
- Light Probe: an angular map (Debevec's), looking along -b, turned by the locator's matrix read by its columns, made
  unit length and square in turn (probe_turn: the transpose of its turn where it is turned or sized alone); the Wraps
  and UV Rotation do nothing.
- Triplanar: three planar images, X (z, y), Y (x, z), Z (x, y), of q / s, weighted by max(|q_i| - 0.5, 0) to the power
  1 + 25 x Blending Hardness.
- UV Map, Implicit UV and Front Projection: no surface, so no coordinates: one colour, the image at (0, 0).
UV Rotation turns every one but Light Probe about the image's middle; Horizontal and Vertical Repeat (repeat, mirror,
edge, reset) apply as in Modo, reset leaving nothing (the layers under it) outside the image. The locator's position
does nothing; its UV matrix (m00..m12) does nothing either.

Procedurals (Grid, Dots) are evaluated at the same coordinates, by Modo's own lines and dots there (procedurals.
environment_sample: a Grid's square lines half way across each unit, a Dots' dots on the whole numbers), the repeat
modes doing nothing; UV Map at the direction's world x and z, Implicit UV and Front Projection at (0, 0)
(procedural_coordinates). Solid has no coordinates for them, and is refused. A procedural on the plain spherical
projection along Y is evaluated by these too (plain). Triplanar lays a procedural otherwise than an image (procedural_
triplanar): each plane's two coordinates turned by the UV Rotation, then the X plane keeps only its second (the first
0), the Y plane only its first (the second 0; a Grid of Lines takes it as its second), the Z plane both; weighted as an
image's planes."""
import math

# The projections an environment layer can be laid by, as the native blend numbers them (0 the plain spherical image).
KINDS = {'planar': 1, 'cylindrical': 2, 'spherical': 3, 'cubic': 4, 'box': 5, 'lightprobe': 6, 'triplanar': 7, 'constant': 8}
TILES = {'repeat': 0, 'reset': 1, 'mirror': 2, 'edge': 3}
# The locator's projType values (Modo's txtrLocator-projType), and what each is laid as here.
MODO = {'planar': 'planar', 'cylindrical': 'cylindrical', 'spherical': 'spherical', 'cubic': 'cubic', 'box': 'box',
        'lightprobe': 'lightprobe', 'triplanar': 'triplanar', 'front': 'constant', 'uv': 'constant', 'implicitUV': 'constant',
        'none': 'cubic'}
# Axis -> the components (a, b, h) of the direction in the locator's frame.
PERMUTATION = {0: (2, 1, 0), 1: (0, 2, 1), 2: (0, 1, 2)}
SIZE = 22
# Changed whenever the arithmetic below (or its native copy) changes: composed environments are cached by it.
VERSION = 'environment-projections-v3'


def axis_number(value):
    text = str(value).strip().lower()
    if text in ('x', 'y', 'z'):
        return 'xyz'.index(text)
    return int(float(text)) if text not in ('', 'none') else 1


def wanted(locator_projection, axis, matrix=None):
    """Whether an environment layer laid by this projection (Modo's projType) needs this module: anything but a spherical
    one along Y, which the plugin lays as a latitude-longitude image as it always has, unless its locator is sized
    unevenly (Modo divides the direction by the size twice there; the plain image is turned whole)."""
    if locator_projection != 'spherical' or axis_number(axis) != 1:
        return True
    if matrix is None:
        return False
    size = [math.sqrt(sum(float(matrix[r * 4 + c]) ** 2 for c in range(3))) for r in range(3)]
    return max(size) - min(size) > 1e-6 * max(size)


def capture(locator, channel, matrix, procedural=False):
    """The locator's projection as this module lays it (a dict kept in the scene's environment layer), from its channels
    and its world matrix (row-major 4x4, rows its axes). ValueError where it cannot be laid."""
    modo = channel(locator, 'projType', 'uv')
    if modo not in MODO:
        raise ValueError('unknown environment projection ' + str(modo))
    if procedural and modo == 'none':
        raise ValueError('a Solid environment procedural has no coordinates to lay it by')
    rows = [[float(matrix[r * 4 + c]) for c in range(3)] for r in range(3)]
    size = [math.sqrt(sum(v * v for v in row)) for row in rows]
    if min(size) <= 1e-12:
        raise ValueError('the Texture Locator has no size')
    turn = [v / size[r] for r, row in enumerate(rows) for v in row]
    tiles = [str(channel(locator, key, 'repeat')) for key in ('tileU', 'tileV')]
    return {'projection': MODO[modo], 'modo_projection': modo, 'axis': axis_number(channel(locator, 'projAxis', 1)),
            'turn': turn, 'size': size,
            'wrap': [float(channel(locator, 'wrapU', 1)), float(channel(locator, 'wrapV', 1))],
            'uv_rotation': float(channel(locator, 'uvRotation', 0)),
            'tiles': [t if t in TILES else 'repeat' for t in tiles],
            'hardness': float(channel(locator, 'triplanarBlending', 0) or 0)}


def plain(layer):
    """The plain spherical projection along Y of a procedural laid without one (environments: an even locator), from
    its placement (matrix), Wraps (scale) and UV Rotation (rotation), for procedural: Modo evaluates it as any other
    projection's. None where its placement has no size."""
    channels = {'projType': 'spherical', 'projAxis': 1, 'wrapU': (layer.get('scale') or [1, 1])[0],
                'wrapV': (layer.get('scale') or [1, 1])[1], 'uvRotation': layer.get('rotation', 0)}
    try:
        return capture(None, lambda item, key, default=None: channels.get(key, default),
                       layer.get('matrix') or [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1], True)
    except ValueError:
        return None


def numbers(projection):
    """The SIZE numbers the native blend (MR_environment_projected) takes for a layer: kind, axis, turn (9), size (3),
    wraps (2), cos and sin of the UV rotation, the two repeat modes, the blending hardness; all zero for a plain image."""
    if not projection:
        return [0.0] * SIZE
    rotation = float(projection.get('uv_rotation', 0))
    axis = float(projection.get('axis', 1))
    if projection['projection'] == 'constant':
        # One colour for an image; a procedural laid by UV Map is evaluated at the direction's world x and z
        # (procedural_coordinates), told apart by its axis 3.
        axis = 3.0 if projection.get('modo_projection') == 'uv' else 0.0
    return ([float(KINDS[projection['projection']]), axis] + [float(v) for v in projection['turn']]
            + [float(v) for v in projection['size']] + [float(v) for v in projection.get('wrap', [1, 1])]
            + [math.cos(rotation), math.sin(rotation)] + [float(TILES[t]) for t in projection.get('tiles', ['repeat'] * 2)]
            + [float(projection.get('hardness', 0))])


def _turned_about_middle(u, v, cosine, sine):
    u, v = u - .5, v - .5
    return u * cosine - v * sine + .5, u * sine + v * cosine + .5


def probe_turn(t, s):
    """The turn Modo lays a Light Probe by: the locator's matrix (rows its axes, each its size long) read by its columns,
    x, y then z, made unit length and square to those before (Gram-Schmidt); rows of the result. It is the locator's
    own turn the other way (its transpose) where the locator is turned or sized alone; turned and sized unevenly both,
    Modo's is this one (read from its renders, tools/probe_cl_environment_projections.py lightprobe_rotsize: a turn
    taken from the rows was 0.07 to 0.13 of the image off)."""
    found = []
    for c in range(3):
        v = [t[r * 3 + c] * s[r] for r in range(3)]
        for u in found:
            dot = sum(a * b for a, b in zip(v, u))
            v = [a - dot * b for a, b in zip(v, u)]
        length = math.sqrt(sum(a * a for a in v)) or 1e-12
        found.append([a / length for a in v])
    return found


def coordinates(projection, d):
    """Where Modo looks the layer up for the world direction d: a list of (u, v, weight), weights adding to one (three
    for Triplanar, one for the rest)."""
    kind = projection['projection']
    if kind == 'constant':
        return [(0.0, 0.0, 1.0)]
    t = projection['turn']
    s = projection['size']
    q = [d[0] * t[i * 3] + d[1] * t[i * 3 + 1] + d[2] * t[i * 3 + 2] for i in range(3)]
    rotation = float(projection.get('uv_rotation', 0))
    cosine, sine = math.cos(rotation), math.sin(rotation)
    order = PERMUTATION[int(projection.get('axis', 1))]
    if kind == 'lightprobe':
        f = probe_turn(t, s)
        p = [sum(f[i][j] * d[j] for j in range(3)) for i in range(3)]
        a, b, h = (p[i] for i in order)
        length = math.sqrt(a * a + b * b + h * h) or 1e-12
        across = math.hypot(a, h)
        if across < 1e-12:
            return [(.5, .5, 1.0)]
        r = math.acos(max(-1.0, min(1.0, -b / length))) / math.pi
        return [(.5 - .5 * a / across * r, .5 + .5 * h / across * r, 1.0)]
    if kind == 'box':
        x, y, z = d
        face = max(range(3), key=lambda i: abs(d[i]))
        sign = 1 if d[face] >= 0 else -1
        u, v = [(-sign * y, z), (sign * x, z), (x, -sign * y)][face]
        return [_turned_about_middle(.5 + u / s[0], .5 + v / s[1], cosine, sine) + (1.0,)]
    p = [q[i] / s[i] for i in range(3)]
    if kind == 'planar':
        a, b, _ = (p[i] for i in order)
        return [_turned_about_middle(.5 + a, .5 + b, cosine, sine) + (1.0,)]
    if kind in ('cylindrical', 'spherical'):
        p2 = [q[i] / (s[i] * s[i]) for i in range(3)]
        a, b, h = (p2[i] for i in order)
        u = .5 + math.atan2(a, b) / (2 * math.pi)
        if kind == 'cylindrical':
            v = .5 + p[order[2]]
        else:
            length = math.sqrt(a * a + b * b + h * h) or 1e-12
            v = .5 + math.asin(max(-1.0, min(1.0, h / length))) / math.pi
        wrap = projection.get('wrap', [1, 1])
        # A cylinder's height is wrapped about its middle, a sphere's latitude from its foot (alike but for the turn).
        v = (v - .5) * wrap[1] + .5 if kind == 'cylindrical' else v * wrap[1]
        return [_turned_about_middle(u * wrap[0], v, cosine, sine) + (1.0,)]
    if kind == 'cubic':
        face = max(range(3), key=lambda i: abs(q[i]))
        sign = 1 if q[face] >= 0 else -1
        x, y, z = p
        u, v = [(sign * z, y), (x, sign * z), (-sign * x, y)][face]
        return [_turned_about_middle(.5 + u, .5 + v, cosine, sine) + (1.0,)]
    if kind == 'triplanar':
        power = 1 + 25 * max(0.0, float(projection.get('hardness', 0)))
        weights = [max(abs(v) - .5, 0.0) ** power for v in q]
        total = sum(weights)
        if total <= 0:
            weights, total = [1.0 if i == max(range(3), key=lambda k: abs(q[k])) else 0.0 for i in range(3)], 1.0
        x, y, z = p
        found = []
        for (u, v), w in zip(((z, y), (x, z), (x, y)), weights):
            if w > 0:
                found.append(_turned_about_middle(.5 + u, .5 + v, cosine, sine) + (w / total,))
        return found
    raise ValueError('unknown environment projection ' + str(kind))


def tiled(value, mode):
    """A coordinate under a repeat mode, 0 to 1; None outside the image where it is reset."""
    if mode == 'reset':
        return value if 0.0 <= value <= 1.0 else None
    if mode == 'edge':
        return min(1.0, max(0.0, value))
    if mode == 'mirror':
        value = value % 2.0
        return 2.0 - value if value > 1.0 else value
    return value % 1.0


def texel(index, count, mode):
    """A pixel's column or row under a repeat mode (bilinear taps past the edge)."""
    if mode == 'repeat':
        return index % count
    if mode == 'mirror':
        index = index % (2 * count)
        return 2 * count - 1 - index if index >= count else index
    return min(count - 1, max(0, index))


def sample(projection, pixels, alpha, width, height, d):
    """The layer's colour and coverage in direction d, its image (pixels: width x height x 3 floats, rows bottom up;
    alpha: width x height or None) looked up bilinearly at Modo's coordinates."""
    colour, coverage = [0.0, 0.0, 0.0], 0.0
    tiles = projection.get('tiles', ['repeat', 'repeat'])
    for u, v, weight in coordinates(projection, d):
        u, v = tiled(u, tiles[0]), tiled(v, tiles[1])
        if u is None or v is None:
            continue
        x, y = u * width - .5, v * height - .5
        ix, iy = math.floor(x), math.floor(y)
        ax, ay = x - ix, y - iy
        found, covered = [0.0, 0.0, 0.0], 0.0 if alpha is not None else 1.0
        for dx, dy, w in ((0, 0, (1 - ax) * (1 - ay)), (1, 0, ax * (1 - ay)), (0, 1, (1 - ax) * ay), (1, 1, ax * ay)):
            index = texel(iy + dy, height, tiles[1]) * width + texel(ix + dx, width, tiles[0])
            a = max(0.0, min(1.0, alpha[index])) if alpha is not None else 1.0
            if alpha is not None:
                covered += a * w
            for k in range(3):
                found[k] += pixels[index * 3 + k] * w * a
        if alpha is not None:
            found = [c / max(1e-12, covered) for c in found]
        for k in range(3):
            colour[k] += found[k] * weight * covered
        coverage += covered * weight
    if coverage > 0:
        colour = [c / coverage for c in colour]
    return colour, coverage


def procedural_triplanar(projection, d, line=False):
    """Where Modo evaluates a procedural laid by Triplanar for the world direction d: (u, v, weight) for each of the
    three planes an image has (coordinates; X (z, y), Y (x, z), Z (x, y) of q / s, about the image's middle, weighted
    alike), each plane's pair turned by the UV Rotation; then the X plane keeps only its v (its u 0) and the Y plane
    only its u (its v 0), the Z plane both. A Grid of Lines (line), whose lines run along u, takes the Y plane's u as its
    v. Read from Modo's renders (tools/probe_cl_environment_projections.py proc_triplanar* and tri_*: Grids of each
    type, Dots, hardness, uneven sizes, a turn, each axis, UV Rotation, the Wraps; the axis and the Wraps do nothing):
    lines only of y where the X plane is laid, only of x where the Y plane is, the three planes' blend of images
    elsewhere."""
    t = projection['turn']
    s = projection['size']
    q = [d[0] * t[i * 3] + d[1] * t[i * 3 + 1] + d[2] * t[i * 3 + 2] for i in range(3)]
    rotation = float(projection.get('uv_rotation', 0))
    cosine, sine = math.cos(rotation), math.sin(rotation)
    power = 1 + 25 * max(0.0, float(projection.get('hardness', 0)))
    weights = [max(abs(v) - .5, 0.0) ** power for v in q]
    total = sum(weights)
    if total <= 0:
        weights, total = [1.0 if i == max(range(3), key=lambda k: abs(q[k])) else 0.0 for i in range(3)], 1.0
    x, y, z = (q[i] / s[i] for i in range(3))
    xu, xv = _turned_about_middle(.5 + z, .5 + y, cosine, sine)
    yu, yv = _turned_about_middle(.5 + x, .5 + z, cosine, sine)
    planes = ((0.0, xv), (0.0, yu) if line else (yu, 0.0), _turned_about_middle(.5 + x, .5 + y, cosine, sine))
    return [(u, v, w / total) for (u, v), w in zip(planes, weights) if w > 0]


def procedural_coordinates(projection, d, line=False):
    """Where Modo evaluates a procedural (Grid, Dots) for the world direction d: the image's coordinates (coordinates),
    the repeat modes doing nothing (Modo's renders: a Reset locator's Grid carries on past the image); Triplanar's its
    own (procedural_triplanar; line: a Grid of Lines). UV Map, which gives an image one colour, evaluates it at the
    direction's world x and z, the locator doing nothing; Implicit UV and Front Projection at (0, 0), one colour."""
    if projection['projection'] == 'constant':
        return [(d[0], d[2], 1.0) if projection.get('modo_projection') == 'uv' else (0.0, 0.0, 1.0)]
    if projection['projection'] == 'triplanar':
        return procedural_triplanar(projection, d, line)
    return coordinates(projection, d)


def is_line(pattern):
    """Whether a procedural's settings are a Grid of Lines (procedural_triplanar lays its Y plane otherwise)."""
    return pattern.get('kind') == 'grid' and pattern.get('pattern') == 'line'


def procedural(projection, pattern, d, evaluate):
    """A procedural's colour and alpha in direction d: evaluate(pattern, u, v) (procedurals.environment_sample) at each
    of Modo's coordinates (procedural_coordinates), weighted."""
    colour, coverage, total = [0.0, 0.0, 0.0], 0.0, 0.0
    for u, v, weight in procedural_coordinates(projection, d, is_line(pattern)):
        found, alpha = evaluate(pattern, u, v)
        for k in range(3):
            colour[k] += found[k] * weight
        coverage += alpha * weight
        total += weight
    if total > 0:
        colour = [c / total for c in colour]
    return colour, coverage
