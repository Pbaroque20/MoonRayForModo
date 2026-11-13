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
FORM = 3  # bumped whenever the model changes, so that tiles made by an older one are made again
# The settings an Ocean node has, with their defaults (nodes.MAPS takes its schema from here).
DEFAULTS = {
    'size': 50.0,           # the tile's width in scene units (metres)
    'repeat': [1.0, 1.0],   # how many tiles across the surface's UVs (its first UV map)
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
PYTHON_LIMIT = 256


def settings(params):
    """An Ocean node's parameters made whole and checked."""
    value = dict(DEFAULTS)
    value.update({k: v for k, v in (params or {}).items() if k in DEFAULTS})
    for key in DEFAULTS:
        if key in ('repeat', 'resolution', 'seed'):
            continue
        value[key] = float(value[key])
        if not math.isfinite(value[key]):
            raise ValueError('Ocean %s must be a number' % key.replace('_', ' '))
    value['resolution'] = int(value['resolution'])
    if value['resolution'] not in RESOLUTIONS:
        raise ValueError('Ocean resolution must be one of %s' % ', '.join(map(str, RESOLUTIONS)))
    value['seed'] = int(value['seed'])
    repeat = list(value['repeat'])[:2] if isinstance(value['repeat'], (list, tuple)) else [1.0, 1.0]
    value['repeat'] = [float(r) for r in repeat] + [1.0] * (2 - len(repeat))
    if value['size'] <= 0 or value['wind_speed'] <= 0:
        raise ValueError('Ocean size and wind speed must be above 0')
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
    shape = {k: value[k] for k in DEFAULTS if k not in ('repeat', 'time_scale', 'time_offset')}
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
