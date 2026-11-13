"""An ocean surface, as Tessendorf's "Simulating Ocean Water" (SIGGRAPH course notes) makes it: a Phillips spectrum of
waves driven by the wind, each wave moving at its own speed, summed by FFT into a tile that repeats seamlessly.

MoonRay has no ocean of its own. The kit works the tile out for the frame being rendered and hands MoonRay a texture:
a vector displacement (red the sideways push along U, green the height, blue the push along V, in scene units, for a
tangent-space VectorDisplacement), a foam mask (where the choppy surface folds over, Tessendorf's Jacobian), and the
surface's slope, which MoonLightIPR's shading reads for waves finer than a mesh's vertices are apart. The graph
editor's Ocean and Ocean Foam nodes are expanded into those before any engine sees the graph (nodes.effective), so
MoonRay, XPU2 and MoonLightIPR render the same ocean. A switch in MoonRay Source Overrides (native.ocean) turns it off.

The kit ships modo_ocean.dll (its bin folder), loaded into Modo's Python, which does the work many times faster; were it
missing, the kit would compute the tile itself, in Python, at most 256 across. Both draw the same random numbers (splitmix64, Box-Muller), so either gives the same sea."""
import cmath
import hashlib
import json
import math
import os
import struct
from pathlib import Path

GRAVITY = 9.81
LIBRARY = 'modo_ocean.dll'
FORM = 4  # bumped whenever the model changes, so that tiles made by an older one are made again
# The settings an Ocean node has, with their defaults (nodes.MAPS takes its schema from here).
DEFAULTS = {
    'repeat': [1.0, 1.0],   # how many tiles across the surface's UVs (its first UV map), where fit_to_mesh is off
    # The tiles laid on by the surface itself (fitted): tiles_across of them across its U, as wide as the mesh is over
    # that many, and as many along V as keep them square. The sea is made at its size and scaled to them whole, its
    # heights and its sideways push with its width: a smaller mesh, the same sea smaller.
    'fit_to_mesh': True,
    'tiles_across': 10.0,
    'resolution': 256,      # points across the tile: 64 to 1024, a power of two
    'wind_speed': 10.0,     # metres a second
    'wind_direction': 0.0,  # degrees, from U towards V
    'wave_height': 1.0,     # times a fully developed sea's height for the wind (Pierson-Moskowitz)
    'choppiness': 1.0,      # how far the crests are pushed together sideways
    'small_waves': 0.05,    # waves shorter than this many metres fade out
    'wind_alignment': 2.0,  # how strongly waves follow the wind
    'against_wind': 0.5,    # what is left of waves running against the wind
    'depth': 0.0,           # water depth in metres; 0 is deep water
    'seed': 1,
    'time_scale': 1.0,      # the scene's time times this, plus the offset, in seconds
    'time_offset': 0.0,
    'loop': 0.0,            # seconds after which the waves repeat; 0 never
    # Foam where the surface is squeezed below this (1 is untouched): 0.7 shows it on the sharpest crests of a 10 m/s
    # sea at choppiness 1 (squeezed to about 0.53 there), more as the wind and the choppiness rise.
    'foam_threshold': 0.7,
}
RESOLUTIONS = (64, 128, 256, 512, 1024)
# The tile every sea is made at, in metres (an Ocean node has no Size of its own): fitted to its mesh, it is then
# scaled whole to the tiles laid on the mesh, the waves' look coming from Tiles Across alone; with Fit to Mesh off,
# Repeat lays tiles of this size.
FITTED_SIZE = 80.0
PYTHON_LIMIT = 256


def settings(params):
    """An Ocean node's parameters made whole and checked."""
    value = dict(DEFAULTS)
    value.update({k: v for k, v in (params or {}).items() if k in DEFAULTS})
    for key in DEFAULTS:
        if key in ('repeat', 'resolution', 'seed', 'fit_to_mesh'):
            continue
        value[key] = float(value[key])
        if not math.isfinite(value[key]):
            raise ValueError('Ocean %s must be a number' % key.replace('_', ' '))
    value['resolution'] = int(value['resolution'])
    if value['resolution'] not in RESOLUTIONS:
        raise ValueError('Ocean resolution must be one of %s' % ', '.join(map(str, RESOLUTIONS)))
    value['seed'] = int(value['seed'])
    value['fit_to_mesh'] = bool(value['fit_to_mesh'])
    repeat = list(value['repeat'])[:2] if isinstance(value['repeat'], (list, tuple)) else [1.0, 1.0]
    value['repeat'] = [float(r) for r in repeat] + [1.0] * (2 - len(repeat))
    value['size'] = FITTED_SIZE
    if value['wind_speed'] <= 0 or value['tiles_across'] <= 0:
        raise ValueError('Ocean wind speed and tiles across must be above 0')
    for key in ('wave_height', 'choppiness', 'small_waves', 'wind_alignment', 'against_wind', 'depth', 'loop', 'foam_threshold'):
        if value[key] < 0:
            raise ValueError('Ocean %s cannot be negative' % key.replace('_', ' '))
    return value


def seconds(value, time):
    """The ocean's own time for the scene's time (seconds)."""
    return float(time) * value['time_scale'] + value['time_offset']


# ---- The random numbers, the same in modo_ocean.cpp ------------------------------------------------------------------

MASK = (1 << 64) - 1


def splitmix(state):
    state = (state + 0x9E3779B97F4A7C15) & MASK
    z = state
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK
    return state, z ^ (z >> 31)


def gaussians(seed, count):
    """count pairs of standard normal numbers, by Box-Muller from splitmix64's uniform ones."""
    state = (seed * 0x2545F4914F6CDD1D + 1) & MASK
    result = []
    for _ in range(count):
        state, a = splitmix(state)
        state, b = splitmix(state)
        u1 = ((a >> 11) + 1) / float(1 << 53)  # (0, 1]
        u2 = (b >> 11) / float(1 << 53)        # [0, 1)
        r = math.sqrt(-2.0 * math.log(u1))
        result.append((r * math.cos(2 * math.pi * u2), r * math.sin(2 * math.pi * u2)))
    return result


# ---- The model -------------------------------------------------------------------------------------------------------

def wavenumbers(value):
    n, size = value['resolution'], value['size']
    return [2 * math.pi * (i - n // 2) / size for i in range(n)]


def phillips(value, kx, kz):
    k2 = kx * kx + kz * kz
    if k2 < 1e-12:
        return 0.0
    k = math.sqrt(k2)
    big = value['wind_speed'] ** 2 / GRAVITY
    angle = math.radians(value['wind_direction'])
    along = (kx * math.cos(angle) + kz * math.sin(angle)) / k
    p = math.exp(-1.0 / (k2 * big * big)) / (k2 * k2) * abs(along) ** value['wind_alignment']
    if along < 0:
        p *= value['against_wind']
    small = value['small_waves']
    return p * math.exp(-k2 * small * small)


def frequency(value, k):
    if value['depth'] > 0:
        w = math.sqrt(GRAVITY * k * math.tanh(k * value['depth']))
    else:
        w = math.sqrt(GRAVITY * k)
    if value['loop'] > 0:
        w0 = 2 * math.pi / value['loop']
        w = math.floor(w / w0) * w0
    return w


def initial(value):
    """h0(k) for every wavenumber, rows by z, and the scale that gives the wanted height."""
    n = value['resolution']
    ks = wavenumbers(value)
    noise = gaussians(value['seed'], n * n)
    h0 = [[0j] * n for _ in range(n)]
    for j in range(n):
        for i in range(n):
            amplitude = math.sqrt(phillips(value, ks[i], ks[j]) / 2.0)
            g = noise[j * n + i]
            h0[j][i] = complex(g[0] * amplitude, g[1] * amplitude)
    # Heights as a fully developed sea's for the wind (Pierson-Moskowitz: significant height 0.21 V^2 / g, four times
    # the heights' spread), whatever the tile's size and resolution: the spread a field of these waves has on average.
    variance = 0.0
    for j in range(n):
        for i in range(n):
            mirror = h0[(n - j) % n][(n - i) % n]
            variance += abs(h0[j][i]) ** 2 + abs(mirror) ** 2
    target = value['wave_height'] * 0.21 * value['wind_speed'] ** 2 / GRAVITY / 4.0
    scale = target / math.sqrt(variance) if variance > 0 else 0.0
    return h0, scale


def ifft(row):
    """An inverse DFT without the 1/n, radix 2, in place on a list of complex numbers."""
    n = len(row)
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            row[i], row[j] = row[j], row[i]
    length = 2
    while length <= n:
        step = cmath.exp(2j * math.pi / length)
        half = length // 2
        for start in range(0, n, length):
            w = 1 + 0j
            for k in range(start, start + half):
                a, b = row[k], row[k + half] * w
                row[k], row[k + half] = a + b, a - b
                w *= step
        length <<= 1
    return row


def ifft2(grid):
    n = len(grid)
    rows = [ifft(list(r)) for r in grid]
    columns = [ifft([rows[j][i] for j in range(n)]) for i in range(n)]
    return [[columns[i][j] for i in range(n)] for j in range(n)]


def fields(value, time, slopes=False):
    """Displacement (dx, height, dz) and foam at each point of the tile, rows by z, in scene units; with slopes, also
    the displaced surface's slope as the height's change across one tile along U and along V (its tangents' normal)."""
    n = value['resolution']
    h0, scale = initial(value)
    ks = wavenumbers(value)
    t = seconds(value, time)
    chop = value['choppiness']
    # Two real fields in each transform: a + ib, a and b each from a spectrum with Hermitian symmetry.
    pair1, pair2, pair3, pair4 = ([[0j] * n for _ in range(n)] for _ in range(4))
    for j in range(n):
        for i in range(n):
            kx, kz = ks[i], ks[j]
            k = math.hypot(kx, kz)
            if k < 1e-12:
                continue
            w = frequency(value, k) * t
            e = complex(math.cos(w), math.sin(w))
            h = h0[j][i] * e + h0[(n - j) % n][(n - i) % n].conjugate() * e.conjugate()
            dx, dz = -1j * kx / k * h, -1j * kz / k * h
            jxx, jzz, jxz = kx * kx / k * h, kz * kz / k * h, kx * kz / k * h
            pair1[j][i] = h + 1j * dx
            pair2[j][i] = dz + 1j * jxx
            pair3[j][i] = jzz + 1j * jxz
            pair4[j][i] = 1j * kx * h + 1j * (1j * kz * h)
    a, b, c = ifft2(pair1), ifft2(pair2), ifft2(pair3)
    d = ifft2(pair4) if slopes else None
    displacement, foam, slope = [], [], []
    threshold = value['foam_threshold']
    for j in range(n):
        for i in range(n):
            sign = -1.0 if (i + j) & 1 else 1.0  # the wavenumbers run from -n/2: a sign at every other point
            h, dx = a[j][i].real * sign * scale, a[j][i].imag * sign * scale
            dz, jxx = b[j][i].real * sign * scale, b[j][i].imag * sign * scale
            jzz, jxz = c[j][i].real * sign * scale, c[j][i].imag * sign * scale
            displacement.append((chop * dx, h, chop * dz))
            jacobian = (1 + chop * jxx) * (1 + chop * jzz) - (chop * jxz) ** 2
            foam.append(min(1.0, max(0.0, (threshold - jacobian) / threshold)) if threshold > 0 else 0.0)
            if slopes:
                hx, hz = d[j][i].real * sign * scale, d[j][i].imag * sign * scale
                ax, bz, e = 1 + chop * jxx, 1 + chop * jzz, chop * jxz
                held = max(jacobian, 0.05)
                slope.append(((bz * hx - e * hz) / held * value['size'], (ax * hz - e * hx) / held * value['size'], 0.0))
    return (displacement, foam, slope) if slopes else (displacement, foam)


# ---- Tiles on disk ---------------------------------------------------------------------------------------------------

def key(value, time):
    """What a tile is made from: its settings that shape the waves, and the moment."""
    shape = {k: value[k] for k in DEFAULTS if k not in ('repeat', 'fit_to_mesh', 'tiles_across', 'time_scale', 'time_offset')}
    return hashlib.sha256(json.dumps([FORM, shape, round(seconds(value, time), 6)], sort_keys=True).encode()).hexdigest()[:24]


def folder():
    from .cache_folder import root as cache_root
    path = cache_root() / 'Ocean'
    path.mkdir(parents=True, exist_ok=True)
    return path


def paths(value, time):
    """The tile's displacement, foam and slope images (PFM) for these settings and this moment."""
    stem = folder() / key(value, time)
    return stem.with_suffix('.displacement.pfm'), stem.with_suffix('.foam.pfm'), stem.with_suffix('.slope.pfm')


def write_pfm(path, width, values, channels):
    data = bytearray(('PF\n' if channels == 3 else 'Pf\n').encode())
    data += ('%d %d\n-1.0\n' % (width, width)).encode()
    # PFM keeps its rows bottom up: the first row written is V = 0.
    for j in range(width):
        row = values[j * width:(j + 1) * width]
        data += struct.pack('<%df' % (width * channels), *(c for v in row for c in (v if channels == 3 else (v,))))
    staged = path.with_name(path.name + '.part')
    staged.write_bytes(bytes(data))
    os.replace(staged, path)


_LIBRARY = {}


def library(path=None):
    """modo_ocean.dll, loaded into this Python (ctypes): the kit's own, in its bin folder as the release ships it, or the
    one at path. None where it is not there or does not load."""
    path = Path(path) if path else Path(__file__).resolve().parents[2] / 'bin' / LIBRARY
    if str(path) not in _LIBRARY:
        held = None
        if path.is_file():
            try:
                import ctypes
                held = ctypes.CDLL(str(path))
                held.modo_ocean_tile_slope.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_double), ctypes.c_int, ctypes.c_char_p,
                                                       ctypes.c_char_p, ctypes.c_char_p]
                held.modo_ocean_tile_slope.restype = ctypes.c_int
            except (OSError, AttributeError):
                held = None
        _LIBRARY[str(path)] = held
    return _LIBRARY[str(path)]


def values(value, time):
    """The library's numbers, in its order: size to foam threshold, then the ocean's seconds."""
    order = ('size', 'wind_speed', 'wind_direction', 'wave_height', 'choppiness', 'small_waves', 'wind_alignment', 'against_wind',
             'depth', 'seed', 'loop', 'foam_threshold')
    return [float(value[k]) for k in order] + [seconds(value, time)]


def native_tile(value, time, displacement, foam, slope, path=None):
    """The tile made by modo_ocean.dll into the three paths; whether it was."""
    held = library(path)
    if held is None:
        return False
    import ctypes
    numbers = values(value, time)
    array = (ctypes.c_double * len(numbers))(*numbers)
    done = held.modo_ocean_tile_slope(int(value['resolution']), array, len(numbers), str(displacement).encode('mbcs'),
                                      str(foam).encode('mbcs'), str(slope).encode('mbcs'))
    return done == 0 and all(Path(p).is_file() for p in (displacement, foam, slope))


def make(value, time, runtime=None):
    """The tile's three images, made where they are not on disk yet; their paths."""
    made = paths(value, time)
    if all(p.is_file() for p in made):
        return made
    if native_tile(value, time, *made):
        return made
    if value['resolution'] > PYTHON_LIMIT:
        # In Python a large tile takes too long: the largest it makes, the waves the same, the detail less fine.
        value = dict(value, resolution=PYTHON_LIMIT)
        made = paths(value, time)
        if all(p.is_file() for p in made):
            return made
    vectors, mask, slopes = fields(value, time, slopes=True)
    write_pfm(made[0], value['resolution'], vectors, 3)
    write_pfm(made[1], value['resolution'], [(m, m, m) for m in mask], 3)
    write_pfm(made[2], value['resolution'], slopes, 3)
    return made


# The frame a scene is being written for: its time in seconds and the runtime, set while rdla or MoonLightIPR's packer
# writes it (writing). Outside, an Ocean node's tile is only named, not made: the graph editor checks graphs often.
CONTEXT = {'time': None, 'runtime': None}


class writing:
    """with ocean.writing(time, runtime): Ocean tiles are made for this frame while a scene is written."""
    def __init__(self, time, runtime=None):
        self.held = (time, runtime)

    def __enter__(self):
        self.before = dict(CONTEXT)
        CONTEXT['time'], CONTEXT['runtime'] = float(self.held[0] or 0.0), self.held[1]
        return self

    def __exit__(self, *exc):
        CONTEXT.update(self.before)
        return False


def tile(value):
    """The displacement, foam and slope images of the tile for the frame being written (made if need be), or for time 0 named
    only where no scene is being written."""
    time = CONTEXT['time']
    if time is None:
        return paths(value, 0.0)
    return make(value, time, CONTEXT['runtime'])


def reach(value):
    """How far the surface can move, for MoonRay's bound padding: four of the heights' spread, and the push sideways."""
    return value['wave_height'] * 0.21 * value['wind_speed'] ** 2 / GRAVITY * (1.0 + value['choppiness'])


# ---- Repeat fitted to the surface --------------------------------------------------------------------------------------

def uv_metres(mesh, limit=4000):
    """How many metres one unit of a mesh's first UV map spans in the world, across U and across V (its matrix's scale
    taken in): each triangle's own, weighted by its area, from at most limit of its faces spread over it. None where
    the mesh has no UVs, or none that span anything."""
    from .rows import corners as flat_corners, counts as flat_counts, numbers
    vertices, faces, uvs = mesh.get('vertices'), mesh.get('faces'), mesh.get('uvs')
    if not vertices or not faces or not uvs:
        return None
    points = numbers(vertices, 3)
    points = points if points is not None else [c for v in vertices for c in v]
    corners_uv = numbers(uvs, 2)
    corners_uv = corners_uv if corners_uv is not None else [c for uv in uvs for c in uv]
    held, sizes = flat_corners(faces), flat_counts(faces)
    if held is None or sizes is None:
        sizes = [len(face) for face in faces]
        held = [i for face in faces for i in face]
    starts, at = [], 0
    for size in sizes:
        starts.append(at)
        at += size
    if len(corners_uv) < 2 * at:
        return None
    matrix = mesh.get('matrix') or [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]

    def world(v):
        return [v[0] * matrix[0] + v[1] * matrix[4] + v[2] * matrix[8], v[0] * matrix[1] + v[1] * matrix[5] + v[2] * matrix[9],
                v[0] * matrix[2] + v[1] * matrix[6] + v[2] * matrix[10]]
    step = max(1, len(sizes) // limit)
    along_u = along_v = weight = 0.0
    for face in range(0, len(sizes), step):
        start, size = starts[face], sizes[face]
        for k in range(1, size - 1):
            a, b, c = start, start + k, start + k + 1
            ia, ib, ic = held[a], held[b], held[c]
            p0, p1, p2 = (points[3 * i:3 * i + 3] for i in (ia, ib, ic))
            e1 = world([p1[j] - p0[j] for j in range(3)])
            e2 = world([p2[j] - p0[j] for j in range(3)])
            d1 = (corners_uv[2 * b] - corners_uv[2 * a], corners_uv[2 * b + 1] - corners_uv[2 * a + 1])
            d2 = (corners_uv[2 * c] - corners_uv[2 * a], corners_uv[2 * c + 1] - corners_uv[2 * a + 1])
            det = d1[0] * d2[1] - d2[0] * d1[1]
            if abs(det) < 1e-12:
                continue
            dpdu = [(e1[j] * d2[1] - e2[j] * d1[1]) / det for j in range(3)]
            dpdv = [(e2[j] * d1[0] - e1[j] * d2[0]) / det for j in range(3)]
            cross = [e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]]
            area = math.sqrt(sum(x * x for x in cross))
            along_u += area * math.sqrt(sum(x * x for x in dpdu))
            along_v += area * math.sqrt(sum(x * x for x in dpdv))
            weight += area
    if weight <= 0:
        return None
    return along_u / weight, along_v / weight, weight


def fitted(scene):
    """The scene with each Ocean and Ocean Foam node whose Fit to Mesh is on laid on the meshes its material is on in
    Tiles Across tiles across their U (uv_metres, area weighted over those meshes): its repeat that many along U and as
    many along V as keep the tiles square, made at FITTED_SIZE (its own Size is for Fit to Mesh off), and its _scale
    (on the node, nodes.expand_ocean) what makes a tile of that size that wide, the sea scaled whole by it, heights and
    sideways push too; made only at its own size, a small mesh
    had waves as high as the wind makes on tiles a few metres wide, folding over. The scene as it was where there is
    none. Its materials and graphs are copies where they change."""
    import copy
    from . import face_tags
    materials = scene.get('materials') or {}

    def oceans(material):
        for row in material.get('material_stack') or [material]:
            graph = row.get('node_graph') if isinstance(row, dict) else None
            for node in ((graph or {}).get('nodes') or {}).values():
                own = node.get('parameters') or {}
                if (node.get('type') == 'ocean' or (node.get('type') == 'ocean_foam' and own)) and own.get('fit_to_mesh', DEFAULTS['fit_to_mesh']):
                    return True
        return False
    wanted = {tag for tag, material in materials.items() if isinstance(material, dict) and oceans(material)}
    if not wanted:
        return scene
    spans = {}
    for mesh in scene.get('meshes') or []:
        tags = {tag if tag in materials else '' for tag in face_tags.worn(mesh)} & wanted
        if not tags:
            continue
        found = uv_metres(mesh)
        if found is None:
            continue
        for tag in tags:
            u, v, w = spans.get(tag, (0.0, 0.0, 0.0))
            spans[tag] = (u + found[0] * found[2], v + found[1] * found[2], w + found[2])
    if not spans:
        return scene
    result = dict(scene, materials=dict(materials))
    for tag, (u, v, w) in spans.items():
        metres = (u / w, v / w)
        material = copy.deepcopy(materials[tag])
        for row in material.get('material_stack') or [material]:
            graph = row.get('node_graph') if isinstance(row, dict) else None
            for node in ((graph or {}).get('nodes') or {}).values():
                params = node.get('parameters')
                if node.get('type') not in ('ocean', 'ocean_foam') or not (params or {}).get('fit_to_mesh', DEFAULTS['fit_to_mesh']):
                    continue
                if node['type'] == 'ocean_foam' and not params:
                    continue    # it follows the Ocean node, which is fitted
                tiles = float((params or {}).get('tiles_across', DEFAULTS['tiles_across']))
                if tiles > 0 and math.isfinite(tiles) and metres[0] > 0:
                    wide = metres[0] / tiles
                    held = node.setdefault('parameters', {})
                    held['repeat'] = [tiles, max(1e-3, metres[1] / wide)]
                    node['_scale'] = wide / FITTED_SIZE
        result['materials'][tag] = material
    return result
