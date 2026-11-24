"""The Backplate, a MoonRay item of the kit's own (entity_catalog: BackplateEnvironment, the Backplate environments
Source Override): in one item, the HDRI that lights a scene and the backplate photo shot with it, the way a car is put
on the road it was photographed on.

At each reading of the scene (host.snapshot) the item is made what every engine renders already, so MoonRay, XPU2 and
MoonLightIPR show it alike:
- the HDRI as an environment, lighting the scene, seen by the rays its switches let see it;
- the backplate, thrown by its projection (camera, front, planar, box, cylindrical or spherical) around the scene and
  laid over the HDRI where it reaches: an environment for reflections and refractions (and lighting, where asked);
- a card only the camera sees, standing behind everything and filling the view, wearing the photo pixel for pixel;
- a ground (its own, at the item's height, or a mesh of the scene) wearing the photo by the same projection, so the car's
  reflection of the road is the road; and, as a shadow catcher, showing the camera the photo darkened by the shadows on it
  (MoonRay's ShadowCatcher, tools/port_shadow_catcher.py). Where an engine has no shadow catcher, the ground is a matt
  surface wearing the photo, lit and shadowed by the scene.

Projections that depend on where the camera stands (camera, front) give the ground's corners their places in the photo:
the kit's own ground is a fine grid, so that the photo lies on it without the bend linear UVs give over a large face.
"""
import hashlib
import math
import os
import struct
import uuid
from pathlib import Path

CLASS = 'BackplateEnvironment'
PROJECTIONS = ('camera', 'front', 'planar', 'spherical', 'cylindrical', 'box')
# What becomes of the scene's Modo environments (Other Environments).
OTHERS = ('replace', 'override', 'add')
MATERIAL_PREFIX = '|backplate|'
# The kit's ground: cells each way (a 20 m ground in cells of 15 cm). Fine enough that a camera projection's bend across a
# cell, which UVs straight across it cannot follow, stays under a pixel at the ground's near edge in a 1920-wide frame.
GROUND_CELLS = int(os.environ.get('MOONRAY_MODO_BACKPLATE_CELLS') or 128)
# The reflections' environment: the photo laid over the HDRI in a latitude-longitude picture this wide.
ENVIRONMENT_WIDTH = int(os.environ.get('MOONRAY_MODO_BACKPLATE_WIDTH') or 2048)
# How far the camera's card stands: short of MoonRay's camera far clip (10000, which the kit leaves as it is), behind
# anything a scene holds.
CARD_DISTANCE = 9000.0
IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


# ---- Maths --------------------------------------------------------------------------------------------------------
# Matrices are Modo's and the kit's: 16 numbers, rows of the axes then the place (translation at 12, 13, 14); a point p
# goes to p x M.

def transform(matrix, point):
    x, y, z = point
    m = matrix
    return [x * m[0] + y * m[4] + z * m[8] + m[12], x * m[1] + y * m[5] + z * m[9] + m[13], x * m[2] + y * m[6] + z * m[10] + m[14]]


def turn(matrix, direction):
    x, y, z = direction
    m = matrix
    return [x * m[0] + y * m[4] + z * m[8], x * m[1] + y * m[5] + z * m[9], x * m[2] + y * m[6] + z * m[10]]


def inverse(matrix):
    """The inverse of an affine matrix (axes and place)."""
    a = [[float(matrix[r * 4 + c]) for c in range(3)] for r in range(3)]
    det = (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1]) - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
           + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))
    if abs(det) < 1e-12:
        raise ValueError('the placement cannot be undone (scaled to nothing)')
    inv = [[(a[(c + 1) % 3][(r + 1) % 3] * a[(c + 2) % 3][(r + 2) % 3] - a[(c + 1) % 3][(r + 2) % 3] * a[(c + 2) % 3][(r + 1) % 3]) / det
            for c in range(3)] for r in range(3)]
    t = [float(matrix[12]), float(matrix[13]), float(matrix[14])]
    place = [-(t[0] * inv[0][c] + t[1] * inv[1][c] + t[2] * inv[2][c]) for c in range(3)]
    return inv[0] + [0.0] + inv[1] + [0.0] + inv[2] + [0.0] + place + [1.0]


def unit(v):
    length = math.sqrt(sum(c * c for c in v)) or 1.0
    return [c / length for c in v]


class Projector:
    """Where a point of the world, or a direction, falls in the photo, by one projection: (u, v), 0 to 1 from the
    photo's lower left, or None where it falls outside (camera and front). camera is the snapshot's camera (focal_mm,
    film_mm, film_offset, pixel_aspect, matrix, projection); aspect the picture's width over height; place the item's
    world matrix; size the projection's size (Ground Size)."""

    def __init__(self, projection, camera=None, aspect=16 / 9.0, place=None, size=20.0):
        if projection not in PROJECTIONS:
            raise ValueError('unknown projection ' + str(projection))
        self.projection, self.size = projection, max(float(size), 1e-6)
        self.place = list(place or IDENTITY)
        self.local = inverse(self.place)
        if projection in ('camera', 'front'):
            if not camera:
                raise ValueError('the projection needs a camera')
            self.camera = camera
            self.view = inverse(camera.get('matrix') or IDENTITY)
            self.origin = [float(v) for v in (camera.get('matrix') or IDENTITY)[12:15]]
            self.focal = max(float(camera.get('focal_mm') or 50.0), 1e-6)
            self.film = max(float(camera.get('film_mm') or 36.0), 1e-6)
            pixel = max(float(camera.get('pixel_aspect') or 1.0), 1e-6)
            self.film_height = self.film / max(float(aspect), 1e-6) / pixel
            offset = camera.get('film_offset') or [0.0, 0.0]
            # host.camera's offsets are in millimetres, the vertical one times the pixel aspect (camera.offsets).
            self.offset = [float(offset[0]), float(offset[1]) / pixel]
            self.ortho = camera.get('projection') == 'ortho'
            self.ortho_width = float(camera.get('ortho_width') or 1.0)

    def point(self, p, clip=True):
        """clip: None outside the photo (camera, front); else the place beyond its edge, as a texture repeats."""
        if self.projection in ('camera', 'front'):
            x, y, z = transform(self.view, p)
            if self.ortho:
                u = x / self.ortho_width + 0.5
                v = y / (self.ortho_width * self.film_height / self.film) + 0.5
            else:
                if z > -1e-6:
                    return None          # behind the camera
                u = (x / -z * self.focal - self.offset[0]) / self.film + 0.5
                v = (y / -z * self.focal - self.offset[1]) / self.film_height + 0.5
            return (u, v) if not clip or (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0) else None
        x, y, z = [c / self.size for c in transform(self.local, p)]
        if self.projection == 'planar':
            # Seen from above, as a ground is: X across, -Z up the photo.
            return (x + 0.5, -z + 0.5)
        if self.projection == 'spherical':
            d = unit([x, y, z])
            return (0.5 + math.atan2(d[0], -d[2]) / (2 * math.pi), 0.5 + math.asin(max(-1.0, min(1.0, d[1]))) / math.pi)
        if self.projection == 'cylindrical':
            return (0.5 + math.atan2(x, -z) / (2 * math.pi), y + 0.5)
        # Box: the photo whole on each of the box's six sides, the side the point lies farthest toward.
        ax, ay, az = abs(x), abs(y), abs(z)
        if ay >= ax and ay >= az:
            return (x + 0.5, (-z if y > 0 else z) + 0.5)
        if ax >= az:
            return ((z if x > 0 else -z) + 0.5, y + 0.5)
        return ((-x if z > 0 else x) + 0.5, y + 0.5)

    def direction(self, d):
        """A direction seen from the middle of things: from the camera for camera and front (the photo's vanishing
        points), from the item for the others, out to the size of the projection."""
        if self.projection in ('camera', 'front'):
            if self.ortho:
                return None
            far = [o + c * 1e6 for o, c in zip(self.origin, unit(d))]
            return self.point(far)
        centre = self.place[12:15]
        return self.point([c + v * self.size * 0.5 for c, v in zip(centre, unit(d))])


# ---- Pictures -----------------------------------------------------------------------------------------------------

def latlong_direction(x, y, width, height):
    """The direction of a latitude-longitude texel (x across, y down from the top) as Modo's spherical projection lays
    an image, as the HDRI's own file is; environments.emit then turns both alike for MoonRay (the entry's matrix)."""
    phi = (x + 0.5) / width * 2 * math.pi
    theta = (y + 0.5) / height * math.pi
    s = math.sin(theta)
    # Modo's spherical projection: u = 0.5 at -Z, growing toward +X; v = 1 at the zenith.
    return [math.sin(phi - math.pi) * s, math.cos(theta), -math.cos(phi - math.pi) * s]


def st_map(projector, width, height):
    """The st map of a latitude-longitude picture: for each texel, top row first, where in the photo its direction falls
    (s, t from the photo's lower left) and whether it does (third channel 1, else 0)."""
    rows = []
    for y in range(height):
        row = []
        for x in range(width):
            hit = projector.direction(latlong_direction(x, y, width, height))
            row += (hit[0], hit[1], 1.0) if hit else (0.0, 0.0, 0.0)
        rows.append(row)
    return rows


def write_pfm(path, rows, width, height, channels=3):
    """rows top first, each width x channels floats."""
    with open(path, 'wb') as out:
        out.write(b'PF\n' if channels == 3 else b'Pf\n')
        out.write(('%d %d\n-1.0\n' % (width, height)).encode('ascii'))
        for row in reversed(rows):
            out.write(struct.pack('<%df' % (width * channels), *row))


def _cache(kind, key, suffix):
    from .cache_folder import root
    folder = root() / 'Backplates'
    folder.mkdir(parents=True, exist_ok=True)
    return folder / (hashlib.sha256(repr((kind, key)).encode('utf-8')).hexdigest() + suffix)


def _run(args):
    from . import native
    import subprocess
    tool = native.tool('oiiotool.exe')
    done = subprocess.run([str(tool)] + [str(a) for a in args], env=native.environment(tool.parent), stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, timeout=600, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if done.returncode:
        raise ValueError('the image tool could not make the backplate: ' + done.stdout[-400:])


def _stamp(path):
    stat = Path(path).stat()
    return (str(Path(path).resolve()), stat.st_size, stat.st_mtime_ns)


def _linear(path):
    """oiiotool's arguments turning a photo's colours linear, as the kit reads an sRGB image."""
    return [] if Path(path).suffix.lower() in ('.exr', '.hdr', '.tx', '.pfm') else ['--colorconvert', 'sRGB', 'linear']


def reflection_environment(projector, plate, hdri, hdri_rotation, plate_intensity, hdri_intensity, key):
    """The photo laid over the HDRI where it reaches, as a latitude-longitude EXR (ENVIRONMENT_WIDTH wide), made once a
    projection and kept in the cache folder. Where there is no HDRI, black under it."""
    width, height = ENVIRONMENT_WIDTH, ENVIRONMENT_WIDTH // 2
    stamp = (_stamp(plate), _stamp(hdri) if hdri else None, round(float(hdri_rotation), 6), float(plate_intensity),
             float(hdri_intensity), width, key, 'v1')
    target = _cache('reflection', stamp, '.exr')
    if target.is_file() and target.stat().st_size:
        return target
    staged = target.with_name(target.stem + '-' + uuid.uuid4().hex)
    st, made = Path(str(staged) + '-st.pfm'), Path(str(staged) + '.exr')
    try:
        # From the camera, where the photo falls changes smoothly with the direction: worked out at a quarter of the size
        # and enlarged by the image tool (a pass of the full picture took 16 s in Python at 2048 wide, at every move of a
        # Front projection's camera). The other projections' seams (a wrap, a box's sides) would smear so: full size,
        # once for a placement.
        small = 4 if projector.projection in ('camera', 'front') else 1
        write_pfm(st, st_map(projector, width // small, height // small), width // small, height // small)
        warp = [st] + (['--resize:filter=triangle', '%dx%d' % (width, height)] if small > 1 else [])
        args = []
        if hdri:
            # The HDRI under it, turned as its environment is: a turn of the item by a positive angle (about Y, as
            # Modo turns) carries the image's middle toward -X, so its pixels move left.
            shift = int(round(-float(hdri_rotation) / 360.0 * width)) % width
            args += [hdri] + _linear(hdri) + ['--ch', 'R,G,B', '--resize', '%dx%d' % (width, height),
                                               '--mulc', '%g,%g,%g' % ((hdri_intensity,) * 3)]
            if shift:
                args += ['--cshift', '+%d+0' % shift]
            args += ['--ch', 'R,G,B,A=1.0']
        # The photo where it reaches, its st map's third channel the reach (as alpha), laid over the HDRI.
        # The image tool's st_warp makes a picture the size of the photo it warps, not of the st map: the photo is brought
        # to the environment's size first (its coordinates are shares of it, so nothing moves).
        args += [plate] + _linear(plate) + ['--ch', 'R,G,B', '--resize', '%dx%d' % (width, height),
                                            '--mulc', '%g,%g,%g' % ((plate_intensity,) * 3)]
        args += warp + ['--st_warp:filter=lanczos3:flip_t=1']
        args += warp + ['--ch', 'A=B', '--chappend', '--chnames', 'R,G,B,A', '--premult']
        if hdri:
            # The image tool's --over lays the image read first over the one read after it: the photo is brought before
            # the HDRI for it.
            args += ['--swap', '--over']
        args += ['--ch', 'R,G,B', '-d', 'float', '-o', made]
        _run(args)
        made.replace(target)
    finally:
        for left in (st, made):
            if left.exists():
                left.unlink()
    return target


# ---- Meshes -------------------------------------------------------------------------------------------------------

def ground(entity, size, cells=None):
    """The kit's ground: a square of cells each way, Size across, flat at the item's height, centred under it, facing up;
    its points in the item's space. (vertices, faces)."""
    cells = max(1, int(cells or GROUND_CELLS))
    half, step = size / 2.0, size / cells
    vertices = [[-half + i * step, 0.0, -half + j * step] for j in range(cells + 1) for i in range(cells + 1)]
    faces = []
    for j in range(cells):
        for i in range(cells):
            a = j * (cells + 1) + i
            # Wound to face up (+Y): MoonRay's faces turn counter-clockwise seen from their front.
            faces.append([a, a + cells + 1, a + cells + 2, a + 1])
    return vertices, faces


def corner_uvs(projector, vertices, faces, matrix):
    """Each face corner's place in the photo, for points given in a mesh's space and its world matrix. Corners outside the photo lie
    beyond its edge, as a texture's do; behind the camera, at its lower left. Across a spherical or cylindrical seam,
    each face is kept whole (its corners on one side of the seam)."""
    world = [transform(matrix, v) for v in vertices]
    uvs = []
    for face in faces:
        held = [projector.point(world[v], clip=False) for v in face]
        held = [h if h else (0.0, 0.0) for h in held]
        if projector.projection in ('spherical', 'cylindrical'):
            first = held[0][0]
            held = [(u + 1.0 if u - first < -0.5 else u - 1.0 if u - first > 0.5 else u, v) for u, v in held]
        uvs += [[u, v] for u, v in held]
    return uvs


def card(camera, aspect, distance):
    """The camera's card: a rectangle filling its view at distance, facing it, its corners the photo's (front
    projection). Points in the world; (vertices, faces, uvs)."""
    focal = max(float(camera.get('focal_mm') or 50.0), 1e-6)
    film = max(float(camera.get('film_mm') or 36.0), 1e-6)
    pixel = max(float(camera.get('pixel_aspect') or 1.0), 1e-6)
    height = film / max(aspect, 1e-6) / pixel
    offset = camera.get('film_offset') or [0.0, 0.0]
    ox, oy = float(offset[0]), float(offset[1]) / pixel
    if camera.get('projection') == 'ortho':
        across = float(camera.get('ortho_width') or 1.0)
        corners = [((u - 0.5) * across, (v - 0.5) * across * height / film) for u, v in ((0, 0), (1, 0), (1, 1), (0, 1))]
    else:
        corners = [(((u - 0.5) * film + ox) / focal * distance, ((v - 0.5) * height + oy) / focal * distance)
                   for u, v in ((0, 0), (1, 0), (1, 1), (0, 1))]
    m = camera.get('matrix') or IDENTITY
    vertices = [transform(m, [x, y, -distance]) for x, y in corners]
    return vertices, [[0, 1, 2, 3]], [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]


def plate_material(plate, emissive, catcher=False):
    """What the ground (matt, the photo its colour; as a shadow catcher, its emission too, which the catcher shows) or
    the card (the photo as its light alone) wears."""
    from . import nodes
    graph = nodes.new('DwaBaseMaterial', {'albedo': [0.0, 0.0, 0.0] if emissive else [1.0, 1.0, 1.0], 'roughness': 1.0,
                                          'specular': 0.0, 'metallic': 0.0})
    # MoonRay's ImageMap of the photo on the mesh's own UVs, its sRGB read as the file says (gamma auto).
    graph['nodes']['plate'] = {'type': 'ImageMap', 'position': [-300, 0], 'inputs': {},
                               'parameters': {'texture': str(plate), 'gamma': 2, 'wrap_around': False}}
    graph['nodes']['surface']['inputs'].update({'emission' if emissive else 'albedo': 'plate'})
    if catcher:
        graph['nodes']['surface']['inputs']['emission'] = 'plate'
    if emissive or catcher:
        # DwaBase shows no emission unless told to.
        graph['nodes']['surface'].setdefault('parameters', {}).update(emission=[1.0, 1.0, 1.0], show_emission=True)
    return {'native_shader': 'DwaBaseMaterial', 'native_parameters': {}, 'node_graph': graph, 'node_override': True,
            'color': [0.5, 0.5, 0.5], 'roughness': 1.0}


# ---- The scene ----------------------------------------------------------------------------------------------------

def marked(meshes):
    """The meshes made shadow catchers on their MoonRay Object tab (options.OBJECT shadow_catcher), not yet given their
    catcher's material; not the Backplate's own, nor instanced ones (whose material their reference holds)."""
    return [mesh for mesh in meshes if (mesh.get('geometry_settings') or {}).get('shadow_catcher') and not mesh.get('_backplate')
            and not mesh.get('_catcher_done') and 'instances' not in mesh and mesh.get('faces')]


def strength_of(mesh):
    try:
        return min(max(float((mesh.get('geometry_settings') or {}).get('shadow_strength', 1.0)), 0.0), 1.0)
    except (TypeError, ValueError):
        return 1.0


def catchers(result, warnings):
    """Objects made shadow catchers where no Backplate gives them a photo (apply has given those it does): each left out
    of the picture, its alpha holding the shadows on it alone, to lay over a photo in compositing. Where MoonRay has no
    shadow catcher, or the Source Override is off, they render as they are, with a notice."""
    from . import native
    meshes = marked(result.get('meshes') or [])
    if not meshes:
        return result
    if not native.shadow_catcher_runtime():
        warnings.append('Shadow catchers render as plain surfaces: %s. Turn on Backplate environments and shadow catchers in '
                        'MoonRay Source Overrides, with a MoonRay that has them.' % ', '.join(sorted({m.get('name', '') for m in meshes})))
        return result
    materials = result.setdefault('materials', {})
    from . import nodes
    for mesh in meshes:
        strength = strength_of(mesh)
        tag = '%smatte/%g' % (MATERIAL_PREFIX, strength)
        if tag not in materials:
            graph = nodes.new('DwaBaseMaterial', {'albedo': [0.5, 0.5, 0.5], 'roughness': 1.0, 'specular': 0.0, 'metallic': 0.0})
            materials[tag] = {'native_shader': 'DwaBaseMaterial', 'native_parameters': {}, 'node_graph': graph, 'node_override': True,
                              'color': [0.5, 0.5, 0.5], 'roughness': 1.0, 'shadow_catcher': {'strength': strength, 'matte': True}}
        mesh['material'] = tag
        mesh.pop('face_materials', None)
        mesh['_catcher_done'] = True
    return result

def _path(text, warnings, name, what):
    if not text:
        return None
    path = Path(str(text)).expanduser()
    if not path.is_file():
        warnings.append('Backplate %s: its %s %s is not found.' % (name, what, path))
        return None
    return path


def environment_entries(entity, value, plate, hdri, projector, warnings):
    """The environments a Backplate gives (environments.collect's entries), top first."""
    name = entity.get('name', 'Backplate')
    rotation = float(value('hdri_rotation') or 0.0)
    found = []
    if plate:
        try:
            made = reflection_environment(projector, plate, hdri, rotation, float(value('plate_intensity')),
                                          float(value('hdri_intensity')), (projector.projection, entity.get('_projection_key')))
        except (OSError, ValueError) as exc:
            warnings.append('Backplate %s: the reflections of its backplate could not be made (%s).' % (name, exc))
        else:
            stat = made.stat()
            # Laid over the HDRI and turned with it, in the space of Modo's spherical projection (latlong_direction):
            # placed at rest, as an unturned HDRI is, so that emit turns it as Modo's images are turned for MoonRay.
            found.append({'identity': entity.get('identity', '') + '/plate', 'name': name + ' backplate', 'kind': 'image',
                          'matrix': list(IDENTITY),
                          'intensity': 1.0, 'path': str(made), 'mtime': stat.st_mtime_ns, 'size': stat.st_size, 'srgb': False,
                          'color_space': 'linear', 'effect': 'envColor', 'opacity': 1, 'blend': 'normal', 'invert': False,
                          'camera': False, 'indirect': bool(value('plate_lighting')), 'indirect_seen': bool(value('plate_lighting')),
                          'reflection': bool(value('plate_reflection')), 'refraction': bool(value('plate_refraction')), 'backplate': True})
    if hdri:
        angle = math.radians(rotation)
        c, s = math.cos(angle), math.sin(angle)
        stat = hdri.stat()
        found.append({'identity': entity.get('identity', '') + '/hdri', 'name': name + ' HDRI', 'kind': 'image',
                      'intensity': float(value('hdri_intensity')), 'path': str(hdri.resolve()), 'mtime': stat.st_mtime_ns,
                      'size': stat.st_size, 'srgb': hdri.suffix.lower() not in ('.exr', '.hdr', '.tx'), 'color_space': '(default)',
                      'effect': 'envColor', 'opacity': 1, 'blend': 'normal', 'invert': False,
                      'matrix': [c, 0, -s, 0, 0, 1, 0, 0, s, 0, c, 0, 0, 0, 0, 1],
                      'camera': bool(value('hdri_camera')), 'indirect': bool(value('hdri_lighting')), 'indirect_seen': bool(value('hdri_lighting')),
                      'reflection': bool(value('hdri_reflection')), 'refraction': bool(value('hdri_refraction')), 'backplate': True})
    return found


def apply(result, warnings, cameras=None):
    """The scene read (host.snapshot) with each Backplate item made its environments, card and ground, and taken out of
    its MoonRay items, which no engine has a class for. cameras: the scene's cameras by name (host.backplate_cameras),
    for a projection camera other than the render camera. Left out, with a notice, where its Source Override is off."""
    from . import entities, native
    from .environments import occlude
    if 'meshes' in result:
        result['meshes'] = [mesh for mesh in result['meshes'] if not mesh.get('_backplate')]
    items = [e for e in result.get('entities') or [] if e.get('class') == CLASS]
    if not items:
        return result
    result['entities'] = [e for e in result['entities'] if e.get('class') != CLASS]
    if not native.backplate():
        warnings.append('Backplate is left out: turn on Backplate environments and shadow catchers, in MoonRay Source Overrides.')
        return result
    if len(items) > 1:
        warnings.append('Only one Backplate renders at a time: %s is used.' % items[0].get('name', ''))
    entity = items[0]
    name = entity.get('name', 'Backplate')

    def value(key):
        return entities.value(entity, key)
    camera = result.get('camera') or {}
    aspect = float(result.get('width') or 16) / float(result.get('height') or 9)
    kind = PROJECTIONS[min(max(int(value('projection') or 0), 0), len(PROJECTIONS) - 1)]
    thrower = camera
    if kind == 'camera' and value('projection_camera'):
        thrower = (cameras or {}).get(str(value('projection_camera')))
        if not thrower:
            warnings.append('Backplate %s: no camera is named %s; the backplate is thrown from the render camera.'
                            % (name, value('projection_camera')))
            thrower = camera
    size = max(float(value('ground_size') or 20.0), 1e-3)
    place = entity.get('matrix') or IDENTITY
    try:
        projector = Projector(kind, thrower, aspect, place, size)
    except ValueError as exc:
        warnings.append('Backplate %s is left out: %s.' % (name, exc))
        return result
    entity = dict(entity, _projection_key=(kind, [round(float(v), 6) for v in (thrower.get('matrix') or IDENTITY)],
                                           thrower.get('focal_mm'), thrower.get('film_mm'), str(thrower.get('film_offset')),
                                           [round(float(v), 6) for v in place], size, round(aspect, 6)))
    plate = _path(value('plate'), warnings, name, 'backplate image')
    hdri = _path(value('hdri'), warnings, name, 'HDRI')
    shows = bool(value('catcher_shows_plate'))

    # Environments: the Backplate's in place of the scene's (Replace), over them with each ray seeing the topmost it is
    # let see (Override), or added to them (Add). The camera background override (backdrop) stays in every case.
    own = environment_entries(entity, value, plate, hdri, projector, warnings)
    kept = list(result.get('environments') or [])
    others = OTHERS[min(max(int(value('other_environments') or 0), 0), len(OTHERS) - 1)]
    if others == 'replace':
        kept = [e for e in kept if e.get('backdrop')]
    result['environments'] = occlude(own + kept) if others == 'override' else own + kept

    materials = result.setdefault('materials', {})
    meshes = result.setdefault('meshes', [])
    if plate:
        # The backdrop: a plane filling the camera's view, wearing the photo as its own light, seen by the camera and,
        # where asked, through glass (refractions), from where it stands: behind everything (Backdrop Distance 0), or
        # nearer, as LightWave's backdrop plane, so that what is seen through a car's windows lines up with the photo.
        seen, through = shows and bool(value('plate_camera')), bool(value('backdrop_refraction'))
        if seen or through:
            distance = float(value('backdrop_distance') or 0.0)
            vertices, faces, uvs = card(camera, aspect, distance if distance > 0 else CARD_DISTANCE)
            tag = MATERIAL_PREFIX + 'card/' + str(entity.get('identity', ''))
            materials[tag] = plate_material(plate, emissive=True)
            meshes.append({'name': name + ' card', 'identity': str(entity.get('identity', '')) + '/card', 'vertices': vertices,
                           'faces': faces, 'uvs': uvs, 'material': tag, 'smooth': False, 'matrix': list(IDENTITY),
                           'visibility': [seen, False, False, through, False, False], '_backplate': True})
        tag = MATERIAL_PREFIX + 'ground/' + str(entity.get('identity', ''))
        # The ground wears the photo as its colour, lit as any surface where an engine has no shadow catcher; and as its
        # emission, which a shadow catcher shows (tools/port_shadow_catcher.py).
        catching = bool(value('shadow_catcher')) and native.shadow_catcher_runtime()
        if value('shadow_catcher') and not catching:
            warnings.append('Backplate %s: this MoonRay has no shadow catcher; its ground is lit as any surface.' % name)
        materials[tag] = plate_material(plate, emissive=False, catcher=catching)
        if catching:
            # Left out of the picture as a matte: the alpha holds the shadows alone, to be laid over the photo.
            materials[tag]['shadow_catcher'] = {'strength': min(max(float(value('shadow_strength')), 0.0), 1.0), 'matte': not shows}
        grounds = []
        if value('ground'):
            vertices, faces = ground(entity, size)
            lifted = [float(v) for v in place]
            grounds.append({'name': name + ' ground', 'identity': str(entity.get('identity', '')) + '/ground',
                            'vertices': vertices, 'faces': faces, 'material': tag, 'smooth': True, 'matrix': lifted, '_backplate': True})
            meshes.append(grounds[-1])
        chosen = str(value('ground_mesh') or '').strip()
        if chosen:
            found = [mesh for mesh in meshes if mesh.get('name') == chosen and not mesh.get('_backplate')]
            if not found:
                warnings.append('Backplate %s: no mesh is named %s to be its ground.' % (name, chosen))
            for mesh in found:
                if 'instances' in mesh:
                    warnings.append('Backplate %s: %s is instanced and cannot be its ground.' % (name, chosen))
                    continue
                mesh['material'] = tag
                mesh.pop('face_materials', None)
                mesh.pop('uv_sets', None)
                grounds.append(mesh)
        # Objects made shadow catchers (MoonRay Object tab) wear the photo too, each with its own Shadow Strength.
        for mesh in marked(meshes):
            own = '%s|%s' % (tag, mesh.get('identity', ''))
            materials[own] = dict(materials[tag])
            if catching:
                materials[own]['shadow_catcher'] = dict(materials[tag].get('shadow_catcher') or {'matte': not shows},
                                                        strength=strength_of(mesh))
            mesh['material'] = own
            mesh.pop('face_materials', None)
            mesh.pop('uv_sets', None)
            mesh['_catcher_done'] = True
            grounds.append(mesh)
        for mesh in grounds:
            mesh['uvs'] = corner_uvs(projector, mesh['vertices'], mesh['faces'], mesh.get('matrix') or IDENTITY)
    elif value('shadow_catcher') and value('ground'):
        warnings.append('Backplate %s has no backplate image: its ground is left out.' % name)
    return result
