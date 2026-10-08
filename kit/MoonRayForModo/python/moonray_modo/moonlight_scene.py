"""Pure Python packer for the MoonLightIPR GPU preview. Does not import or change the Modo scene.

MoonLightIPR approximates the scene MoonRay renders: one fixed uber-shader with layered
textures, the environment and lights. Everything it cannot show is reported as a warning,
never silently.
"""
import hashlib
import math
import struct
from array import array
from itertools import chain

IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
# Layout flags; keep in step with moonlight/session/scene_loader.cpp.
MESH_HAS_DATA, MESH_HAS_NORMALS, MESH_HAS_MATERIAL_IDS, MESH_SMOOTH, MESH_HAS_UVS, MESH_MOVES, MESH_SUBDIVIDE = 1, 2, 4, 8, 16, 32, 64
# A subdivision surface is refined in the session, up to this many quads; MoonRay's own limit is finer.
SUBDIVISION_QUADS = 3000000
SCENE_DENOISE, SCENE_WORKING_SPACE, SCENE_MOTION = 1, 2, 4
ENVIRONMENT_ROWS = 64
ENVIRONMENT_IMAGE = (1024, 512)
ENVIRONMENT_BAKE = (256, 128)       # layered environments are composed in Python, pixel by pixel
GRADIENTS = ('constant', 'grad2', 'grad4', 'overcast')
LOCAL_LIGHTS = {'SphereLight': 0, 'RectLight': 1, 'DiskLight': 2, 'SpotLight': 3, 'CylinderLight': 4, 'PortalLight': 5}
MESH_LIGHT = 6
MESH_LIGHT_TRIANGLES = 50000
_packed = {}
_emitters = {}


def finite(values):
    values = [float(v) for v in values]
    if not all(math.isfinite(v) for v in values):
        raise ValueError('Scene contains a non-finite number')
    return values


def unit(values):
    length = math.sqrt(sum(v * v for v in values))
    if not length > 1e-20:
        raise ValueError('Scene contains a zero-length direction')
    return [v / length for v in values]


def transform(matrix):
    """Modo and MoonRay store basis vectors in rows; OptiX wants a row-major 3x4."""
    m = finite(matrix)
    if len(m) != 16:
        raise ValueError('Transform must contain 16 values')
    return [m[0], m[4], m[8], m[12], m[1], m[5], m[9], m[13], m[2], m[6], m[10], m[14]]


def environment_image(item, runtime):
    """Convert a latitude-longitude image once to a linear float file in the working space."""
    import uuid
    from pathlib import Path
    from .moonlight_materials import Compiler, cache_folder, color_space
    from .working_space import TO_AP1, enabled as working_enabled, matrix_argument
    if item['kind'] == 'stack':
        # The plugin composes layered environments and physical skies into one linear image.
        from .environment_layers import texture
        source, space, ocio = Path(texture(item, *ENVIRONMENT_BAKE)), 'linear', None
    else:
        source = Path(item['path'])
        space, ocio = color_space(source, item.get('color_space', ''), item.get('srgb'))
    stat = source.stat()
    working = working_enabled()
    digest = hashlib.sha256(repr((str(source.resolve()), stat.st_size, stat.st_mtime_ns, space, ocio, working, ENVIRONMENT_IMAGE,
                                  'moonlight-env-v2')).encode()).hexdigest()
    target = cache_folder() / (digest + '.pfm')
    if not target.is_file() or not target.stat().st_size:
        compiler = Compiler(runtime)
        steps = ((['--colorconvert', 'sRGB', 'linear'] if space == 'sRGB' else [])
                 + (['--colormatrix', matrix_argument(TO_AP1)] if working else []) + ['--resize', '%dx%d' % ENVIRONMENT_IMAGE])
        if not ocio:
            compiler.convert(source, target, True, steps)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            staged = target.with_name(target.stem + '-' + uuid.uuid4().hex + '.exr')
            try:
                compiler.run(['--colorconfig', ocio[0], str(source), '--colorconvert', space, ocio[2], '-d', 'float', '-o', str(staged)], source.name)
                compiler.convert(staged, target, True, steps)
            finally:
                if staged.exists():
                    staged.unlink()
    return str(target)


def environment_section(scene, environment, warnings, runtime):
    """Pack what lights the scene and what the camera sees behind it.

    Each is a column of rows from zenith to nadir, summing the preview light and every
    constant or gradient environment, plus at most one latitude-longitude image: a picture, or a
    layered environment or physical sky the plugin has composed into one.
    """
    import subprocess
    from .working_space import color as working_color
    from .environments import gradient_color
    # MoonRay does not show the preview environment light to the camera.
    rows = {'lighting': [[max(0.0, float(environment))] * 3 for _ in range(ENVIRONMENT_ROWS)],
            'background': [[0.0] * 3 for _ in range(ENVIRONMENT_ROWS)]}
    images = {'lighting': None, 'background': None}
    for item in scene.get('environments', []):
        intensity = float(item['intensity'])
        targets = [name for name, visible in (('lighting', item.get('indirect', True)), ('background', item.get('camera', True))) if visible]
        if item['kind'] in ('image', 'stack'):
            try:
                matrix = finite(item.get('matrix', IDENTITY))
                # The image's own axes in world space, which the session turns directions into.
                record = (environment_image(item, runtime), intensity, unit(matrix[0:3]) + unit(matrix[4:7]) + unit(matrix[8:11]))
            except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
                warnings.append('MoonLightIPR shows environment %s as uniform grey; its image could not be made (%s).' % (item.get('name', ''), exc))
            else:
                # One image lights the scene and one is seen behind it; any further one falls back to grey.
                fits = [name for name in targets if images[name] is None]
                for name in fits:
                    images[name] = record
                targets = [name for name in targets if name not in fits]
                if not targets:
                    continue
                warnings.append('MoonLightIPR shows one environment image for lighting and one behind the scene; %s is uniform grey where another is in use.' % item.get('name', ''))
        elif item['kind'] not in GRADIENTS:
            warnings.append('MoonLightIPR shows environment %s as uniform grey; MoonRay renders its %s.' % (item.get('name', ''), item['kind']))
        for y in range(ENVIRONMENT_ROWS):
            height = math.cos((y + .5) / ENVIRONMENT_ROWS * math.pi)
            color = working_color(gradient_color(item, height)) if item['kind'] in GRADIENTS else [.5] * 3
            for name in targets:
                for c, v in enumerate(color):
                    rows[name][y][c] += max(0.0, v) * intensity
    parts = [struct.pack('<I', ENVIRONMENT_ROWS)]
    parts += [struct.pack('<%df' % (ENVIRONMENT_ROWS * 3), *chain.from_iterable(rows[name])) for name in ('lighting', 'background')]
    for name in ('lighting', 'background'):
        if images[name] is None:
            parts.append(struct.pack('<I', 0))
            continue
        path = images[name][0].encode('utf-8')
        parts.append(struct.pack('<I', 1) + hashlib.blake2b(path, digest_size=8).digest() + struct.pack('<I', len(path)) + path
                     + struct.pack('<10f', images[name][1], *images[name][2]))
    return parts


FILTER_DECAY, FILTER_RAMP = 0, 1
FILTER_NEAR, FILTER_FAR = 1, 2
FILTER_DIRECTIONAL, FILTER_MIRROR, FILTER_PLACED = 1, 2, 4
RAMP_SAMPLES = 256


def control_filters(settings, light, scene, warnings):
    """The filters set on a Modo light in Lighting controls, in the form entities.filter_records gives."""
    from .entities import inverse_rows
    from .working_space import color as working_color
    records, name = [], light.get('name', '')
    if settings.get('filter_enabled'):
        scale = float(settings.get('filter_intensity', 1)) * 2 ** float(settings.get('filter_exposure', 0))
        records.append({'kind': 'intensity', 'scale': [c * scale for c in working_color(finite(settings.get('filter_color', [1, 1, 1])))]})
    if settings.get('decay_enabled'):
        distances = [float(settings.get(key, default)) for key, default in (('near_start', 0), ('near_end', 0), ('far_start', 10), ('far_end', 20))]
        records.append({'kind': 'decay', 'near': distances[1] > distances[0], 'far': True, 'distances': distances})
    if settings.get('ramp_enabled'):
        begin, end = float(settings.get('ramp_start', 0)), float(settings.get('ramp_end', 10))
        placed = scene.get('scene_references', {}).get(settings.get('filter_locator'), {}).get('matrix') if settings.get('filter_locator') else None
        if end > begin:
            records.append({'kind': 'ramp', 'directional': False, 'mirror': False, 'rows': inverse_rows(placed) if placed else None,
                            'begin': begin, 'end': end, 'intensity': 1.0, 'density': 1.0, 'positions': [0.0, 1.0],
                            'colors': [working_color(finite(settings.get('ramp_color0', [1, 1, 1]))),
                                       working_color(finite(settings.get('ramp_color1', [0, 0, 0])))], 'interpolations': [1, 1]})
    shaping = [label for key, label in (('rod_enabled', 'rod'), ('barn_enabled', 'barn door'), ('cookie_file', 'cookie'), ('filter_vdb', 'VDB')) if settings.get(key)]
    if shaping:
        warnings.append('MoonLightIPR does not apply the %s filter%s on %s.' % (' and '.join(shaping), 's' if len(shaping) > 1 else '', name))
    return records


def packed_filters(records, compiler):
    """Decay and ramp filters as the session reads them; a ramp's colours go into a small image."""
    from .entities import ramp_eval
    parts = []
    for record in records:
        if record['kind'] == 'decay':
            parts.append(struct.pack('<2I4f12fi', FILTER_DECAY, (FILTER_NEAR if record['near'] else 0) | (FILTER_FAR if record['far'] else 0),
                                     *record['distances'], *([0.0] * 12), -1))
        elif record['kind'] == 'ramp':
            # The ramp over its own 0 to 1, which the session stretches from begin to end.
            steps = [i / (RAMP_SAMPLES - 1) for i in range(RAMP_SAMPLES)]
            colors = [ramp_eval(record['positions'], record['colors'], record['interpolations'], x) for x in steps]
            texture = compiler.ramp({'positions': steps, 'colors': colors}, exact=True)
            rows = record['rows'] or [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]]
            flags = ((FILTER_DIRECTIONAL if record['directional'] else 0) | (FILTER_MIRROR if record['mirror'] else 0)
                     | (FILTER_PLACED if record['rows'] else 0))
            parts.append(struct.pack('<2I4f12fi', FILTER_RAMP, flags, record['begin'], record['end'], record['intensity'], record['density'],
                                     *(v for row in rows for v in row), texture))
    return struct.pack('<I', len(parts)) + b''.join(parts)


def lights(scene, warnings, environment=0.0, compiler=None):
    """Return (distant, local) light records, with MoonRay's default normalization applied."""
    import subprocess
    from .working_space import color as working_color
    controls = scene.get('production', {}).get('lights', {})
    distant, local = [], []
    for index, light in enumerate(scene.get('lights', [])):
        settings = controls.get(light.get('identity', str(index)), {})
        kind = settings.get('kind') or light['kind']
        if kind not in LOCAL_LIGHTS and kind != 'DistantLight':
            warnings.append('MoonLightIPR does not show %s %s yet.' % (kind, light.get('name', '')))
            continue
        matrix = finite(light.get('matrix', IDENTITY))
        color = [c * float(light['intensity']) for c in working_color(finite(light['color']))]
        # Filters from Lighting controls, and those a MoonRay light item names.
        filters = control_filters(settings, light, scene, warnings) + list(light.get('filters', []))
        for record in [r for r in filters if r['kind'] == 'intensity']:
            color = [c * s for c, s in zip(color, record['scale'])]
        filters = [r for r in filters if r['kind'] != 'intensity']
        if filters and (kind == 'DistantLight' or compiler is None):
            warnings.append('MoonLightIPR applies only intensity filters to %s.' % light.get('name', ''))
            filters = []
        if kind == 'DistantLight':
            angle = max(1e-3, float(light.get('angle', .5)))
            # A white Lambertian surface facing the light reflects color * intensity.
            scale = 1 / math.sin(min(math.radians(angle) / 2, math.pi / 2)) ** 2
            # The light sits on its local +Z axis.
            distant.append(unit(matrix[8:11]) + [c * scale for c in color] + [angle])
            continue
        # Sizes follow the node's scale; the flat lights emit along local -Z.
        scale_x, scale_y = math.sqrt(sum(v * v for v in matrix[0:3])), math.sqrt(sum(v * v for v in matrix[4:7]))
        width, height = float(light.get('width', 1)) * scale_x, float(light.get('height', 1)) * scale_y
        radius = float(light.get('radius', .001 if kind == 'SpotLight' else .05)) * scale_x
        radius = max(.001 * scale_x, radius) if kind != 'SpotLight' else radius
        if min(width, height, radius) <= 0:
            warnings.append('MoonLightIPR skips light %s, which has no size.' % light.get('name', ''))
            continue
        # A cylinder stands along its local Y axis and emits from its side.
        area = (4 * math.pi * radius ** 2 if kind == 'SphereLight' else width * height if kind in ('RectLight', 'PortalLight')
                else 2 * math.pi * radius * height if kind == 'CylinderLight' else math.pi * radius ** 2)
        cone = float(light.get('cone', 45))
        if kind == 'PortalLight':
            # MoonRay then lights the scene with the environment only where it shows through a portal.
            lighting = (1 if environment > 0 else 0) + sum(1 for item in scene.get('environments', []) if item.get('indirect', True))
            if lighting != 1:
                warnings.append('MoonLightIPR passes all %d lighting environments through portal %s; MoonRay needs one chosen.'
                                % (lighting, light.get('name', '')))
        # Normalized with MoonRay's default apply_scene_scale: color * intensity is flux / pi at scene scale 1.
        # A portal is not normalized; its colour and intensity multiply what shows through it.
        normalization = 1.0 if kind == 'PortalLight' else 1 / (math.pi * area)
        # A picture on a rect light, read as MoonRay reads it: without a colour conversion.
        texture = -1
        if light.get('texture') and compiler is not None:
            try:
                texture = compiler.texture({'path': light['texture'], 'srgb': False, 'color_space': 'raw', 'repeat': False})
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                warnings.append('MoonLightIPR shows %s without its texture (%s).' % (light.get('name', ''), exc))
        local.append(struct.pack('<I20fi', LOCAL_LIGHTS[kind], *(matrix[12:15] + unit(matrix[0:3]) + unit(matrix[4:7])
            + [-v for v in unit(matrix[8:11])] + [width, height, radius] + [c * normalization for c in color]
            + [cone, max(0.0, cone - 2 * float(light.get('soft_edge', 0)))]), texture)
            + (packed_filters(filters, compiler) if compiler is not None else struct.pack('<I', 0)))
    return distant, local


def emitter(mesh, settings, warnings):
    """A mesh light's record: its triangles in world space, emitting from both faces as MoonRay's MeshLight."""
    from .scene_digest import content
    from .working_space import color as working_color
    if 'instances' in mesh:
        warnings.append('MoonLightIPR skips mesh light %s; MoonRay needs instance sharing off for it.' % mesh['name'])
        return None
    matrix = finite(mesh.get('matrix', IDENTITY))
    color = [c * float(settings.get('light_intensity', 1)) for c in working_color(finite(settings.get('light_color', [1, 1, 1])))]
    signature = (content(mesh['vertices']), content(mesh['faces']), tuple(matrix))
    cached = _emitters.get(signature)
    if cached is None:
        triangles = sum(len(face) - 2 for face in mesh['faces'])
        if not 0 < triangles <= MESH_LIGHT_TRIANGLES:
            warnings.append('MoonLightIPR skips mesh light %s, which has %d triangles (the limit is %d).' % (mesh['name'], triangles, MESH_LIGHT_TRIANGLES))
            return None
        # Rows of the matrix are the basis vectors, as elsewhere in the snapshot.
        world = [[v[0] * matrix[0 + a] + v[1] * matrix[4 + a] + v[2] * matrix[8 + a] + matrix[12 + a] for a in range(3)]
                 for v in mesh['vertices']]
        corners, area = array('f'), 0.0
        for face in mesh['faces']:
            for i in range(1, len(face) - 1):
                a, b, c = world[face[0]], world[face[i]], world[face[i + 1]]
                e1, e2 = [b[k] - a[k] for k in range(3)], [c[k] - a[k] for k in range(3)]
                normal = (e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0])
                area += .5 * math.sqrt(sum(v * v for v in normal))
                corners.extend(a + b + c)
        if not area > 0 or not math.isfinite(area):
            warnings.append('MoonLightIPR skips mesh light %s, which has no area.' % mesh['name'])
            return None
        if len(_emitters) > 64:
            _emitters.clear()
        cached = _emitters[signature] = (struct.pack('<I', triangles) + corners.tobytes(), area)
    # MoonRay divides by the area, so the light gives the same power at any size.
    return (struct.pack('<I20fiI', MESH_LIGHT, *([0.0] * 12 + [1.0, 1.0, 1.0] + [c / (math.pi * cached[1]) for c in color] + [0.0, 0.0]), -1, 0)
            + cached[0])


def cage_payload(mesh, material_index, slots, warnings):
    """A subdivision surface as its control cage, which the session refines.

    MoonRay tessellates each edge into 2 ** level pieces; that many rounds of Catmull-Clark
    give the same density. Returns what mesh_payload returns.
    """
    from .scene_digest import content
    from .moonlight_materials import UV_SLOTS
    vertices, faces = mesh['vertices'], mesh['faces']
    face_materials = mesh.get('face_materials')
    available = dict(mesh.get('uv_sets') or {})
    if mesh.get('uvs'):
        available[''] = mesh['uvs']
    sets = sorted((slot, available[key]) for key, slot in slots.items() if available.get(key))
    creases = mesh.get('creases') or []
    corner_count = sum(map(len, faces))
    level = max(0, min(6, int(mesh.get('subdivision_level', 3))))
    wanted = level
    while level > 0 and corner_count * 4 ** (level - 1) > SUBDIVISION_QUADS:
        level -= 1
    if level < wanted:
        warnings.append('MoonLightIPR subdivides %s %d times rather than %d, to stay under %d quads.' % (mesh['name'], level, wanted, SUBDIVISION_QUADS))
    signature = ('cage', content(vertices), content(faces), content(face_materials) if face_materials is not None else '', level,
                 tuple(sorted(material_index.items())) if face_materials is not None else (),
                 tuple((slot, content(values)) for slot, values in sets), content(creases) if creases else '')
    cached = _packed.get(signature)
    if cached:
        return cached
    if face_materials is not None and len(face_materials) != len(faces):
        raise ValueError('Face materials must match the face count')
    try:
        corners = array('I', chain.from_iterable(faces))
    except (TypeError, OverflowError):
        raise ValueError('Invalid face in ' + mesh['name'])
    if min(map(len, faces)) < 3 or max(corners) >= len(vertices):
        raise ValueError('Invalid face in ' + mesh['name'])
    positions = array('f', chain.from_iterable(vertices))
    if not math.isfinite(sum(positions)):
        raise ValueError('Mesh %s contains a non-finite number' % mesh['name'])
    sizes = array('I', map(len, faces))
    material_ids = array('I')
    if face_materials is not None:
        default = material_index['']
        material_ids = array('I', [material_index.get(tag, default) for tag in face_materials])
    uvs, slot_map = [], [-1] * UV_SLOTS
    for slot, values in sets:
        if len(values) != len(corners):
            raise ValueError('Texture coordinates of %s must match its polygon corners' % mesh['name'])
        slot_map[slot] = len(uvs)
        uvs.append(array('f', chain.from_iterable(values)))
        if len(uvs[-1]) != len(corners) * 2 or not math.isfinite(sum(uvs[-1])):
            raise ValueError('Mesh %s has invalid texture coordinates' % mesh['name'])
    edges, sharpness = array('I'), array('f')
    for a, b, sharp in creases:
        if type(a) is not int or type(b) is not int or a == b or min(a, b) < 0 or max(a, b) >= len(vertices) or sharp < 0:
            raise ValueError('Invalid subdivision crease')
        edges.extend((a, b))
        sharpness.append(float(sharp))
    flags = MESH_SUBDIVIDE | MESH_SMOOTH | (MESH_HAS_MATERIAL_IDS if face_materials is not None else 0) | (MESH_HAS_UVS if uvs else 0)
    payload = (struct.pack('<5I', len(vertices), len(faces), len(corners), level, len(sharpness)) + positions.tobytes() + sizes.tobytes()
               + corners.tobytes() + material_ids.tobytes())
    if uvs:
        payload += struct.pack('<I', len(uvs)) + b''.join(values.tobytes() for values in uvs)
    payload += edges.tobytes() + sharpness.tobytes()
    key = hashlib.blake2b(struct.pack('<I', flags) + payload, digest_size=8).digest()
    _packed[signature] = (key, flags, payload, struct.pack('<%di' % UV_SLOTS, *slot_map))
    return _packed[signature]


def mesh_payload(mesh, material_index, slots):
    """Triangulate one mesh; return (key, flags, payload, slot map), cached by the content of its lists.

    slots maps coordinate keys to scene-wide slots; the mesh carries the sets it has, and the
    slot map says which of them serves each slot.
    """
    from .scene_digest import content
    from .moonlight_materials import UV_SLOTS
    vertices, faces = mesh['vertices'], mesh['faces']
    smooth = bool(mesh.get('smooth', True))
    # As in the RDLA path, authored normals apply only to smooth, unsubdivided meshes.
    normals = mesh.get('normals') if smooth and not mesh.get('subdivision') else None
    face_materials = mesh.get('face_materials')
    # With motion blur, where the vertices are when the shutter closes, if they move at all.
    closing = mesh.get('vertices_close')
    if closing is not None and (closing is vertices or closing == vertices):
        closing = None
    # '' names the primary UVs; other keys are coordinates the capture baked for one projection.
    available = dict(mesh.get('uv_sets') or {})
    if mesh.get('uvs'):
        available[''] = mesh['uvs']
    sets = sorted((slot, available[key]) for key, slot in slots.items() if available.get(key))
    # Keyed by content, so a mesh recaptured into new lists is not triangulated again.
    signature = (content(vertices), content(faces), content(normals) if normals else '',
                 content(face_materials) if face_materials is not None else '', smooth,
                 tuple(sorted(material_index.items())) if face_materials is not None else (),
                 tuple((slot, content(values)) for slot, values in sets), content(closing) if closing is not None else '')
    cached = _packed.get(signature)
    if cached:
        return cached
    if face_materials is not None and len(face_materials) != len(faces):
        raise ValueError('Face materials must match the face count')
    try:
        corners = array('I', chain.from_iterable(faces))
    except (TypeError, OverflowError):
        raise ValueError('Invalid face in ' + mesh['name'])
    if min(map(len, faces)) < 3 or max(corners) >= len(vertices):
        raise ValueError('Invalid face in ' + mesh['name'])
    if normals and len(normals) != len(corners):
        raise ValueError('Face-varying normals must match the corner count')
    quads = all(len(face) == 4 for face in faces)
    fan = None      # each triangle corner as an index into the polygon corners
    if normals or sets:
        if quads:
            fan = array('I', [o + k for o in range(0, len(corners), 4) for k in (0, 1, 2, 0, 2, 3)])
        else:
            fan, offset = array('I'), 0
            for face in faces:
                fan.extend([v for i in range(1, len(face) - 1) for v in (offset, offset + i, offset + i + 1)])
                offset += len(face)
    if closing is not None and len(closing) != len(vertices):
        raise ValueError('Motion samples of %s must have equal vertex counts' % mesh['name'])
    moved = array('f')
    if normals:
        # With per-corner normals every corner is its own vertex.
        indices = fan
        positions = array('f', chain.from_iterable(map(vertices.__getitem__, corners)))
        shading = array('f', chain.from_iterable(normals))
        if closing is not None:
            moved = array('f', chain.from_iterable(map(closing.__getitem__, corners)))
    else:
        if closing is not None:
            moved = array('f', chain.from_iterable(closing))
        if quads:
            indices = array('I', [face[k] for face in faces for k in (0, 1, 2, 0, 2, 3)])
        else:
            indices = array('I', [v for face in faces for i in range(1, len(face) - 1) for v in (face[0], face[i], face[i + 1])])
        positions, shading = array('f', chain.from_iterable(vertices)), array('f')
    # A sum is finite only if every term is.
    if not math.isfinite(sum(positions)) or not math.isfinite(sum(shading)) or not math.isfinite(sum(moved)):
        raise ValueError('Mesh %s contains a non-finite number' % mesh['name'])
    material_ids = array('I')
    if face_materials is not None:
        default = material_index['']
        material_ids = array('I', [index for tag, face in zip(face_materials, faces)
                                   for index in [material_index.get(tag, default)] * (len(face) - 2)])
    # Texture coordinates go per triangle corner, whichever way the vertices are shared.
    uvs, slot_map = [], [-1] * UV_SLOTS
    for slot, values in sets:
        if len(values) != len(corners):
            raise ValueError('Texture coordinates of %s must match its polygon corners' % mesh['name'])
        slot_map[slot] = len(uvs)
        uvs.append(array('f', chain.from_iterable(map(values.__getitem__, fan))))
        if len(uvs[-1]) != len(fan) * 2 or not math.isfinite(sum(uvs[-1])):
            raise ValueError('Mesh %s has invalid texture coordinates' % mesh['name'])
    flags = ((MESH_HAS_NORMALS if normals else MESH_SMOOTH if smooth else 0) | (MESH_HAS_MATERIAL_IDS if face_materials is not None else 0)
             | (MESH_HAS_UVS if uvs else 0) | (MESH_MOVES if moved else 0))
    payload = struct.pack('<2I', len(positions) // 3, len(indices) // 3) + positions.tobytes() + shading.tobytes() + indices.tobytes() + material_ids.tobytes()
    if uvs:
        payload += struct.pack('<I', len(uvs)) + b''.join(values.tobytes() for values in uvs)
    payload += moved.tobytes()
    key = hashlib.blake2b(struct.pack('<I', flags) + payload, digest_size=8).digest()
    _packed[signature] = (key, flags, payload, struct.pack('<%di' % UV_SLOTS, *slot_map))
    return _packed[signature]


def pack(scene, width, height, environment=0.15, known=(), samples=256, denoise=True, runtime=None):
    """Serialize a snapshot. Return (bytes, mesh keys, warnings).

    known holds the mesh keys the receiving session has already loaded; their data is left out.
    runtime is the MoonRay folder whose oiiotool converts textures; the default runtime if omitted.
    """
    from .working_space import configuration as working_configuration
    from .textures import configuration as texture_configuration
    with working_configuration(scene.get('asset_settings', {})), texture_configuration(scene.get('asset_settings', {})):
        return _pack(scene, int(width), int(height), float(environment), set(known), int(samples), bool(denoise), runtime)


def _pack(scene, width, height, environment, known, samples, denoise, runtime):
    from . import geometry, options
    from .moonlight_materials import Compiler
    from .working_space import TO_AP1, enabled as working_enabled
    if not 16 <= width <= 16384 or not 16 <= height <= 16384:
        raise ValueError('Image dimensions must be between 16 and 16384')
    if samples < 1:
        raise ValueError('MoonLightIPR needs at least one sample')
    warnings = []
    # MoonRay's own items arrive beside the Modo ones; draw those that have a counterpart here.
    from .entities import preview as preview_entities, replaces_environment
    if replaces_environment(scene):
        environment = 0.0   # the preview environment light goes too
    scene = preview_entities(scene, warnings)
    camera = scene['camera']
    if camera.get('projection', 'persp') != 'persp':
        raise ValueError('MoonLightIPR previews perspective cameras only')
    if camera['focal_mm'] <= 0 or camera['film_mm'] <= 0:
        raise ValueError('Camera focal length and film width must be positive')
    if camera.get('region') or scene.get('region'):
        warnings.append('MoonLightIPR ignores the render region.')
    # MoonRay's lens: the f-stop gives its diameter from the focal length, in metres.
    lens = [0.0, 1.0, 0, 0.0]
    if camera.get('dof'):
        stop, focus = float(camera.get('f_stop', 4)), float(camera.get('focus_distance', 4))
        if stop <= 0 or focus <= 0:
            raise ValueError('Depth of field requires positive f-stop and focus distance')
        blades = int(camera.get('iris_blades', 0))
        lens = [camera['focal_mm'] / stop / 2000, focus, blades if blades >= 3 else 0, float(camera.get('iris_rotation', 0))]
    if any(camera.get('film_offset', [0, 0])) or camera.get('pixel_aspect', 1) != 1:
        warnings.append('MoonLightIPR ignores film offset and pixel aspect.')
    def placed(matrix, focal):
        """Eye, target, up and vertical field of view. The camera looks down its local -Z axis;
        MoonRay's field of view is horizontal."""
        matrix = finite(matrix)
        eye = matrix[12:15]
        return (eye + [e - z for e, z in zip(eye, unit(matrix[8:11]))] + unit(matrix[4:7])
                + [math.degrees(2 * math.atan(camera['film_mm'] / (2 * focal) * height / width))])
    pose = placed(camera.get('matrix', IDENTITY), camera['focal_mm'])
    # A snapshot captured with motion blur says where everything is when the shutter opens, and
    # again, under keys ending in _close, when it closes.
    motion = bool(scene.get('motion_steps'))
    if motion and camera.get('focal_mm_close', camera['focal_mm']) <= 0:
        raise ValueError('Camera focal length must be positive at both shutter endpoints')
    settings = options.render_values(scene.get('render_settings', {}))
    depths = [min(8, settings[key]) for key in ('max_depth', 'max_diffuse_depth', 'max_glossy_depth')]
    # Material colours are worked out in Rec.709; the session takes them to the working space.
    working = working_enabled()
    parts = [b'MLS7', struct.pack('<7I', width, height, *depths, samples, (SCENE_DENOISE if denoise else 0)
                                  | (SCENE_WORKING_SPACE if working else 0) | (SCENE_MOTION if motion else 0)),
             struct.pack('<9f', *(v for row in (TO_AP1 if working else [[1, 0, 0], [0, 1, 0], [0, 0, 1]]) for v in row)),
             struct.pack('<10f', *pose), struct.pack('<2fIf', *lens)]
    if motion:
        parts.append(struct.pack('<10f', *placed(camera.get('matrix_close', camera.get('matrix', IDENTITY)),
                                                 camera.get('focal_mm_close', camera['focal_mm']))))
        if any(light.get('matrix_close', light.get('matrix')) != light.get('matrix') for light in scene.get('lights', [])):
            warnings.append('MoonLightIPR holds lights still during the shutter.')

    materials = dict(scene.get('materials', {}))
    materials.setdefault('', {'color': [.5, .5, .5], 'roughness': .4, 'metallic': 0})
    from .clay import material as clay_material
    clay = clay_material(scene.get('_clay_preview'))
    if clay:
        materials = {tag: clay for tag in materials}
    material_index = {tag: index for index, tag in enumerate(sorted(materials))}
    compiler = Compiler(runtime)
    records = [compiler.material(materials[tag], tag or 'base material') for tag in sorted(materials)]
    # Lights now, since a filter's ramp or a light's picture adds to the images.
    distant, local = lights(scene, warnings, environment, compiler)
    # Images first: the session reads them before the layers and lights that name them.
    parts += [struct.pack('<I', len(compiler.textures))] + list(compiler.textures)
    parts += [struct.pack('<I', len(records))] + records
    parts += [struct.pack('<I', len(compiler.layers))] + compiler.layers
    parts.append(struct.pack('<I%di' % len(compiler.tiles), len(compiler.tiles), *compiler.tiles))
    warnings += compiler.warnings()

    parts += environment_section(scene, environment, warnings, runtime)
    objects = scene.get('production', {}).get('objects', {})

    used, meshes, instances, order = set(), [], [], {}
    for mesh in geometry.render_meshes(scene.get('meshes', [])):
        if not mesh['faces']:
            continue
        if mesh.get('subdivision'):
            if mesh.get('vertices_close') is not None and mesh['vertices_close'] != mesh['vertices']:
                warnings.append('MoonLightIPR shows subdivision mesh %s without its change of shape during the shutter.' % mesh['name'])
            key, flags, payload, slot_map = cage_payload(mesh, material_index, compiler.slots, warnings)
        else:
            key, flags, payload, slot_map = mesh_payload(mesh, material_index, compiler.slots)
        if key not in order:
            order[key] = len(meshes)
            # Send the data once per session; later scenes refer to it by key.
            meshes.append(key + struct.pack('<I', flags | MESH_HAS_DATA) + slot_map + payload if key not in known
                          else key + struct.pack('<I', flags) + slot_map)
        used.add(key)
        material = material_index.get(mesh.get('material', ''), material_index[''])
        # A mesh light is its object's own surface, so the object says which light it is.
        light = -1
        owner = objects.get(mesh.get('source_item') or str(mesh.get('identity', '')).split('|')[0], {})
        if owner.get('mesh_light'):
            # Set in Object controls, or by a MoonRay mesh light item that names this mesh.
            record = emitter(mesh, owner, warnings)
            if record:
                light = len(local)
                local.append(record)
        opening = mesh['instances'] if 'instances' in mesh else [mesh.get('matrix', IDENTITY)]
        ending = (mesh.get('instances_close') or opening) if 'instances' in mesh else [mesh.get('matrix_close', opening[0])]
        if len(ending) != len(opening):
            raise ValueError('Instance shutter transforms of %s must match' % mesh['name'])
        for placement, later in zip(opening, ending):
            instances.append(struct.pack('<2Ii12f', order[key], material, light, *transform(placement))
                             + (struct.pack('<12f', *transform(later)) if motion else b''))
    if scene.get('extra_geometry'):
        warnings.append('MoonLightIPR does not show curves, volumes or other non-mesh geometry.')
    parts.append(struct.pack('<I', len(distant)))
    parts += [struct.pack('<7f', *light) for light in distant]
    parts += [struct.pack('<I', len(local))] + local
    parts += [struct.pack('<I', len(meshes))] + meshes + [struct.pack('<I', len(instances))] + instances
    # Drop cached triangulations of meshes that have left the scene.
    for identity in [k for k, v in _packed.items() if v[0] not in used]:
        del _packed[identity]
    return b''.join(parts), used, list(dict.fromkeys(warnings))
