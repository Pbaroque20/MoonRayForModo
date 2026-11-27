"""Modo's Blob and Sprite items, made from their particles for MoonRay, XPU2 and MoonLightIPR.

A Blob or a Sprite has a Particle Source (volume.particle): a mesh's points, a particle simulation, a Surface Generator,
anything Modo makes particles of. At each reading of the scene the particles are read as Modo evaluates them at that
moment (the item's particleObj channel; ItemToParticle on its source where that is not set), each placed by its
source's world matrix as Modo's renderer places them (the Blob or Sprite item's own placement plays no part; measured).

A Blob is Modo's metaball surface around its particles: each particle's field (1 - d^2 / R^2)^3 out to its radius R,
summed, the surface where the sum is 1 - Level (measured against Modo's renders, tools/probe_cl_blob_field.py:
the radius of one particle's blob at each Level and the necks between two). Size Random gives each particle a radius
of (1 - Size Random x (1 - its ID)) x Radius, its ID being the particle's own number between 0 and 1, as Modo does; a
particle's Size scales it too. The runtime's modo_particles cuts the field into faces (native-port/modo_particles.cpp)
and the result is a mesh like any other, wearing the Blob's material (its Material channel names the tag), placed in
the world: every engine draws it as it draws a mesh. Its points carry the particles' velocities, by which a moving
blob, rebuilt in each sample, is blurred (motion.apply_motion): the particles' own (a simulation's) or, where they have
none, their move over half a frame. Modo 16.1's renderer gives a Blob no direct light at all (any light, from any side,
its shadows on or off; tools/probe_cl_blob_shading.py), only ambient and indirect light, while a mesh of the same
material beside it is lit and the Blob still casts shadows. A Blob is lit as a mesh is unless its Blob lighting (Light
Links, Emitters and Volumes) asks for Modo's look: then no light but the environment reaches it, the light from other
surfaces still does, and it still casts shadows (blob_lighting).

A Sprite is fog in puffs: each particle a ball of fog of its radius, thickest in the middle as Falloff shapes it and as
dense as Density says, the density in each ball taken from Modo's renders of one puff at each Falloff (SPRITE_TABLES,
tools/fit_sprite_profile.py). The runtime's modo_particles lays the puffs into a VDB file (in the Cache folder) which
MoonRay renders as a VdbVolume, its Scattering the fog's albedo, its Forward Scattering its anisotropy. Slices are how
Modo draws a puff (as so many sheets); they change nothing in its look (measured) and are not used. Modo lights the fog
by its lights alone, never by the environment or Global Illumination, and the fog neither shades the light reaching it
nor casts a shadow: so it is given to MoonRay (sprite_volume, SPRITE_BRIGHTNESS).

A Blob or Sprite on a Particle Simulation has particles once Modo has run the simulation to the frame (played or cached);
until then the reading says so.

What is not followed is said once a reading, in the notices (UNREAD)."""
import hashlib
import math
import os
import struct
import subprocess
import tempfile
import time
import uuid
from array import array
from pathlib import Path

PREFIX = 'modo_particles:'
PROGRAM = 'modo_particles.exe'
IDENTITY = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
KINDS = ('blob', 'sprite')
# What a Blob or Sprite has that is not followed: its channel, the value it rests at, and what it is called.
UNREAD = {'blob': (('stretch', 0.0, 'Stretch'), ('texAmplitude', 0.0, 'Texture Displacement'), ('sizeInput', '', 'Size by a gradient input'),
                   ('dissolve', 0.0, 'Dissolve'), ('useXfrm', 0, 'Use Particle Transform')),
          'sprite': (('stretch', 0.0, 'Stretch'), ('sizeInput', '', 'Size by a gradient input'), ('rgbaInput', '', 'Colour by a gradient input'),
                     ('posOffset', 0.0, 'Position Offset'))}
# The most contributions of a particle to a cell (particles x cells within a radius) one blob or sprite is laid with:
# past it, the cells are made larger. ~2 s on 16 threads.
BUDGET = 3.0e8
# Cells across one particle's blob radius (the blob's own surface, not its field's reach), by its Render Quality.
QUALITY = {'low': 2.5, 'medium': 3.5, 'high': 5.0, 'veryhigh': 8.0, 'ultra': 8.0}
# The most faces a Blob's mesh is to have: past it, the cells are made larger (blob_faces_cell). A blob over 100,000
# particles made 18 million faces at High, 30 s to make and 108 s to write.
FACES = 3.0e6
# Never fewer cells than this across one particle's blob, whatever the faces come to.
FEWEST_ACROSS = 1.5
# Cells across a sprite's radius.
SPRITE_CELLS = 12.0
# A Sprite's fog from its centre (first) to its edge (last), per metre at Density 1, by its Falloff: from Modo's renders
# (tools/fit_sprite_profile.py on test-results/blob-field). Falloff 0 is an even ball; 1 is no fog at all.
SPRITE_TABLES = {
    0.0: [2.0] * 32 + [0.0],
    0.1: [4.0119, 3.5338, 3.1765, 3.0344, 2.8981, 2.8033, 2.6679, 2.6052, 2.5087, 2.4356, 2.3633, 2.2924, 2.2212, 2.143, 2.0647, 1.9796, 1.9013,
          1.808, 1.712, 1.6161, 1.5078, 1.3926, 1.2742, 1.1468, 1.0124, 0.8724, 0.728, 0.582, 0.4365, 0.297, 0.171, 0.0666, 0.0],
    0.25: [5.1213, 4.3861, 3.7103, 3.2944, 3.0171, 2.7557, 2.5709, 2.3878, 2.2319, 2.0851, 1.9445, 1.8116, 1.6871, 1.57, 1.4504, 1.3392, 1.2291,
           1.121, 1.0178, 0.9156, 0.8171, 0.7217, 0.6293, 0.5404, 0.4549, 0.3738, 0.2979, 0.2273, 0.1632, 0.1064, 0.0587, 0.0214, 0.0],
    0.5: [4.97, 4.0271, 3.1579, 2.6417, 2.2648, 1.9886, 1.7518, 1.5593, 1.394, 1.2515, 1.1215, 1.0064, 0.9031, 0.8105, 0.7236, 0.6456, 0.5735,
          0.507, 0.4464, 0.39, 0.3382, 0.2907, 0.2468, 0.2066, 0.1696, 0.1363, 0.1061, 0.0792, 0.0555, 0.0352, 0.0186, 0.0057, 0.0],
    0.75: [3.0939, 2.4301, 1.7892, 1.4185, 1.1665, 0.984, 0.8391, 0.7241, 0.6281, 0.5482, 0.4797, 0.4213, 0.3695, 0.3245, 0.2848, 0.2492, 0.2181,
           0.1897, 0.1646, 0.1417, 0.1213, 0.1028, 0.0861, 0.0712, 0.0577, 0.0457, 0.035, 0.0256, 0.0174, 0.0104, 0.0047, 0.0004, 0.0],
    0.9: [1.3582, 1.0524, 0.7489, 0.578, 0.4656, 0.3844, 0.3224, 0.2743, 0.2346, 0.2022, 0.1749, 0.1518, 0.1318, 0.1147, 0.0997, 0.0866, 0.075,
          0.0647, 0.0557, 0.0475, 0.0403, 0.0338, 0.028, 0.0228, 0.0181, 0.014, 0.0104, 0.0071, 0.0043, 0.0016, 0.0, 0.0, 0.0],
    1.0: [0.0] * 33,
}
# How much brighter Modo draws a Sprite's fog than MoonRay's single scattering of the same albedo, the fog lit as Modo
# lights it (its lights alone, no shadow through the fog: sprite_volume). Measured lit by a sun alone
# (tools/probe_cl_sprite_light.py): Modo's scattered light goes as Scattering x (1 - e^(-depth / 2)) while its alpha is
# 1 - e^(-depth), which MoonRay's fog cannot follow. Over the whole of each, the same albedo needs 6.4 for a lone puff
# (8.0 through its middle), 5.6 for the reference scene's block of 27 and 9 to 10 inside a slab of 1,500: 6 keeps the
# reference scene as it was (where 3 with the fog's shadows matched it) and brings the puff and the slab much nearer
# (they were 4 and 3 times too dark). The fog's albedo is its Scattering times this.
SPRITE_BRIGHTNESS = 6.0
# Answers made this session, by request digest: a blob's mesh lists, a sprite's file.
_MADE = {}
_MADE_MOST = 24


# ---------------------------------------------------------------------------------------------------------------------
# What Modo's settings make, without Modo.

def threshold(level):
    """The field's value at a Blob's surface for its Level (Modo's percent, 0 to 1): 1 - Level, kept off 0 and 1."""
    return min(0.999, max(1e-3, 1.0 - float(level)))


def surface_radius(radius, level):
    """How far from a lone particle its blob's surface is: where (1 - d^2/R^2)^3 is the threshold."""
    return float(radius) * math.sqrt(max(0.0, 1.0 - threshold(level) ** (1.0 / 3.0)))


def radii(radius, size_random, ids, sizes=None):
    """Each particle's radius: the item's Radius, made smaller by up to Size Random by the particle's ID (0 to 1, the
    particle's own number: an ID of 1 keeps the whole radius, 0 takes all of Size Random off), times its Size."""
    radius, size_random = float(radius), min(1.0, max(0.0, float(size_random)))
    made = array('f', (radius * (1.0 - size_random * (1.0 - min(1.0, max(0.0, i)))) for i in ids))
    if sizes is not None:
        made = array('f', (r * max(0.0, s) for r, s in zip(made, sizes)))
    return made


def blob_cell(found_radii, level, quality, count):
    """A blob's cell size: QUALITY cells across the smallest particle's blob, made larger where the particles would lay
    more than BUDGET contributions."""
    if not count:
        return 1.0
    smallest = max(1e-6, min(found_radii))
    mean = max(1e-6, sum(found_radii) / len(found_radii))
    across = QUALITY.get(str(quality).lower(), QUALITY['high'])
    cell = max(1e-6, surface_radius(smallest, level) / across)
    # Each particle reaches 4/3 pi (R / cell)^3 cells.
    least = mean * (4.18879 * count / BUDGET) ** (1.0 / 3.0)
    # At most FACES faces were every particle's blob a ball of its own: 4 pi (r / cell)^2 faces each.
    alone = surface_radius(mean, level) * math.sqrt(12.566 * count / FACES)
    coarsest = surface_radius(smallest, level) / FEWEST_ACROSS
    return max(cell, least, mean / 400.0, min(alone, coarsest))


def finer_cell(cell, faces, wanted_cell):
    """A blob cut at cell came to faces: the cell that brings it to about FACES (faces go as 1 / cell^2), no finer than
    wanted_cell (its Render Quality's) and never coarser than it was."""
    if faces <= 0:
        return cell
    return min(cell, max(wanted_cell, cell * math.sqrt(faces / FACES) * 1.05))


def sprite_cell(found_radii, count):
    if not count:
        return 1.0
    smallest = max(1e-6, min(found_radii))
    mean = max(1e-6, sum(found_radii) / len(found_radii))
    least = mean * (4.18879 * count / BUDGET) ** (1.0 / 3.0)
    return max(smallest / SPRITE_CELLS, least, mean / 400.0)


def sprite_table(falloff):
    """A Sprite's fog from its centre to its edge at Density 1 for its Falloff: the measured tables, between two of them
    in proportion."""
    falloff = min(1.0, max(0.0, float(falloff)))
    keys = sorted(SPRITE_TABLES)
    for low, high in zip(keys, keys[1:]):
        if low <= falloff <= high:
            t = (falloff - low) / (high - low) if high > low else 0.0
            return [a * (1.0 - t) + b * t for a, b in zip(SPRITE_TABLES[low], SPRITE_TABLES[high])]
    return list(SPRITE_TABLES[keys[-1]])


def placed(positions, matrix):
    """Points (a flat run x, y, z ...) through a world matrix (sixteen numbers, basis vectors in rows)."""
    m = [float(v) for v in matrix]
    if m == IDENTITY:
        return array('f', positions)
    out = array('f', bytes(4 * len(positions)))
    for i in range(0, len(positions), 3):
        x, y, z = positions[i], positions[i + 1], positions[i + 2]
        out[i] = x * m[0] + y * m[4] + z * m[8] + m[12]
        out[i + 1] = x * m[1] + y * m[5] + z * m[9] + m[13]
        out[i + 2] = x * m[2] + y * m[6] + z * m[10] + m[14]
    return out


def turned(vectors, matrix):
    """Directions (velocities) through a world matrix, without its move."""
    m = [float(v) for v in matrix]
    out = array('f', bytes(4 * len(vectors)))
    for i in range(0, len(vectors), 3):
        x, y, z = vectors[i], vectors[i + 1], vectors[i + 2]
        out[i] = x * m[0] + y * m[4] + z * m[8]
        out[i + 1] = x * m[1] + y * m[5] + z * m[9]
        out[i + 2] = x * m[2] + y * m[6] + z * m[10]
    return out


def moved(now, later, seconds, ids=None, later_ids=None):
    """Velocities (units a second) of particles at two moments seconds apart: matched one for one where there are as
    many, else by their IDs where those are each a particle's own; None where they cannot be matched, or none moves."""
    if not seconds or not now:
        return None
    if len(now) != len(later):
        if not ids or not later_ids or len(set(ids)) != len(ids) or len(set(later_ids)) != len(later_ids):
            return None
        where = {value: index for index, value in enumerate(later_ids)}
        matched = array('f')
        for index, value in enumerate(ids):
            k = where.get(value)
            matched.extend(later[3 * k:3 * k + 3] if k is not None else now[3 * index:3 * index + 3])
        later = matched
    speed = array('f', ((b - a) / seconds for a, b in zip(now, later)))
    return speed if any(speed) else None


def request(mode, positions, found_radii, weights, cell, level=0.5, table=(), velocities=None):
    """What modo_particles is asked (native-port/modo_particles.cpp, MPR1)."""
    count = len(found_radii)
    flags = 1 if velocities is not None else 0
    head = b'MPR1' + struct.pack('<3I2fI', mode, count, flags, float(level), float(cell), len(table)) + array('f', table).tobytes()
    width = 8 if velocities is not None else 5
    body = array('f', bytes(4 * width * count))
    body[0::width] = array('f', positions[0::3])
    body[1::width] = array('f', positions[1::3])
    body[2::width] = array('f', positions[2::3])
    body[3::width] = array('f', found_radii)
    body[4::width] = array('f', weights)
    if velocities is not None:
        body[5::width] = array('f', velocities[0::3])
        body[6::width] = array('f', velocities[1::3])
        body[7::width] = array('f', velocities[2::3])
    return head + body.tobytes()


def blob_answer(data):
    """A blob's mesh from modo_particles' answer (MPM1): (points, velocities or None, counts, corners), each a run."""
    if len(data) < 24 or data[:4] != b'MPM1':
        raise ValueError('the blob that came back is not a mesh')
    points, faces, corners, flags, _ = struct.unpack_from('<5I', data, 4)
    at = 24

    def run(kind, n):
        nonlocal at
        values = array(kind)
        values.frombytes(data[at:at + 4 * n])
        at += 4 * n
        if len(values) != n:
            raise ValueError('the blob that came back is cut short')
        return values
    position = run('f', 3 * points)
    velocity = run('f', 3 * points) if flags & 1 else None
    counts = run('i', faces)
    indices = run('i', corners)
    return position, velocity, counts, indices


# ---------------------------------------------------------------------------------------------------------------------
# The runtime's program.

def program():
    """modo_particles.exe: named by MOONRAY_MODO_PARTICLES_TOOL (tests), else the runtime's own; None where not there."""
    named = os.environ.get('MOONRAY_MODO_PARTICLES_TOOL', '')
    if named:
        return Path(named) if Path(named).is_file() else None
    try:
        from . import native
        found = Path(native.default_runtime()) / PROGRAM
    except Exception:
        return None
    return found if found.is_file() else None


def run(asked, answer_suffix):
    """modo_particles on a request: the answer's bytes, or a file where answer_suffix is '.vdb' (the file's path)."""
    tool = program()
    if tool is None:
        raise OSError('this runtime has no particle tool (%s): update the runtime' % PROGRAM)
    folder = Path(tempfile.gettempdir())
    name = 'moonray-particles-' + uuid.uuid4().hex
    question, given = folder / (name + '.in'), folder / (name + answer_suffix)
    try:
        from . import native
        question.write_bytes(asked)
        runtime = Path(native.default_runtime() or tool.parent)
        env = native.environment(runtime) if runtime.is_dir() else dict(os.environ)
        env['PATH'] = str(tool.parent) + os.pathsep + env.get('PATH', '')
        done = subprocess.run([str(tool), str(question), str(given)], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=900)
        if done.returncode or not given.is_file():
            raise ValueError(done.stdout.decode(errors='replace').strip()[-300:] or 'the particle tool failed')
        if answer_suffix == '.vdb':
            return given
        return given.read_bytes()
    finally:
        for path in (question,) + (() if answer_suffix == '.vdb' else (given,)):
            try:
                path.unlink()
            except OSError:
                pass


def _remember(key, value):
    if len(_MADE) >= _MADE_MOST:
        _MADE.pop(next(iter(_MADE)))
    _MADE[key] = value
    return value


def blob_made(asked):
    """A blob's mesh for a request: made once (this session, then the Scene cache in the Cache folder) for what it asks."""
    digest = hashlib.sha256(asked).hexdigest()
    if digest in _MADE:
        return digest, _MADE[digest]
    from . import cache_folder
    data = cache_folder.kept('Blobs', ('blob-v1', digest))
    if data is None:
        data = run(asked, '.mpm')
        cache_folder.keep('Blobs', ('blob-v1', digest), data)
    return digest, _remember(digest, blob_answer(data))


# Sprite files kept in the Cache folder; the oldest let go past this many.
SPRITE_FILES = 400


def sprite_made(asked):
    """A sprite's VDB file in the Cache folder (Sprites) for a request, made once for what it asks."""
    digest = hashlib.sha256(asked).hexdigest()
    held = _MADE.get(digest)
    if held and Path(held).is_file():
        return held
    from .cache_folder import root
    folder = root() / 'Sprites'
    target = folder / ('sprite-v1-' + digest[:40] + '.vdb')
    if not target.is_file() or not target.stat().st_size:
        folder.mkdir(parents=True, exist_ok=True)
        made = run(asked, '.vdb')
        try:
            os.replace(made, target)
        except OSError:
            import shutil
            shutil.move(str(made), str(target))
        try:
            files = sorted(folder.glob('sprite-v1-*.vdb'), key=lambda p: p.stat().st_mtime)
            for old in files[:-SPRITE_FILES]:
                old.unlink()
        except OSError:
            pass
    else:
        try:
            os.utime(target)
        except OSError:
            pass
    return _remember(digest, str(target))


# ---------------------------------------------------------------------------------------------------------------------
# Reading Modo.

def _soup():
    import lxifc

    class Soup(lxifc.TriangleSoup):
        """Every particle's numbers, one after another (Modo hands particles over as points of a surface)."""

        def __init__(self, size):
            self.size = size
            self.values = array('f')
            self.count = 0

        def soup_TestBox(self, bbox):
            return True

        def soup_Segment(self, segID, stype):
            return True

        def soup_Vertex(self, vbuf):
            vbuf.setType('f')
            vbuf.setSize(self.size)
            self.values.extend(vbuf.get())
            self.count += 1
            return self.count - 1

        def soup_Polygon(self, v0, v1, v2):
            pass

        def soup_Connect(self, kind):
            pass
    return Soup


def sources(item):
    """The items a Blob or Sprite takes its particles from (Particle Source: the 'particle' graph into it)."""
    try:
        return list(item.itemGraph('particle').reverse())
    except (LookupError, RuntimeError, AttributeError):
        return []


def surface(item, seconds):
    """The particles a Blob or Sprite renders at a moment, as Modo evaluates them: its particleObj channel's object, or
    its source's particles (ItemToParticle); None where it has none."""
    import lx
    scene = lx.object.Scene(item._item.Context())
    chan = lx.object.ChannelRead(scene.Channels(None, float(seconds)))
    raw = lx.object.Item(item._item)
    try:
        value = chan.ValueObj(raw, raw.ChannelLookup('particleObj'))
        reference = lx.object.ValueReference(value)
        if reference.test() and reference.IsSet():
            found = lx.object.TableauSurface(reference.GetObject())
            if found.test():
                return found
    except (LookupError, RuntimeError, AttributeError, TypeError):
        pass
    for source in sources(item):
        try:
            found = lx.object.TableauSurface(lx.service.Particle().ItemToParticle(lx.object.Item(source._item), chan))
            if found.test():
                return found
        except (LookupError, RuntimeError, AttributeError, TypeError):
            continue
    return None


def read(item, seconds):
    """A Blob's or Sprite's particles at a moment: {'positions' (world, a flat run), 'ids', 'sizes', 'velocities' (or
    None)}, the positions placed by the source's world matrix, or None where it has no particles."""
    import lx
    from .host import world_matrix
    found = surface(item, seconds)
    if found is None:
        return None
    kind = lx.symbol.iTBLX_PARTICLES
    have = [found.FeatureByIndex(kind, i) for i in range(found.FeatureCount(kind))]
    if 'pos' not in have:
        return None
    wanted = [name for name in ('pos', 'id', 'size', 'vel', 'dissolve') if name in have]
    vertex = lx.service.Tableau().AllocVertex()
    offsets, at = {}, 0
    for name in wanted:
        vertex.AddFeature(kind, name)
        offsets[name] = at
        at += 3 if name in ('pos', 'vel') else 1
    found.SetVertex(vertex)
    size = vertex.Size()
    soup = _soup()(size)
    found.Sample(((-1e30, -1e30, -1e30), (1e30, 1e30, 1e30)), -1.0, soup)
    values, count = soup.values, soup.count

    def column(name, k=0):
        return values[offsets[name] + k::size] if name in offsets else None
    positions = array('f', bytes(12 * count))
    for k in range(3):
        positions[k::3] = column('pos', k)
    velocities = None
    if 'vel' in offsets:
        velocities = array('f', bytes(12 * count))
        for k in range(3):
            velocities[k::3] = column('vel', k)
    ids = column('id') if 'id' in offsets else array('f', ((i + 0.5) / max(1, count) for i in range(count)))
    sizes = column('size')
    dissolve = column('dissolve')
    if dissolve is not None and any(d >= 0.999 for d in dissolve):
        # Particles dissolved whole are not there.
        keep = [i for i, d in enumerate(dissolve) if d < 0.999]
        positions = array('f', (positions[3 * i + k] for i in keep for k in range(3)))
        ids = array('f', (ids[i] for i in keep))
        sizes = array('f', (sizes[i] for i in keep)) if sizes is not None else None
        velocities = array('f', (velocities[3 * i + k] for i in keep for k in range(3))) if velocities is not None else None
    owners = sources(item)
    if owners:
        try:
            matrix = world_matrix(owners[0], seconds)
            positions = placed(positions, matrix)
            if velocities is not None:
                velocities = turned(velocities, matrix)
        except (LookupError, RuntimeError, AttributeError, TypeError):
            pass
    # features: what Modo hands over for them (a simulation not yet run to this frame gives positions alone, none).
    return {'positions': positions, 'ids': ids, 'sizes': sizes, 'velocities': velocities, 'features': have}


def settings(item, kind):
    """A Blob's or Sprite's channels, by name, with Modo's defaults where one cannot be read."""
    from .host import channel
    defaults = {'radius': 0.1, 'level': 0.5, 'sizeRand': 0.0, 'renderQuality': 'high', 'material': '', 'falloff': 0.5, 'density': 1.0,
                'scattering': 1.0, 'phaseFwd': 0.5, 'dissolve': 0.0}
    held = {}
    for key, default in defaults.items():
        try:
            value = channel(item, key, default)
        except (LookupError, RuntimeError, AttributeError, TypeError):
            value = default
        held[key] = default if value is None else value
    return held


def unread(item, kind):
    """What of a Blob or Sprite is set and not followed, in words."""
    from .host import channel
    found = []
    for key, rest, name in UNREAD.get(kind, ()):
        try:
            value = channel(item, key, rest)
        except (LookupError, RuntimeError, AttributeError, TypeError):
            continue
        if value not in (rest, None) and not (isinstance(rest, float) and abs(float(value) - rest) < 1e-9):
            found.append(name)
    return found


def particle_items(scene):
    """Every Blob and Sprite, and every item their particles come from or hang from (each source's parents): moving
    or editing any of them changes what the particles make (incremental)."""
    held = set()
    for kind in KINDS:
        try:
            items = list(scene.items(kind, superType=False))
        except (LookupError, RuntimeError, AttributeError, TypeError):
            continue
        for item in items:
            held.add(item.id)
            for source in sources(item):
                at = source
                while at is not None:
                    held.add(at.id)
                    at = at.parent
    return held


def velocities_of(item, seconds, held, fps):
    """The particles' velocities: their own where Modo gives them, else their move over half a frame (none where they
    do not move or cannot be matched)."""
    if held.get('velocities') is not None:
        return held['velocities']
    step = 0.5 / max(1e-6, float(fps))
    try:
        later = read(item, seconds + step)
    except (LookupError, RuntimeError, AttributeError, TypeError, ValueError):
        return None
    if later is None:
        return None
    return moved(held['positions'], later['positions'], step, held.get('ids'), later.get('ids'))


def blob_mesh(item, held, values, velocities):
    """A Blob as a mesh of the kit's (as host reads one): its faces from modo_particles."""
    from .rows import Rows, Faces
    count = len(held['ids'])
    found_radii = radii(values['radius'], values['sizeRand'], held['ids'], held.get('sizes'))
    level = threshold(values['level'])
    cell = blob_cell(found_radii, values['level'], values['renderQuality'], count)
    weights = array('f', [1.0]) * count
    asked = request(1, held['positions'], found_radii, weights, cell, level=level, velocities=velocities)
    digest, (points, speed, counts, corners) = blob_made(asked)
    # The faces were counted as though no two blobs met: where they meet, far fewer came, and the blob is cut again finer.
    wanted = surface_radius(max(1e-6, min(found_radii)), values['level']) / QUALITY.get(str(values['renderQuality']).lower(), QUALITY['high'])
    again = finer_cell(cell, len(counts), wanted)
    if again < cell * 0.8:
        cell = again
        asked = request(1, held['positions'], found_radii, weights, cell, level=level, velocities=velocities)
        digest, (points, speed, counts, corners) = blob_made(asked)
    if not counts:
        return None
    tag = str(values.get('material') or '')
    mesh = {'name': item.name, 'identity': PREFIX + 'blob|' + item.id, 'source_item': item.id,
            'vertices': Rows(points, 3, 'blob-points:' + digest), 'faces': Faces(corners, counts, 'blob-faces:' + digest),
            'matrix': list(IDENTITY), 'material': tag, 'uvs': [], 'normals': [], 'uv_sets': {},
            'smooth': True, 'subdivision': False, 'subdivision_level': 1, 'object_override': False, 'geometry_settings': {},
            # Placed anew at every reading, in the world: never moved with an item (incremental.follow_items).
            'volumetric': True, '_particles': 'blob', '_cell': cell}
    if speed is not None:
        mesh['velocities'] = Rows(speed, 3, 'blob-velocities:' + digest)
    return mesh


def sprite_volume(item, held, values, velocities):
    """A Sprite as a VDB volume of the kit's extra geometry (extra_geometry.emit's 'vdb')."""
    count = len(held['ids'])
    found_radii = radii(values['radius'], values.get('sizeRand', 0.0), held['ids'], held.get('sizes'))
    density = max(0.0, float(values['density'])) * max(0.0, 1.0 - float(values.get('dissolve') or 0.0))
    table = sprite_table(values['falloff'])
    if not density or not any(table):
        return None
    cell = sprite_cell(found_radii, count)
    asked = request(2, held['positions'], found_radii, array('f', [density]) * count, cell, table=table, velocities=velocities)
    path = sprite_made(asked)
    scattering = max(0.0, float(values['scattering']))
    # Luminous Density changes nothing in Modo's render of a puff: it gives off no light in the dark and looks the same
    # lit (measured, tools/probe_cl_sprite_light.py lum, lum2): the fog gives off no light of its own.
    return {'kind': 'vdb', 'identity': PREFIX + 'sprite|' + item.id, 'source_item': item.id, 'name': item.name, 'file': path,
            'density_grid': 'density', 'emission_grid': '', 'velocity_grid': 'v' if velocities is not None else '',
            'velocity_scale': 1.0, 'density': 1.0, 'emission': 0.0,
            'anisotropy': min(0.95, max(-0.95, 2.0 * float(values['phaseFwd']) - 1.0)),
            'volume_color': [scattering * SPRITE_BRIGHTNESS] * 3, 'material': str(values.get('material') or ''), 'matrix': list(IDENTITY),
            # Modo's fog is lit by its lights alone, never by the environment, and neither shades the light reaching it
            # nor casts a shadow (measured: tools/probe_cl_sprite_light.py, tools/probe_cl_blob_shading.py).
            'visibility': [True, True, True, True, True, False], 'lit_by_environment': False,
            '_particles': 'sprite'}


def blob_lighting(meshes, production):
    """The production settings (Light Links, Emitters and Volumes) with each Blob set to Modo's lighting ('modo') lit by
    the environments alone: its light links on, every environment checked. A Blob whose own Light Links are on keeps
    them. The settings given are not changed; where nothing is to change they are returned as they are."""
    objects = (production or {}).get('objects', {})
    unlit = {mesh.get('source_item') for mesh in meshes if mesh.get('_particles') == 'blob'
             and (objects.get(mesh.get('source_item')) or {}).get('blob_lighting') == 'modo'
             and not objects[mesh.get('source_item')].get('link_enabled')}
    if not unlit:
        return production
    held = dict(objects)
    for identity in unlit:
        held[identity] = dict(held[identity], link_enabled=True, lights=['__environment__'])
    return dict(production, objects=held)


def tag_materials(scene, result, tags, warnings):
    """The materials of material tags a reading has none for, made as a reading of the scene's own meshes makes them
    (host._snapshot): the Shader Tree's materials for the tag, the base material's beneath. Read as Modo's evaluated
    geometry, a scene's materials are its render cache's stacks (evaluated.assign_materials), named for them, and the
    cache has no Blob surfaces (measured, tools/probe_cl_blob_evaluated.py): a Blob's tag was none of them, so it wore
    whatever the renderer gives a surface of no material."""
    from .host import material_values, image_layers, channel
    from .layers import ordered, material_stack, material_tag
    from .materials import active
    from . import properties
    missing = [tag for tag in dict.fromkeys(tags) if tag not in result.setdefault('materials', {})]
    if not missing:
        return
    found = {}
    for material in reversed(ordered(scene.renderItem)):
        if not properties.is_material(material) or not active(material) or not channel(material, 'enable', 1):
            continue
        try:
            tag = material_tag(material)
        except ValueError:
            continue
        if tag is not None:
            found.setdefault(tag, []).append(material)
    made = {}
    for tag in missing:
        # A tag no group takes wears the base material, as Modo renders it.
        chosen = found.get(tag) or found.get('')
        if not chosen:
            continue
        made[tag] = material_values(chosen[-1], warnings)
        held = made[tag]
        if channel(chosen[-1], 'subsAmt', 0) or held.get('anisotropy', 0) or held.get('sheen', 0) or \
                (channel(chosen[-1], 'tranAmt', 0) and (channel(chosen[-1], 'metallic', 0) or channel(chosen[-1], 'coatAmt', 0))):
            held['shader'] = 'DwaBaseMaterial'
    if not made:
        return
    image_layers(scene, made, warnings)
    for tag, held in made.items():
        chosen = found.get(tag) or found.get('')
        inherited = [m for m in found.get('', []) if m not in chosen] if tag else []
        held['material_stack'] = material_stack(scene, chosen + inherited, warnings, tag)
    result['materials'].update(made)


def apply(scene, result, warnings):
    """Each Blob's mesh and each Sprite's fog added to a reading of the scene (host._snapshot), those of an earlier
    reading it was made from taken out first; and the points of their sources, which Modo does not render, not drawn
    as points (extra_geometry.collect draws a mesh of points alone as points). Said where something cannot be made."""
    from .host import render_visible
    result['meshes'] = [mesh for mesh in result.get('meshes', []) if not str(mesh.get('identity', '')).startswith(PREFIX)]
    extra = [entry for entry in result.get('extra_geometry', []) if not str(entry.get('identity', '')).startswith(PREFIX)]
    found = []
    for kind in KINDS:
        try:
            found += [(kind, item) for item in scene.items(kind, superType=False)]
        except (LookupError, RuntimeError, AttributeError, TypeError):
            continue
    result['extra_geometry'] = extra
    if not found:
        return
    result['particle_items'] = sorted(particle_items(scene))
    fed = {source.id for _, item in found for source in sources(item)}
    try:
        from . import properties
        explicit = properties.scene_settings().get('production', {}).get('objects', {})
    except Exception:
        explicit = {}
    result['extra_geometry'] = [entry for entry in extra if not (entry.get('kind') == 'points' and entry.get('source_item') in fed
                                                                    and not (explicit.get(entry.get('source_item')) or {}).get('points'))]
    import lx
    seconds = float(result.get('time', lx.service.Selection().GetTime()))
    fps = float(result.get('fps') or 24.0)
    for kind, item in found:
        if not render_visible(item):
            continue
        label = 'Blob' if kind == 'blob' else 'Sprite'
        started = time.perf_counter()
        try:
            held = read(item, seconds)
        except (LookupError, RuntimeError, AttributeError, TypeError, ValueError) as exc:
            warnings.append('%s %s: its particles could not be read (%s).' % (label, item.name, exc))
            continue
        if held is None or not len(held['ids']):
            owners = sources(item)
            if not owners:
                warnings.append('%s %s has no Particle Source and renders nothing.' % (label, item.name))
            elif any(owner.type == 'particleSim' for owner in owners) and set((held or {}).get('features') or ['pos']) <= {'pos'}:
                # Modo's simulation gives its particles once it has run up to the frame (its cache): a scene opened and
                # read at a frame without playing or caching it has none, and only positions to give (measured,
                # tools/probe_cl_particle_sim.py); run, it gives ids, velocities and ages too, even before any is born.
                warnings.append('%s %s: its Particle Simulation has no particles at this frame. Play the timeline up to it '
                                'or cache the simulation (Dynamics > Cache Simulation).' % (label, item.name))
            continue
        values = settings(item, kind)
        skipped = unread(item, kind)
        if skipped:
            warnings.append('%s %s: %s %s not followed.' % (label, item.name, ', '.join(skipped), 'is' if len(skipped) == 1 else 'are'))
        try:
            velocities = velocities_of(item, seconds, held, fps)
            took = {'particles': len(held['ids']), 'read': round(time.perf_counter() - started, 3)}
            started = time.perf_counter()
            if kind == 'blob':
                mesh = blob_mesh(item, held, values, velocities)
                if mesh is not None:
                    result['meshes'].append(mesh)
            else:
                volume = sprite_volume(item, held, values, velocities)
                if volume is not None:
                    result['extra_geometry'].append(volume)
            # How long it took (for tests and timings): reading the particles (with their velocities), making the shape.
            took['made'] = round(time.perf_counter() - started, 3)
            result.setdefault('_particle_seconds', {})[item.name] = took
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            warnings.append('%s %s is not rendered: %s' % (label, item.name, exc))
    if result.get('_evaluated_data') is not None:
        # Read as Modo's evaluated geometry, the materials are the render cache's: a Blob's tag is made here.
        try:
            tag_materials(scene, result, [mesh.get('material', '') for mesh in result['meshes'] if mesh.get('_particles')], warnings)
        except (LookupError, RuntimeError, AttributeError, TypeError, ValueError) as exc:
            warnings.append('The material of a Blob could not be read (%s): it renders with the base material.' % exc)
