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
FORM = 5  # bumped whenever the model changes, so that tiles made by an older one are made again
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
    # The sea over four tiles of unrelated sizes, its waves shared out between them by length (CASCADES), so that its
    # pattern never repeats in sight; off, one tile, which repeats every Tile's width.
    'cascades': True,
    # A swell: one long, regular wave running through the sea, as from a storm far away (swell_fields), its height
    # from trough to crest and its length in the sea's own metres (as the wind's waves are, before Tiles Across or Tile
    # Size scale them), running towards Swell Direction (as Wind Direction: the same angle runs with the wind's waves).
    # Height 0, none.
    'swell_height': 0.0,
    'swell_length': 120.0,
    'swell_direction': 0.0,
    # The Ocean Crest node's mask (crest_tile): 0 where the surface stands below this share of the waves' height, up
    # to 1 at their highest, for the light that shines through the crests.
    'crest_start': 0.3,
}
SWELL_KEYS = ('swell_height', 'swell_length', 'swell_direction')
CREST_KEYS = ('crest_start',)
# The nodes that give a mask of the sea, not its displacement: its foam, and its crests.
MASK_NODES = ('ocean_foam', 'ocean_crest')
# Points along the swell's tile: one wave across it, smooth, so few are needed.
SWELL_RESOLUTION = 128
RESOLUTIONS = (64, 128, 256, 512, 1024)
# The cascades: each a tile this many times the sea's tile (FITTED_SIZE), holding the waves between these many cycles
# across the sea's tile (0: no end). The sizes are powers of the golden ratio, so no two tiles' repeats ever line up.
# Each holds five or more of its own waves, so none shows its tile: one with two waves across showed a grid of its
# steepest ones to the horizon. The longest waves on a tile 4.24 times as wide (80 to 40 m on the sea's 80 m tile),
# then 2.62 (40 to 13 m), the sea's own (13 to 3 m), and ripples under 3 m on one 0.38 as wide, too fine to show a grid
# from afar. Together they are the one tile's waves (no longer, none lost), shared out by length.
PHI = (1 + 5 ** 0.5) / 2
CASCADES = ((PHI ** 3, 1.0, 2.0), (PHI ** 2, 2.0, 6.0), (1.0, 6.0, 26.0), (PHI ** -2, 26.0, 0.0))
# Each cascade's tiles turned by these many degrees on the surface (the ImageMap's rotation_angle), its wind turned back
# by as much, so that no tile's grid lines up with another's or with the surface's U and V (a view along them saw the
# smallest tile's grid in rows); the sea's waves still run with the wind.
TURNS = (21.0, -38.0, 57.0, -11.0)
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
        if key in ('repeat', 'resolution', 'seed', 'fit_to_mesh', 'cascades'):
            continue
        value[key] = float(value[key])
        if not math.isfinite(value[key]):
            raise ValueError('Ocean %s must be a number' % key.replace('_', ' '))
    value['resolution'] = int(value['resolution'])
    if value['resolution'] not in RESOLUTIONS:
        raise ValueError('Ocean resolution must be one of %s' % ', '.join(map(str, RESOLUTIONS)))
    value['seed'] = int(value['seed'])
    value['fit_to_mesh'] = bool(value['fit_to_mesh'])
    value['cascades'] = bool(value['cascades'])
    repeat = list(value['repeat'])[:2] if isinstance(value['repeat'], (list, tuple)) else [1.0, 1.0]
    value['repeat'] = [float(r) for r in repeat] + [1.0] * (2 - len(repeat))
    value['size'] = FITTED_SIZE
    if value['wind_speed'] <= 0 or value['tiles_across'] <= 0:
        raise ValueError('Ocean wind speed and tiles across must be above 0')
    if not 0.0 <= value['crest_start'] < 1.0:
        raise ValueError('Ocean crest start must be from 0 to under 1')
    if value['swell_length'] <= 0:
        raise ValueError('Ocean swell length must be above 0')
    for key in ('wave_height', 'choppiness', 'small_waves', 'wind_alignment', 'against_wind', 'depth', 'loop', 'foam_threshold', 'swell_height'):
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


def cell_amplitude(value, kx, kz):
    """A cell's amplitude before the heights' scale: the whole tile's sqrt(P / 2); a cascade's (fixed_scale) only within
    its band, by its share of the spectrum over its own cells (times a cell's width in wavenumber, 2 pi over its tile)."""
    if 'fixed_scale' not in value:
        return math.sqrt(phillips(value, kx, kz) / 2.0)
    k = math.hypot(kx, kz)
    if k < value['k_low'] or (value['k_high'] > 0 and k >= value['k_high']):
        return 0.0
    return math.sqrt(phillips(value, kx, kz) / 2.0) * (2 * math.pi / value['size'])


# Each band's variance, by the numbers it is made from (band_variance): the same sea, packed again at each step of a
# drag, summed its 48 bands again each time, half a second of a step on a test dragon's sea.
_VARIANCES = {}


def band_variance(value):
    """A cascade's expected variance of the heights before their scale: 2 P(k) times a cell's area in wavenumber, over
    its band's cells (modo_ocean.dll's modo_ocean_band_variance where it is there). Worked out once for the same numbers."""
    try:
        known = (int(value['resolution']), tuple(values(dict(value, fixed_scale=1.0), 0.0)))
    except (KeyError, TypeError, ValueError):
        known = None
    if known is not None and known in _VARIANCES:
        return _VARIANCES[known]
    found = _band_variance(value)
    if known is not None:
        if len(_VARIANCES) > 512:
            _VARIANCES.clear()
        _VARIANCES[known] = found
    return found


def _band_variance(value):
    held = library()
    if held is not None and hasattr(held, 'modo_ocean_band_variance'):
        import ctypes
        call = held.modo_ocean_band_variance
        call.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_double), ctypes.c_int, ctypes.POINTER(ctypes.c_double)]
        call.restype = ctypes.c_int
        numbers = values(dict(value, fixed_scale=1.0), 0.0)
        out = ctypes.c_double(0.0)
        if call(int(value['resolution']), (ctypes.c_double * len(numbers))(*numbers), len(numbers), ctypes.byref(out)) == 0:
            return out.value
    n, cell, total = value['resolution'], 2 * math.pi / value['size'], 0.0
    for j in range(n):
        for i in range(n):
            kx, kz = cell * (i - n // 2), cell * (j - n // 2)
            k = math.hypot(kx, kz)
            if k < 1e-12 or k < value['k_low'] or (value['k_high'] > 0 and k >= value['k_high']):
                continue
            total += 2.0 * phillips(value, kx, kz) * cell * cell
    return total


def cascade_values(value):
    """The sea's cascades (CASCADES), each the settings of its own tile: its size, its band of wavenumbers, a seed of its
    own, and the heights' scale they share, which makes the sea's heights together a fully developed sea's for its
    wind, as one tile's are. One, the tile itself, where cascades are off."""
    if not value.get('cascades'):
        return [value]
    base = 2 * math.pi / FITTED_SIZE
    found = []
    for index, (ratio, low, high) in enumerate(CASCADES):
        found.append(dict(value, size=FITTED_SIZE * ratio, k_low=low * base, k_high=high * base if high else 0.0,
                          seed=int(value['seed']) + 1000003 * index, cascade=index, turn=TURNS[index],
                          wind_direction=value['wind_direction'] - TURNS[index]))
    variance = sum(band_variance(dict(c, fixed_scale=1.0)) for c in found)
    target = value['wave_height'] * 0.21 * value['wind_speed'] ** 2 / GRAVITY / 4.0
    scale = target / math.sqrt(variance) if variance > 0 else 0.0
    # A sea with no waves at all (no wind energy in any band) is flat, not the whole tile's.
    return [dict(c, fixed_scale=scale if scale > 0 else 1e-30) for c in found]


def swell_values(value):
    """The swell's tile, where Swell Height is above 0: a tile one wave long (Swell Length) turned to Swell Direction
    (the ImageMap's rotation_angle, as a cascade's), its wave running along the tile's U; none otherwise."""
    if not value.get('swell_height', 0.0) > 0:
        return []
    return [dict(value, swell=True, size=float(value['swell_length']), turn=float(value['swell_direction']),
                 resolution=SWELL_RESOLUTION)]


def swell_frequency(value, k):
    """The swell's angular frequency: the waves' own (frequency), but where Loop is set, the nearest whole number of
    turns in the loop, at least one (the wind's waves round down, which could stop a long swell dead)."""
    w = math.sqrt(GRAVITY * k * math.tanh(k * value['depth'])) if value['depth'] > 0 else math.sqrt(GRAVITY * k)
    if value['loop'] > 0:
        w0 = 2 * math.pi / value['loop']
        w = max(1, round(w / w0)) * w0
    return w


def swell_fields(value, time):
    """The swell's tile, as fields() gives a tile: one Gerstner wave along the tile's U, a cosine of height (Swell
    Height from trough to crest) pushed sideways by the sea's Choppiness as the wind's waves are (Tessendorf's
    displacement for a single wave), and its slope; no foam of its own. The same signs as fields(): the wave at +k
    with phase k x + w t, so that it runs as the wind's waves of the same direction do."""
    n, size = value['resolution'], value['size']
    k = 2 * math.pi / size
    amplitude = value['swell_height'] / 2.0
    phase = swell_frequency(value, k) * seconds(value, time)
    chop = value['choppiness']
    cos_turn, sin_turn = math.cos(math.radians(value.get('turn', 0.0))), math.sin(math.radians(value.get('turn', 0.0)))
    row_d, row_s = [], []
    for i in range(n):
        angle = k * (i * size / n) + phase
        h, dx = amplitude * math.cos(angle), amplitude * math.sin(angle)
        jxx, hx = k * amplitude * math.cos(angle), -k * amplitude * math.sin(angle)
        row_d.append((chop * cos_turn * dx, h, chop * sin_turn * dx))
        gx = hx / max(1 + chop * jxx, 0.05) * size
        row_s.append((cos_turn * gx, sin_turn * gx, 0.0))
    return row_d * n, [0.0] * (n * n), row_s * n


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
            amplitude = cell_amplitude(value, ks[i], ks[j])
            g = noise[j * n + i]
            h0[j][i] = complex(g[0] * amplitude, g[1] * amplitude)
    if value.get('fixed_scale'):
        return h0, value['fixed_scale']
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


def fields(value, time, slopes=False, cutoff=0.0):
    """Displacement (dx, height, dz) and foam at each point of the tile, rows by z, in scene units; with slopes, also
    the displaced surface's slope as the height's change across one tile along U and along V (its tangents' normal).
    With cutoff (cycles across the tile) above 0, only the waves longer than it, each weighed by exp(-(cycles /
    cutoff)^2) (split)."""
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
            if cutoff > 0:
                h *= math.exp(-(k * value['size'] / (2 * math.pi) / cutoff) ** 2)
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
    cos_turn, sin_turn = math.cos(math.radians(value.get('turn', 0.0))), math.sin(math.radians(value.get('turn', 0.0)))
    for j in range(n):
        for i in range(n):
            sign = -1.0 if (i + j) & 1 else 1.0  # the wavenumbers run from -n/2: a sign at every other point
            h, dx = a[j][i].real * sign * scale, a[j][i].imag * sign * scale
            dz, jxx = b[j][i].real * sign * scale, b[j][i].imag * sign * scale
            jzz, jxz = c[j][i].real * sign * scale, c[j][i].imag * sign * scale
            # Turned from the tile's axes into the surface's (its lookup turns surface to tile by -turn).
            displacement.append((chop * (cos_turn * dx - sin_turn * dz), h, chop * (sin_turn * dx + cos_turn * dz)))
            jacobian = (1 + chop * jxx) * (1 + chop * jzz) - (chop * jxz) ** 2
            foam.append(min(1.0, max(0.0, (threshold - jacobian) / threshold)) if threshold > 0 else 0.0)
            if slopes:
                hx, hz = d[j][i].real * sign * scale, d[j][i].imag * sign * scale
                ax, bz, e = 1 + chop * jxx, 1 + chop * jzz, chop * jxz
                held = max(jacobian, 0.05)
                gx, gz = (bz * hx - e * hz) / held * value['size'], (ax * hz - e * hx) / held * value['size']
                slope.append((cos_turn * gx - sin_turn * gz, sin_turn * gx + cos_turn * gz, 0.0))
    return (displacement, foam, slope) if slopes else (displacement, foam)


# ---- Tiles on disk ---------------------------------------------------------------------------------------------------

def key(value, time):
    """What a tile is made from: its settings that shape the waves, and the moment."""
    # The swell's settings shape only the swell's tile, so that the wind's tiles made before it are still the same.
    shape = {k: value[k] for k in DEFAULTS if k not in ('repeat', 'fit_to_mesh', 'tiles_across', 'time_scale', 'time_offset') + SWELL_KEYS + CREST_KEYS}
    shape.update({k: value[k] for k in ('size', 'k_low', 'k_high', 'fixed_scale', 'turn') if k in value})
    if value.get('swell'):
        shape = {k: value[k] for k in SWELL_KEYS + ('choppiness', 'depth', 'loop', 'size', 'turn', 'resolution')}
        shape['swell'] = 1
    return hashlib.sha256(json.dumps([FORM, shape, round(seconds(value, time), 6)], sort_keys=True).encode()).hexdigest()[:24]


# The Ocean folder as made: made once, not for each of a sea's tiles at each pack (48 a step of a drag). Made again after
# the folder is trimmed or the cache cleared (forget_seen), or the cache folder chosen is another.
_FOLDER = {}


def folder():
    from .cache_folder import root as cache_root
    path = cache_root() / 'Ocean'
    if _FOLDER.get('made') != path:
        path.mkdir(parents=True, exist_ok=True)
        _FOLDER['made'] = path
    return path


# How many tiles were made since the folder was last looked over (trim): looked over at the first made in a session,
# then every TRIM_EVERY.
_MADE = [0]
TRIM_EVERY = 16


def kept_bytes():
    """What the Ocean folder may come to (the cache folder's own limit for each of its kinds), the least lately used let
    go beyond it."""
    from .cache_folder import KEPT_BYTES
    return KEPT_BYTES


def used(made):
    """Tiles found on disk and used again: marked as lately used, so that trim lets go of older ones first, with what
    MoonLightIPR made ready of each beside it (its name and ".mlt", session/scene_loader.cpp)."""
    for path in made:
        for each in (Path(path), Path(str(path) + '.mlt')):
            try:
                os.utime(each)
            except OSError:
                pass
    return made


def trim(path=None, limit=None):
    """The Ocean folder brought back under its limit (kept_bytes), the least lately used files let go first. A sea's
    tiles are made for each moment it is rendered at (key), each moment's some 50 MB: a tester's animated seas came to
    32 GB in a day, with nothing let go, and filled the disk. Returns the bytes freed."""
    path = Path(path) if path else folder()
    limit = kept_bytes() if limit is None else limit
    # What it lets go is no longer there to be trusted (make).
    forget_seen()
    try:
        files = sorted((entry.stat().st_mtime, entry.stat().st_size, entry) for entry in path.iterdir() if entry.is_file())
    except OSError:
        return 0
    total = sum(size for _, size, _ in files)
    freed = 0
    for _, size, entry in files:
        if total <= limit:
            break
        try:
            entry.unlink()
            total -= size
            freed += size
        except OSError:
            pass    # One a render has open is left.
    return freed


def _made():
    """A tile just made: the folder looked over now and then (trim)."""
    _MADE[0] += 1
    if _MADE[0] % TRIM_EVERY == 1:
        trim()


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
    numbers = [float(value[k]) for k in order] + [seconds(value, time)]
    if 'fixed_scale' in value:
        numbers += [float(value['k_low']), float(value['k_high']), float(value['fixed_scale']), float(value.get('turn', 0.0))]
    return numbers


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


# Tiles found on disk, and when (time.monotonic): trusted as there, and marked used, for SEEN_FOR seconds. Each step of a
# drag packs the sea again, which looked for its tiles and marked them used each time (288 files, a sixth of a second).
# Forgotten as the folder is trimmed or the cache cleared (forget_seen).
_SEEN = {}
SEEN_FOR = 30.0


def forget_seen():
    _SEEN.clear()
    _FOLDER.clear()


def make(value, time, runtime=None):
    """The tile's three images, made where they are not on disk yet; their paths."""
    made = paths(value, time)
    import time as clock
    now = clock.monotonic()
    if now - _SEEN.get(made, -SEEN_FOR - 1.0) <= SEEN_FOR:
        return made
    if all(p.is_file() for p in made):
        _SEEN[made] = now
        return used(made)
    _made()
    if value.get('swell'):
        vectors, mask, slopes = swell_fields(value, time)
        write_pfm(made[0], value['resolution'], vectors, 3)
        write_pfm(made[1], value['resolution'], [(m, m, m) for m in mask], 3)
        write_pfm(made[2], value['resolution'], slopes, 3)
        return made
    if native_tile(value, time, *made):
        return made
    if value['resolution'] > PYTHON_LIMIT:
        # In Python a large tile takes too long: the largest it makes, the waves the same, the detail less fine.
        value = dict(value, resolution=PYTHON_LIMIT)
        made = paths(value, time)
        if all(p.is_file() for p in made):
            return used(made)
    vectors, mask, slopes = fields(value, time, slopes=True)
    write_pfm(made[0], value['resolution'], vectors, 3)
    write_pfm(made[1], value['resolution'], [(m, m, m) for m in mask], 3)
    write_pfm(made[2], value['resolution'], slopes, 3)
    return made


# ---- The tile split for MoonRay --------------------------------------------------------------------------------------
# MoonRay dices a displaced surface no finer than its mesh resolution (the subdivision level's, 8 as a rule): waves
# shorter than a few of its steps come out as creases, not waves (a tester's 256-face sea), and dicing it finer cost a
# quarter more time and three times the memory. So MoonRay is given the long waves as the displacement and the rest
# as a normal map over them, as MoonLightIPR shades what its vertices cannot follow; MoonLightIPR keeps the tile whole.

# Dicing steps to each wave the displacement keeps: fewer, and the shortest ones it keeps crease.
STEPS_PER_WAVE = 4.0
# The mesh resolution an ocean's surface is diced at by MoonRay where it is diced by the screen (rdla, ocean_resolution
# on the mesh), above the subdivision level's 8: measured on a tester's sea, 32 cost about 3% more time and no more
# memory, where 1024 cost a quarter more time and three times the memory. Within OCEAN_TRIANGLES at that resolution all
# over (the screen dices most of it far coarser), so that a dense mesh is not made heavier.
OCEAN_RESOLUTION, OCEAN_TRIANGLES = 32, 4000000


def ocean_resolution(mesh, held):
    """The mesh resolution an ocean's surface is diced at (OCEAN_RESOLUTION within OCEAN_TRIANGLES), never under the
    level's own (held)."""
    faces = max(1, len(mesh.get('faces') or ()))
    budget = int(math.sqrt(OCEAN_TRIANGLES / (2.0 * faces)))
    return max(int(held), min(OCEAN_RESOLUTION, budget))


def cutoff(spacing, resolution):
    """The split, in cycles across the tile, for dicing steps spacing (a fraction of the tile) apart: waves of
    STEPS_PER_WAVE steps and longer stay displacement. A power of two, so that a mesh a little larger or smaller keeps
    the same images; None where every wave the tile has can be diced."""
    if not (spacing > 0 and math.isfinite(spacing)):
        return None
    cycles = 1.0 / (STEPS_PER_WAVE * spacing)
    if cycles >= resolution / 2:
        return None
    return float(2 ** max(0, round(math.log2(max(cycles, 1.0)))))


def split_paths(value, time, cycles):
    """The long waves' displacement and the shorter waves' normal map (PFM), split at cycles across the tile."""
    stem = '%s.split%g' % (key(value, time), cycles)
    return folder() / (stem + '.coarse.pfm'), folder() / (stem + '.fine.pfm')


def fine_normals(full, coarse, size):
    """The shorter waves as a tangent-space normal map, 0 to 1 (U, V, the surface's normal): the slope less the long
    waves' slope."""
    out = []
    for (ax, az, _), (bx, bz, _) in zip(full, coarse):
        fx, fz = (ax - bx) / size, (az - bz) / size
        length = math.sqrt(fx * fx + fz * fz + 1.0)
        out.append((0.5 - 0.5 * fx / length, 0.5 - 0.5 * fz / length, 0.5 + 0.5 / length))
    return out


def native_split(value, time, cycles, made, split, path=None):
    """The tile and its split made by modo_ocean.dll; whether they were (False with an older library)."""
    held = library(path)
    if held is None:
        return False
    import ctypes
    try:
        call = held.modo_ocean_tile_split
    except AttributeError:
        return False
    call.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_double), ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
                     ctypes.c_double, ctypes.c_char_p, ctypes.c_char_p]
    call.restype = ctypes.c_int
    numbers = values(value, time)
    array = (ctypes.c_double * len(numbers))(*numbers)
    done = call(int(value['resolution']), array, len(numbers), *(str(p).encode('mbcs') for p in made), float(cycles),
                *(str(p).encode('mbcs') for p in split))
    return done == 0 and all(Path(p).is_file() for p in tuple(made) + tuple(split))


def make_split(value, time, cycles):
    """The long waves' displacement and the shorter waves' normal map, made where they are not on disk yet; their
    paths."""
    if value['resolution'] > PYTHON_LIMIT and library() is None:
        value = dict(value, resolution=PYTHON_LIMIT)
    split = split_paths(value, time, cycles)
    if all(p.is_file() for p in split):
        return used(split)
    _made()
    if native_split(value, time, cycles, paths(value, time), split):
        return split
    value = dict(value, resolution=min(value['resolution'], PYTHON_LIMIT))
    split = split_paths(value, time, cycles)
    if all(p.is_file() for p in split):
        return used(split)
    _, _, full = fields(value, time, slopes=True)
    vectors, _, coarse = fields(value, time, slopes=True, cutoff=cycles)
    write_pfm(split[0], value['resolution'], vectors, 3)
    write_pfm(split[1], value['resolution'], fine_normals(full, coarse, value['size']), 3)
    return split


# The lowest a mirror reflection off the water may point in MoonRay, as the sine of its angle over the world's horizon
# (ModoOceanNormalMap's Horizon): the short waves' normal map tipped some below it, where a real sea has another wave in
# the way and the renderer had the environment's ground, black patches on the water.
HORIZON = 0.02
# How far the short waves tilt MoonRay's normal (ModoOceanNormalMap's Dial): MoonLightIPR displaces its mesh finely near
# the camera and shades only the slope finer than its vertices, where MoonRay has every wave shorter than its dicing as
# the normal map at full strength. Whole, the ripples facing the camera reflected little of the sky and showed the dark
# water beneath: black patches on a tester's sea that MoonLightIPR drew smooth. 0.35 matched it there, but on a second
# sea MoonLightIPR's ripples showed much more; 0.6 is near both, with the Ocean Plane's waves fading out toward the
# horizon (ocean_plane.fade), where the dark speckle was worst.
SHORT_WAVES_DIAL = 0.6


def normal_map_available():
    """Whether the MoonRay runtime has the kit's ModoOceanNormalMap; an older one reads the short waves with MoonRay's
    ImageNormalMap, as before."""
    try:
        from . import native
        return (Path(native.default_runtime()) / 'ModoOceanNormalMap.so').is_file()
    except Exception:
        return False


def split_tile(value, cycles):
    """The split images for the frame being written (made if need be), or for time 0 named only where no scene is
    being written."""
    time = CONTEXT['time']
    if time is None:
        return split_paths(value, 0.0, cycles)
    return make_split(value, time, cycles)


def ocean_tags(materials):
    """The material tags whose graph displaces by an Ocean node: the seas, as spaced and rdla.instanced_resolution
    take them."""
    found = set()
    for tag, material in (materials or {}).items():
        for row in (material.get('material_stack') or [material]) if isinstance(material, dict) else ():
            graph = row.get('node_graph') if isinstance(row, dict) else None
            if graph and graph.get('displacement') and any(n.get('type') == 'ocean' for n in (graph.get('nodes') or {}).values()):
                found.add(tag)
    return found


def wears_ocean(mesh, materials, tags=None):
    """Whether a mesh wears a sea (ocean_tags): a material of it whose graph displaces by an Ocean node."""
    from . import face_tags
    tags = ocean_tags(materials) if tags is None else tags
    return bool(tags and ({tag if tag in (materials or {}) else '' for tag in face_tags.worn(mesh)} & tags))


def spaced(scene):
    """The scene with each Ocean node told how far apart MoonRay dices the surfaces its material is on, as a fraction
    of a tile (_spacing, which nodes.expand_ocean splits the tile by, cutoff): each surface's mean edge over its mesh
    resolution (the subdivision level's, 2 to the level), the finest of them. A material on an instanced surface, whose
    reference is diced for its nearest placement (rdla.instanced_resolution), is left whole. The scene as it was where
    there is none, or with the MoonRay Source Override (native.ocean_split) off. Its materials are copies where they
    change."""
    import copy
    from . import face_tags, moonlightipr_detail, native
    materials = scene.get('materials') or {}
    wanted = ocean_tags(materials)
    if not wanted or not native.ocean_split():
        return scene
    steps, whole, finer = {}, set(), {}
    for index, mesh in enumerate(scene.get('meshes') or []):
        tags = {tag if tag in materials else '' for tag in face_tags.worn(mesh)} & wanted
        if not tags:
            continue
        if mesh.get('instances'):
            whole |= tags
            continue
        found = uv_metres(mesh)
        try:
            edge = moonlightipr_detail.extent(mesh)[2] * moonlightipr_detail._scale(mesh.get('matrix') or [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])
        except Exception:
            continue
        level = mesh.get('subdivision_level', 3)
        resolution = mesh.get('mesh_resolution')
        if not resolution:
            # Diced finer for its waves where MoonRay dices it by the screen (rdla reads ocean_resolution).
            resolution = ocean_resolution(mesh, 2 ** (level if isinstance(level, int) and 1 <= level <= 5 else 3))
            finer[index] = resolution
        resolution = float(resolution)
        if found is None or not (edge > 0):
            continue
        for tag in tags:
            # A step in metres, and the metres one unit of the surface's U spans (the tile's width once its repeat is
            # known).
            held = steps.get(tag)
            step = edge / resolution
            if held is None or step / found[0] < held[0] / held[1]:
                steps[tag] = (step, found[0])
    steps = {tag: held for tag, held in steps.items() if tag not in whole}
    if not steps:
        return scene
    result = dict(scene, materials=dict(materials))
    meshes = list(scene.get('meshes') or [])
    for index, resolution in finer.items():
        if ({tag if tag in materials else '' for tag in face_tags.worn(meshes[index])} & set(steps)):
            meshes[index] = dict(meshes[index], ocean_resolution=resolution)
    result['meshes'] = meshes
    for tag, (step, metres) in steps.items():
        material = copy.deepcopy(materials[tag])
        for row in material.get('material_stack') or [material]:
            graph = row.get('node_graph') if isinstance(row, dict) else None
            for node in ((graph or {}).get('nodes') or {}).values():
                if node.get('type') != 'ocean':
                    continue
                repeat = (node.get('parameters') or {}).get('repeat', DEFAULTS['repeat'])
                try:
                    tile = metres / float(repeat[0])
                except (TypeError, ValueError, IndexError, ZeroDivisionError):
                    continue
                if tile > 0 and math.isfinite(tile):
                    node['_spacing'] = step / tile
        result['materials'][tag] = material
    return result


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


def crest_reference(value):
    """The height the crest mask is measured against: twice the sea's height spread (as the wind's tiles are scaled to,
    initial and cascade_values) and half the swell's height."""
    sigma = value['wave_height'] * 0.21 * value['wind_speed'] ** 2 / GRAVITY / 4.0
    reference = 2.0 * sigma + value.get('swell_height', 0.0) / 2.0
    return reference if reference > 0 else 1.0


def crest_path(part, value, time):
    """The crest mask of a tile (part) of the sea (value) at this moment (PFM)."""
    shape = json.dumps([round(crest_reference(value), 6), round(value['crest_start'], 6)])
    return folder() / ('%s.crest%s.pfm' % (key(part, time), hashlib.sha256(shape.encode()).hexdigest()[:8]))


def read_pfm(path):
    """A three-channel PFM as written here or by modo_ocean.dll: its width and its floats (array 'f')."""
    import array
    data = Path(path).read_bytes()
    at, lines = 0, []
    while len(lines) < 3:
        end = data.index(b'\n', at)
        lines.append(data[at:end])
        at = end + 1
    width = int(lines[1].split()[0])
    values = array.array('f')
    values.frombytes(data[at:at + width * width * 12])
    return width, values


def crest_tile(part, value):
    """The crest mask of one of the sea's tiles for the frame being written (made if need be, from its displacement),
    or for time 0 named only where no scene is being written: grey, 0 where the tile's height is below Crest Start's
    share of the sea's (crest_reference), rising to 1 at it. Each tile's own heights against the whole sea's, so the
    long waves' crests glow most and ripples little; nodes.expand_ocean screens the tiles' masks as it does their foam."""
    import array
    time = CONTEXT['time']
    if time is None:
        return crest_path(part, value, 0.0)
    path = crest_path(part, value, time)
    if path.is_file():
        return used([path])[0]
    displacement = make(part, time, CONTEXT['runtime'])[0]
    width, values = read_pfm(displacement)
    inverse, start = 1.0 / crest_reference(value), value['crest_start']
    gain = 1.0 / (1.0 - start)
    mask = array.array('f', [min(1.0, max(0.0, (h * inverse - start) * gain)) for h in values[1::3]])
    out = array.array('f', bytes(len(values) * 4))
    out[0::3] = mask
    out[1::3] = mask
    out[2::3] = mask
    staged = path.with_name(path.name + '.part')
    staged.write_bytes(('PF\n%d %d\n-1.0\n' % (width, width)).encode() + out.tobytes())
    os.replace(staged, path)
    return path


def reach(value):
    """How far the surface can move, for MoonRay's bound padding: four of the heights' spread, and the push sideways."""
    return (value['wave_height'] * 0.21 * value['wind_speed'] ** 2 / GRAVITY + value.get('swell_height', 0.0)) * (1.0 + value['choppiness'])


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
                if (node.get('type') == 'ocean' or (node.get('type') in MASK_NODES and own)) and own.get('fit_to_mesh', DEFAULTS['fit_to_mesh']):
                    return True
        return False
    wanted = {tag for tag, material in materials.items() if isinstance(material, dict) and oceans(material)}
    if not wanted:
        return scene
    spans = {}
    for mesh in scene.get('meshes') or []:
        if mesh.get('_ocean_plane'):
            continue    # its UVs are world tiles, one a unit (ocean_plane): it sizes nothing
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
                if node.get('type') not in ('ocean',) + MASK_NODES or not (params or {}).get('fit_to_mesh', DEFAULTS['fit_to_mesh']):
                    continue
                if node['type'] in MASK_NODES and not params:
                    continue    # it follows the Ocean node, which is fitted
                tiles = float((params or {}).get('tiles_across', DEFAULTS['tiles_across']))
                if tiles > 0 and math.isfinite(tiles) and metres[0] > 0:
                    wide = metres[0] / tiles
                    held = node.setdefault('parameters', {})
                    held['repeat'] = [tiles, max(1e-3, metres[1] / wide)]
                    node['_scale'] = wide / FITTED_SIZE
        result['materials'][tag] = material
    return result
