"""Modo's Photometric lights, drawn with their IES profiles in MoonRay, XPU2 and MoonLightIPR alike.

How Modo's own renderer draws one (read from its renders, tools/probe_cl_ies_lights.py with tools/make_test_ies.py's
files; tools/read_ies_ring.py):
  - a point that shines its Radiance per steradian as a Point light does, times the profile's candela in each direction
    divided by the profile's largest (the file's units and its lumens do nothing);
  - the profile's nadir (vertical angle 0) along the light's own -Z, its C0 plane toward the light's own +Y;
  - the C planes folded about C0-C180: a direction toward +X and one toward -X read the same plane (C90), so a file
    that runs all round (0 to 360) is read in its first half alone, and one of 0 to 90 is mirrored into all four
    quarters; between the angles the file gives, read in straight lines; outside its vertical angles, nothing;
  - the file is read as Modo reads it: the Photometric light's filename channel, a file and no clip.

MoonRay has no light that reads an IES file. The kit gives it one with what all three engines already draw: a SphereLight
the size of a point (the kit's Point light, light_units), and the profile as up to six CookieLightFilter_v2 projectors
at the light's place, each looking along one face of a cube about it with a 90 degree field of view, whose picture is
the profile over that face; outside its face a projector gives black, and a CombineLightFilter adds them up, so that
each direction takes its own face's value (faces the profile leaves dark are left out; a profile on one face needs no
Combine). The pictures are made once for each file and kept in the kit's cache (Light Profiles). MoonRay draws a cookie
rightly in its scalar mode alone (render.scalar_only); XPU2 and MoonLightIPR draw the same filters on the card.

Nothing of Modo here: host.snapshot reads the light; parse, relative and faces are plain, for tests."""
import hashlib
import math
from pathlib import Path

VERSION = 'ies-cube-v4'
# Texels across a face: a degree is about 1.4 texels at the face's middle.
FACE = 128
# Each face as the projector's own axes in the light's frame (rows x, y, z); the projector looks along its -z, so its
# third row is the face's outward direction negated.
FACES = (
    ('nadir', ((1, 0, 0), (0, 1, 0), (0, 0, 1))),        # looks along -Z: the profile's nadir
    ('zenith', ((1, 0, 0), (0, -1, 0), (0, 0, -1))),     # looks along +Z
    ('plus_x', ((0, 0, 1), (0, 1, 0), (-1, 0, 0))),      # looks along +X
    ('minus_x', ((0, 0, -1), (0, 1, 0), (1, 0, 0))),     # looks along -X
    ('plus_y', ((1, 0, 0), (0, 0, 1), (0, -1, 0))),      # looks along +Y
    ('minus_y', ((1, 0, 0), (0, 0, -1), (0, 1, 0))),     # looks along -Y
)
# The projector's lens: a 90 degree field of view (half the film over the focal length is 1).
FOCAL, FILM = 12.0, 24.0


def parse(text):
    """An IES (LM-63) file's photometry: {'vertical': [degrees], 'horizontal': [degrees], 'candela': [[a value for
    each vertical angle] for each horizontal angle]}, the candela multiplied as the file says. ValueError if it is not
    one."""
    lines = text.replace('\r', '\n').split('\n')
    at = next((i for i, line in enumerate(lines) if line.strip().upper().startswith('TILT')), None)
    if at is None:
        raise ValueError('not an IES file: no TILT line')
    numbers = []
    for line in lines[at + 1:]:
        numbers += line.replace(',', ' ').split()
    values = [float(v) for v in numbers]
    tilt = lines[at].split('=', 1)[1].strip().upper() if '=' in lines[at] else 'NONE'
    if tilt == 'INCLUDE':
        # The lamp's tilt table (its geometry, its count and the angles and factors) comes first: Modo's renders do
        # not depend on it for a luminaire hung as photometered, nor does the kit.
        count = int(values[1])
        values = values[2 + 2 * count:]
    if len(values) < 13:
        raise ValueError('not an IES file: too few numbers')
    multiplier = values[2]
    vertical_count, horizontal_count = int(values[3]), int(values[4])
    start = 13
    vertical = values[start:start + vertical_count]
    horizontal = values[start + vertical_count:start + vertical_count + horizontal_count]
    flat = values[start + vertical_count + horizontal_count:start + vertical_count + horizontal_count + vertical_count * horizontal_count]
    if vertical_count < 1 or horizontal_count < 1 or len(flat) != vertical_count * horizontal_count:
        raise ValueError('not an IES file: its table is short')
    candela = [[max(0.0, c * multiplier) for c in flat[h * vertical_count:(h + 1) * vertical_count]] for h in range(horizontal_count)]
    return {'vertical': vertical, 'horizontal': horizontal, 'candela': candela}


def _between(angles, value):
    """(index, fraction) of value in the ascending angles, or None outside them."""
    if len(angles) == 1:
        return (0, 0.0) if abs(value - angles[0]) < 1e-6 else None
    if value < angles[0] - 1e-6 or value > angles[-1] + 1e-6:
        return None
    for i in range(len(angles) - 1):
        if value <= angles[i + 1] + 1e-9:
            span = angles[i + 1] - angles[i]
            return i, (min(max(value - angles[i], 0.0), span) / span) if span > 0 else 0.0
    return len(angles) - 2, 1.0


def folded(profile, h):
    """A C plane's angle (0 to 180, already folded about C0-C180) as the file's horizontal angles hold it."""
    horizontal = profile['horizontal']
    if len(horizontal) == 1:
        return horizontal[0]
    last = horizontal[-1]
    if last <= 90 + 1e-6 and horizontal[0] >= -1e-6:
        # A quadrant: the other three mirrored from it.
        return h if h <= 90 else 180 - h
    if horizontal[0] >= 90 - 1e-6 and last <= 270 + 1e-6:
        # A file of 90 to 270 (bilateral about C90-C270, as some makers write them): read from its own half.
        return 180 - h if h < 90 else h
    return h


def relative(profile, v, h):
    """The candela toward vertical angle v (0 the nadir) and C plane h (degrees, 0 to 180), divided by the file's
    largest: 0 to 1, 0 outside its vertical angles."""
    largest = profile.get('_largest')
    if largest is None:
        largest = profile['_largest'] = max((c for row in profile['candela'] for c in row), default=0.0)
    if largest <= 0:
        return 0.0
    found_v = _between(profile['vertical'], v)
    if found_v is None:
        return 0.0
    found_h = _between(profile['horizontal'], folded(profile, h))
    if found_h is None:
        return 0.0
    (i, a), (j, b) = found_v, found_h
    rows = profile['candela']

    def at(row, column):
        return rows[min(row, len(rows) - 1)][min(column, len(rows[0]) - 1)]
    low = at(j, i) * (1 - a) + at(j, i + 1) * a if a > 0 else at(j, i)
    high = (at(j + 1, i) * (1 - a) + at(j + 1, i + 1) * a if a > 0 else at(j + 1, i)) if b > 0 else low
    return (low * (1 - b) + high * b) / largest


def angles(d):
    """Modo's angles for a direction in the light's own frame: (vertical from the nadir along -Z, the C plane from +Y
    toward either side, folded to 0 to 180), in degrees."""
    x, y, z = d
    length = math.sqrt(x * x + y * y + z * z) or 1e-30
    v = math.degrees(math.acos(max(-1.0, min(1.0, -z / length))))
    h = abs(math.degrees(math.atan2(x, y))) if abs(x) + abs(y) > 1e-12 else 0.0
    return v, h


def face_values(profile, axes, size=FACE):
    """A face's picture, top row first: for each texel the profile toward its middle. A cookie projector lays its
    picture as an image is seen: across it along the projector's +x, up it along its +y (MoonRay's render of a cookie
    whose picture is tools/make_uv_code_image.py's)."""
    values = []
    for row in range(size):
        t = 1.0 - (row + .5) / size
        for column in range(size):
            s = (column + .5) / size
            # The point on the projector's image plane, in its own frame (it looks along -z), into the light's.
            p = (2 * s - 1, 2 * t - 1, -1.0)
            d = [p[0] * axes[0][k] + p[1] * axes[1][k] + p[2] * axes[2][k] for k in range(3)]
            values.append(relative(profile, *angles(d)))
    return values


def faces(profile, size=FACE):
    """[(face name, its axes in the light's frame, its values top row first)] for each face the profile lights."""
    found = []
    for name, axes in FACES:
        values = face_values(profile, axes, size)
        if max(values) > 0:
            found.append((name, axes, values))
    return found


_HELD = {}


def profile_faces(filename):
    """[(face name, axes, picture path)] for an IES file, made once in the cache (Light Profiles) for each file as it
    stands. ValueError if it cannot be read."""
    path = Path(filename)
    try:
        stat = path.stat()
    except OSError:
        raise ValueError('the IES file %s is missing' % filename)
    key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns, VERSION, FACE)
    if key in _HELD:
        return _HELD[key]
    profile = parse(path.read_text(encoding='latin-1'))
    from .textures import cache_root
    digest = hashlib.sha256(repr(key).encode()).hexdigest()[:32]
    folder = cache_root() / 'Light Profiles' / digest
    folder.mkdir(parents=True, exist_ok=True)
    made = []
    marker = folder / 'faces.txt'
    if marker.is_file():
        names = [n for n in marker.read_text().split() if n]
        axes = dict(FACES)
        made = [(n, axes[n], str(folder / (n + '.exr'))) for n in names if (folder / (n + '.exr')).is_file()]
        if len(made) != len(names):
            made = []
    if not made:
        from .light_images import write_picture
        for name, axes, values in faces(profile):
            target = folder / (name + '.exr')
            write_picture(target, [v for v in values for _ in range(3)], FACE, FACE)
            made.append((name, axes, str(target)))
        marker.write_text(' '.join(n for n, _, _ in made))
    _HELD[key] = made
    return made


def projector_matrix(light_matrix, axes):
    """A face's projector in the world: its axes (the face's, in the light's frame) turned with the light (its axes
    made unit length, its size left out), at the light's place. Row-major 4x4, rows its axes, as the kit's matrices."""
    turn = []
    for row in range(3):
        axis = [float(v) for v in light_matrix[row * 4:row * 4 + 3]]
        length = math.sqrt(sum(v * v for v in axis)) or 1.0
        turn.append([v / length for v in axis])
    out = []
    for row in axes:
        out += [sum(row[k] * turn[k][c] for k in range(3)) for c in range(3)] + [0.0]
    return out + [float(v) for v in light_matrix[12:15]] + [1.0]


def emit(light, name, lines):
    """The light's profile as MoonRay light filters, written to lines: [the filter to name on the light] (one face's
    cookie, or a Combine adding them), or [] where the profile lights nothing."""
    from .rdla import string, matrix
    from .textures import register
    made = profile_faces(light['ies'])
    cookies = []
    for face, axes, picture in made:
        ref = 'CookieLightFilter_v2(%s)' % string('%s/ies/%s' % (name, face))
        lines.append('%s {' % ref)
        for key, value in (('node_xform', matrix(projector_matrix(light['matrix'], axes))), ('texture', string(register(picture).replace('\\', '/'))),
                           ('projector_focal', '%g' % FOCAL), ('projector_film_width_aperture', '%g' % FILM),
                           ('outside_projection', '0'), ('density', '1'), ('gamma', 'Rgb(1, 1, 1)')):
            lines.append('  [%s] = %s,' % (string(key), value))
        lines.append('}')
        cookies.append(ref)
    if len(cookies) < 2:
        return cookies
    combined = 'CombineLightFilter(%s)' % string(name + '/ies')
    lines.append('%s { ["mode"] = 3, ["light_filters"] = {%s} }' % (combined, ', '.join(cookies)))
    return [combined]


def records(light):
    """The light's profile as MoonLightIPR's filter records (entities.filter_records' form): the faces' cookies, added
    up by a Combine where there are more than one. MoonLightIPR reads a cookie's picture from its top row as its t
    grows (its kernel's FILTER_COOKIE), where MoonRay reads it from its bottom row (a cookie of
    tools/make_uv_code_image.py's picture in MoonRay): each face's projector is given to it with its y axis turned
    round, so that it lays the face's picture as MoonRay does."""
    from .entities import cookie_record
    made = profile_faces(light['ies'])
    cookies = []
    for _, axes, picture in made:
        placed = projector_matrix(light['matrix'], axes)
        placed[4:7] = [-v for v in placed[4:7]]
        cookies.append(cookie_record(placed, picture, FOCAL, FILM, 1.0, 1.0, False, 0, False))
    if len(cookies) < 2:
        return cookies
    return [{'kind': 'combine', 'mode': 3, 'children': cookies}]
