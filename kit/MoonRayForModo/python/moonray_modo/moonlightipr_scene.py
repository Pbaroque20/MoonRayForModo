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
# Layout flags; keep in step with moonlightipr/session/scene_loader.cpp.
MESH_HAS_DATA, MESH_HAS_NORMALS, MESH_HAS_MATERIAL_IDS, MESH_SMOOTH, MESH_HAS_UVS, MESH_MOVES, MESH_SUBDIVIDE, MESH_CURVES, MESH_LINEAR, MESH_RIBBON = 1, 2, 4, 8, 16, 32, 64, 128, 256, 512
# A subdivision surface is refined in the session, up to this many quads; MoonRay's own limit is finer.
SUBDIVISION_QUADS = 3000000
SCENE_DENOISE, SCENE_WORKING_SPACE, SCENE_MOTION, SCENE_PRESENCE_SHADOWS = 1, 2, 4, 8
ENVIRONMENT_ROWS = 64
ENVIRONMENT_IMAGE = (1024, 512)
# How a camera turns a point of the picture into a direction, by the session's numbering.
PROJECTIONS = {'persp': 0, 'fisheye': 1, 'spherical': 2, 'ortho': 3}
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
    from .moonlightipr_materials import Compiler, cache_folder, color_space
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
                                  'moonlightipr-env-v2')).encode()).hexdigest()
    target = cache_folder() / (digest + '.pfm')
    if not target.is_file() or not target.stat().st_size:
        compiler = Compiler(runtime)
        steps = ((['--colorconvert', 'sRGB', 'linear'] if space == 'sRGB' else [])
                 + (['--ccmatrix', matrix_argument(TO_AP1)] if working else []) + ['--resize', '%dx%d' % ENVIRONMENT_IMAGE])
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


FILTER_DECAY, FILTER_RAMP, FILTER_ROD, FILTER_BARN, FILTER_COOKIE, FILTER_VDB = 0, 1, 2, 3, 4, 5
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
    # The shaping filters, placed as light_filters.emit places them for MoonRay: with a locator, or with the light.
    from .entities import rod_record, barn_record, cookie_record
    located = settings.get('filter_locator')
    transform = scene.get('scene_references', {}).get(located, {}).get('matrix') if located else light.get('matrix', IDENTITY)
    if transform is not None:
        if settings.get('rod_enabled'):
            records.append(rod_record(transform, *(float(settings.get(key, default)) for key, default in (('rod_width', 1), ('rod_height', 1), ('rod_depth', 1), ('rod_radius', 0), ('rod_edge', .1))),
                                      working_color(finite(settings.get('rod_color', [0, 0, 0]))), float(settings.get('rod_density', 1)), bool(settings.get('rod_invert'))))
        if settings.get('barn_enabled'):
            records.append(barn_record(transform if located else None, {side: float(settings.get('barn_' + side, 0)) for side in ('left', 'bottom', 'right', 'top')},
                                       1.0, 1.0, 0.0, float(settings.get('barn_edge', .1)), {side: 1.0 for side in ('left', 'bottom', 'right', 'top')},
                                       30.0, 0.0, [1.0, 1.0, 1.0], 1.0, False, False, False))
        if settings.get('cookie_file'):
            records.append(cookie_record(transform, settings['cookie_file'], float(settings.get('cookie_focal', 30)), float(settings.get('cookie_aperture', 24)), 1.0,
                                         float(settings.get('cookie_density', 1)), bool(settings.get('cookie_invert')), 0, False))
        if settings.get('filter_vdb'):
            records.append({'kind': 'vdb', 'file': settings['filter_vdb'], 'grid': settings.get('filter_vdb_grid', 'density'), 'matrix': transform,
                            'tint': working_color(finite(settings.get('filter_vdb_tint', [0, 0, 0]))), 'invert': False})
    return records


def scalar_ramp(compiler, lists):
    """A ramp of numbers as an image the session reads, 257 across its own stops' span: (image, low, high)."""
    from .entities import ramp_eval
    low, high = min(lists[0]), max(lists[0])
    if not high > low:
        high = low + 1.0
    steps = [i / (RAMP_SAMPLES - 1) for i in range(RAMP_SAMPLES)]
    values = [float(ramp_eval(lists[0], lists[1], lists[2], low + (high - low) * x)) for x in steps]
    return compiler.ramp({'positions': steps, 'colors': [[v, v, v] for v in values]}, exact=True), low, high


def packed_filters(records, compiler, light_matrix=None, warnings=None):
    """Decay and ramp filters as the session reads them; a ramp's colours go into a small image."""
    from .entities import ramp_eval
    parts = []
    for record in records:
        if record['kind'] == 'decay':
            parts.append(struct.pack('<2I4f12fi12fi', FILTER_DECAY, (FILTER_NEAR if record['near'] else 0) | (FILTER_FAR if record['far'] else 0),
                                     *record['distances'], *([0.0] * 12), -1, *([0.0] * 12), -1))
        elif record['kind'] == 'rod':
            # Its own way of fading over its edge: from 0 at the box to 1 at the edge's end.
            fade = scalar_ramp(compiler, record['fade'])[0] if record.get('fade') else -1
            parts.append(struct.pack('<2I4f12fi12fi', FILTER_ROD, 1 if record['invert'] else 0, *record['corner'], record['radius'],
                                     *(v for row in record['rows'] for v in row), -1,
                                     record['edge'], record['density'], *record['color'], *([0.0] * 7), fade))
        elif record['kind'] == 'barn':
            from .entities import barn_rows
            rows = barn_rows(record, light_matrix or IDENTITY)
            parts.append(struct.pack('<2I4f12fi12fi', FILTER_BARN, (1 if record['invert'] else 0) | (2 if record['orthographic'] else 0) | (4 if record['physical'] else 0),
                                     *record['low'], *record['high'], *(v for row in rows for v in row), -1,
                                     record['radius'], *record['edges'], record['focal'], *record['color'], record['density'], 0.0, 0.0, -1))
        elif record['kind'] == 'vdb':
            import subprocess
            from .entities import inverse_rows
            from .moonlightipr_volumes import dense, product
            try:
                file, unit = dense(record['file'], record['grid'], compiler.runtime)
            except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
                if warnings is not None:
                    warnings.append('MoonLightIPR leaves out a VDB light filter whose grid it cannot read (%s).' % exc)
                continue
            rows = inverse_rows(product(unit, [float(v) for v in record['matrix']]))
            remap, low, high = scalar_ramp(compiler, record['remap']) if record.get('remap') else (-1, 0.0, 1.0)
            # A blur is so far in the filter's own space; how much of the grid's cube that is along each of its axes.
            spans = [1.0 / (math.sqrt(sum(v * v for v in unit[axis * 4:axis * 4 + 3])) or 1.0) for axis in range(3)]
            parts.append(struct.pack('<2I4f12fi12fi', FILTER_VDB, (1 if record['invert'] else 0) | (8 if record.get('round') else 0), low, high, 0.0, 0.0,
                                     *(v for row in rows for v in row), compiler.grid(file), *record['tint'], float(record.get('blur', 0.0)), *spans,
                                     *([0.0] * 5), remap))
        elif record['kind'] == 'cookie':
            import subprocess
            try:
                picture = compiler.texture({'path': record['texture'], 'srgb': False, 'color_space': 'raw', 'repeat': False})
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                if warnings is not None:
                    warnings.append('MoonLightIPR leaves out a cookie whose picture it cannot read (%s).' % exc)
                continue
            if record['front'] is not None and warnings is not None:
                warnings.append('MoonLightIPR throws an orthographic cookie behind its projector as well as in front.')
            parts.append(struct.pack('<2I4f12fi12fi', FILTER_COOKIE, (1 if record['invert'] else 0) | (2 if record['white'] else 0) | (4 if record['edgeless'] else 0)
                                     | (8 if record.get('round') else 0),
                                     0.0, 0.0, 0.0, 0.0, *(v for row in record['rows'] for v in row), picture, record['density'], *record['place'], *record['blur'],
                                     0.0, 0.0, -1))
        elif record['kind'] == 'ramp':
            # The ramp over its own 0 to 1, which the session stretches from begin to end.
            steps = [i / (RAMP_SAMPLES - 1) for i in range(RAMP_SAMPLES)]
            colors = [ramp_eval(record['positions'], record['colors'], record['interpolations'], x) for x in steps]
            texture = compiler.ramp({'positions': steps, 'colors': colors}, exact=True)
            rows = record['rows'] or [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]]
            flags = ((FILTER_DIRECTIONAL if record['directional'] else 0) | (FILTER_MIRROR if record['mirror'] else 0)
                     | (FILTER_PLACED if record['rows'] else 0))
            parts.append(struct.pack('<2I4f12fi12fi', FILTER_RAMP, flags, record['begin'], record['end'], record['intensity'], record['density'],
                                     *(v for row in rows for v in row), texture, *([0.0] * 12), -1))
    return struct.pack('<I', len(parts)) + b''.join(parts)


def lights(scene, warnings, environment=0.0, compiler=None, closing=None):
    """Return (distant, local) light records, with MoonRay's default normalization applied.

    closing, given a dict, is given each light's pose when the shutter closes, in the order of the records: under
    'distant' its direction and axes (9 floats), under 'local' its position, axes and direction (12)."""
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
        # Held still unless moving lights blur (MoonRay's own way, which MoonLightIPR then follows).
        from .native import light_motion
        ending = finite(light.get('matrix_close') or matrix) if light_motion() else matrix
        color = [c * float(light['intensity']) for c in working_color(finite(light['color']))]
        # Filters from Lighting controls, and those a MoonRay light item names.
        filters = control_filters(settings, light, scene, warnings) + list(light.get('filters', []))
        for record in [r for r in filters if r['kind'] == 'intensity']:
            color = [c * s for c, s in zip(color, record['scale'])]
        filters = [r for r in filters if r['kind'] != 'intensity']
        # A picture on the light, read as MoonRay reads it: without a colour conversion. A sphere's and a cylinder's
        # go all the way round, so they repeat where a flat light's stops at its edge.
        texture = -1
        if light.get('texture') and compiler is not None and kind != 'PortalLight':
            try:
                texture = compiler.texture({'path': light['texture'], 'srgb': False, 'color_space': 'raw',
                                            'repeat': kind in ('SphereLight', 'CylinderLight')})
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                warnings.append('MoonLightIPR shows %s without its texture (%s).' % (light.get('name', ''), exc))
        if filters and (kind == 'DistantLight' or compiler is None):
            warnings.append('MoonLightIPR applies only intensity filters to %s.' % light.get('name', ''))
            filters = []
        if kind == 'DistantLight':
            angle = max(1e-3, float(light.get('angle', .5)))
            # A white Lambertian surface facing the light reflects color * intensity.
            scale = 1 / math.sin(min(math.radians(angle) / 2, math.pi / 2)) ** 2
            # The light sits on its local +Z axis.
            # A sun's disc as the camera sees it has a colour and a width of its own; any other distant light the camera
            # sees is seen as it shines.
            seen = light.get('disc')
            shown = working_color(finite(seen['radiance'])) + [float(seen['angle'])] if seen else [c * scale for c in color] + [angle]
            distant.append(unit(matrix[8:11]) + [c * scale for c in color] + [angle, 1 if seen or light.get('camera_visible') else 0]
                           + unit(matrix[0:3]) + unit(matrix[4:7]) + [texture] + shown)
            if closing is not None:
                closing.setdefault('distant', []).append(unit(ending[8:11]) + unit(ending[0:3]) + unit(ending[4:7]))
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
        if closing is not None:
            closing.setdefault('local', []).append(ending[12:15] + unit(ending[0:3]) + unit(ending[4:7]) + [-v for v in unit(ending[8:11])])
        local.append(struct.pack('<I20fi', LOCAL_LIGHTS[kind], *(matrix[12:15] + unit(matrix[0:3]) + unit(matrix[4:7])
            + [-v for v in unit(matrix[8:11])] + [width, height, radius] + [c * normalization for c in color]
            + [cone, max(0.0, cone - 2 * float(light.get('soft_edge', 0)))]), texture)
            + (packed_filters(filters, compiler, matrix, warnings) if compiler is not None else struct.pack('<I', 0)))
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
    # A mesh light has no cone: the number says instead whether the camera sees the surface shining.
    seen = 1.0 if settings.get('light_seen', True) else 0.0
    return (struct.pack('<I20fiI', MESH_LIGHT, *([0.0] * 12 + [1.0, 1.0, 1.0] + [c / (math.pi * cached[1]) for c in color] + [seen, 0.0]), -1, 0)
            + cached[0])


def seen_by(item):
    """The rays that find a mesh or a set of curves, as the engine's bits: 1 the camera's, 2 light scattered
    diffusely, 4 reflections, 8 light passing through a surface, 16 shadows. Modo's visibility is in MoonRay's
    order: camera, indirect, reflection, refraction, subsurface, shadow."""
    visibility = item.get('visibility')
    if not visibility:
        return 255
    camera, indirect, reflection, refraction, _, shadow = (list(visibility) + [True] * 6)[:6]
    return (1 if camera else 0) | (2 if indirect else 0) | (4 if reflection else 0) | (8 if refraction else 0) | (16 if shadow else 0)


def cage_payload(mesh, material_index, slots, warnings):
    """A subdivision surface as its control cage, which the session refines.

    MoonRay tessellates each edge into 2 ** level pieces; that many rounds of Catmull-Clark
    give the same density. Returns what mesh_payload returns.
    """
    from .scene_digest import content
    from .moonlightipr_materials import UV_SLOTS
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
    from .moonlightipr_materials import UV_SLOTS
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
    if scene.get('_draft') == 2:
        # A draft's lines are as clean after a few passes as after hundreds, and there is nothing in them to denoise.
        # Fewer still while a drag is being followed, which wants pictures more than clean ones.
        samples, denoise = min(samples, int(scene.get('_draft_samples') or 12)), False
    from .moonlightipr_materials import Compiler
    from .working_space import TO_AP1, enabled as working_enabled
    if not 16 <= width <= 16384 or not 16 <= height <= 16384:
        raise ValueError('Image dimensions must be between 16 and 16384')
    if samples < 1:
        raise ValueError('MoonLightIPR needs at least one sample')
    warnings = []
    # Which lights light an object, and whose shadows fall where, are MoonRay's to work out.
    if any(held.get('link_enabled') or held.get('shadow_exclude') or held.get('shadow_receivers')
           for held in (scene.get('production') or {}).get('objects', {}).values() if isinstance(held, dict)):
        warnings.append('MoonLightIPR lights and shadows every object alike: light links and the shadows objects are set not to cast show in MoonRay only.')
    if any(isinstance(held, dict) and held.get('sss_trace_set') for held in (scene.get('materials') or {}).values()):
        warnings.append('MoonLightIPR does not join neighbouring objects in subsurface light: a material\'s subsurface neighbours show in MoonRay only.')
    # MoonRay's own items arrive beside the Modo ones; draw those that have a counterpart here.
    from .entities import preview as preview_entities, replaces_environment
    if replaces_environment(scene):
        environment = 0.0   # the preview environment light goes too
    scene = preview_entities(scene, warnings)
    camera = scene['camera']
    projection = camera.get('projection', 'persp')
    if projection not in PROJECTIONS:
        raise ValueError('MoonLightIPR previews perspective, orthographic, fisheye and spherical cameras only')
    if projection == 'ortho':
        # An orthographic camera's rays run side by side over a window this wide, in the scene's units.
        width_across = float(camera.get('ortho_width', 1.0))
        if not width_across > 0:
            raise ValueError('Orthographic width must be positive')
        camera = dict(camera, projection_values=[width_across, 0.0, 0.0, 0.0], dof=False)
    if camera['focal_mm'] <= 0 or camera['film_mm'] <= 0:
        raise ValueError('Camera focal length and film width must be positive')
    # The part of the picture to render: left, top, right, bottom, as fractions. The rest is black.
    region = [float(v) for v in (scene.get('region') or camera.get('region') or [0, 0, 1, 1])]
    if len(region) != 4 or not all(math.isfinite(v) for v in region) or region[2] <= region[0] or region[3] <= region[1]:
        region = [0.0, 0.0, 1.0, 1.0]
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
    depths = [min(8, settings[key]) for key in ('max_depth', 'max_diffuse_depth', 'max_glossy_depth', 'max_volume_depth')]
    # Material colours are worked out in Rec.709; the session takes them to the working space.
    working = working_enabled()
    # The letter after MLS says which form of scene this is; the session refuses any other than its own.
    parts = [b'MLSF', struct.pack('<8I', width, height, *depths, samples, (SCENE_DENOISE if denoise else 0)
                                  | (SCENE_WORKING_SPACE if working else 0) | (SCENE_MOTION if motion else 0)
                                  # See-through surfaces cast whole shadows unless the scene asks for lighter ones, as in MoonRay.
                                  | (SCENE_PRESENCE_SHADOWS if settings.get('enable_presence_shadows') else 0)),
             # The scene's sample clamp, and from which bounce it holds.
             struct.pack('<fI', float(settings['sample_clamping_value']), int(settings['sample_clamping_depth'])),
             struct.pack('<9f', *(v for row in (TO_AP1 if working else [[1, 0, 0], [0, 1, 0], [0, 0, 1]]) for v in row)),
             struct.pack('<10f', *pose), struct.pack('<2fIf', *lens),
             struct.pack('<I4f', PROJECTIONS[projection], *[float(v) for v in (camera.get('projection_values') or [0, 0, 0, 0])]),
             # Draft: 1 draws what is outside the region as lines, 2 the whole picture.
             struct.pack('<4fI', *region, int(scene.get('_draft') or 0))]
    if motion:
        parts.append(struct.pack('<10f', *placed(camera.get('matrix_close', camera.get('matrix', IDENTITY)),
                                                 camera.get('focal_mm_close', camera['focal_mm']))))

    materials = dict(scene.get('materials', {}))
    materials.setdefault('', {'color': [.5, .5, .5], 'roughness': .4, 'metallic': 0})
    from .clay import material as clay_material
    clay = clay_material(scene.get('_clay_preview'))
    if clay:
        materials = {tag: clay for tag in materials}
    # VDB volumes: each a unit cube over its grid, in a material that is the fog.
    from .moonlightipr_volumes import fogs as vdb_fogs
    fogs = vdb_fogs(scene, runtime, warnings)
    for _, tag, fog in fogs:
        materials[tag] = fog
    material_index = {tag: index for index, tag in enumerate(sorted(materials))}
    compiler = Compiler(runtime)
    records = [compiler.material(materials[tag], tag or 'base material') for tag in sorted(materials)]
    # Lights now, since a filter's ramp or a light's picture adds to the images.
    # Where each light is when the shutter closes: lights move as the camera and the meshes do.
    closing = {'distant': [], 'local': []}
    distant, local = lights(scene, warnings, environment, compiler, closing)
    # Images first: the session reads them before the layers and lights that name them.
    parts += [struct.pack('<I', len(compiler.textures))] + list(compiler.textures)
    parts += [struct.pack('<I', len(compiler.grids))] + list(compiler.grids)
    parts += [struct.pack('<I', len(records))] + records
    parts += [struct.pack('<I', len(compiler.layers))] + compiler.layers
    parts.append(struct.pack('<I%di' % len(compiler.tiles), len(compiler.tiles), *compiler.tiles))
    warnings += compiler.warnings()

    parts += environment_section(scene, environment, warnings, runtime)
    objects = scene.get('production', {}).get('objects', {})

    used, meshes, instances, order = set(), [], [], {}
    for mesh in list(geometry.render_meshes(scene.get('meshes', []))) + [fog for fog, _, _ in fogs]:
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
                # A mesh light is held where it is during the shutter.
                closing['local'].append([0.0] * 12)
        opening = mesh['instances'] if 'instances' in mesh else [mesh.get('matrix', IDENTITY)]
        ending = (mesh.get('instances_close') or opening) if 'instances' in mesh else [mesh.get('matrix_close', opening[0])]
        if len(ending) != len(opening):
            raise ValueError('Instance shutter transforms of %s must match' % mesh['name'])
        # A fog's box is found by every ray, and so is a mesh light, which is the light itself.
        seen = 255 if light >= 0 or mesh.get('volume') else seen_by(mesh)
        for placement, later in zip(opening, ending):
            instances.append(struct.pack('<2IiI12f', order[key], material, light, seen, *transform(placement))
                             + (struct.pack('<12f', *transform(later)) if motion else b''))
    # Curves are curves on the GPU too: each strand a run of round segments, in the strands' own material.
    from .moonlightipr_curves import payload as curve_payload
    from .moonlightipr_materials import UV_SLOTS
    for entry in scene.get('extra_geometry', []):
        if entry.get('kind') == 'curves' and entry.get('fur_file'):
            # Fur grown into a file for MoonRay: the preview takes a share of its fibres from the file.
            entry = fur_from_file(entry)
        if entry.get('kind') != 'curves' or not entry.get('vertices'):
            continue
        packed = curve_payload(entry, compiler.slots.get(''))
        if packed is None:
            continue
        key, payload, coordinates, straight, moves = packed
        # MoonRay's own default strand is a flat ribbon that faces the view; Round tubes is the object's choice.
        ribbon = not entry.get('round')
        key = key if not ribbon else hashlib.blake2b(key + b'ribbon', digest_size=8).digest()
        if key not in order:
            order[key] = len(meshes)
            flags = (MESH_CURVES | (MESH_HAS_UVS if coordinates else 0) | (MESH_LINEAR if straight else 0) | (MESH_MOVES if moves else 0)
                     | (MESH_RIBBON if ribbon else 0))
            slot_map = [-1] * UV_SLOTS
            if coordinates:
                slot_map[compiler.slots['']] = 0
            head = key + struct.pack('<I', flags | (0 if key in known else MESH_HAS_DATA)) + struct.pack('<%di' % UV_SLOTS, *slot_map)
            meshes.append(head if key in known else head + payload)
        used.add(key)
        placement = transform(entry.get('matrix') or IDENTITY)
        instances.append(struct.pack('<2IiI12f', order[key], material_index.get(entry.get('material', ''), material_index['']), -1, seen_by(entry), *placement)
                         + (struct.pack('<12f', *transform(entry.get('matrix_close') or entry.get('matrix') or IDENTITY)) if motion else b''))
    if any(entry.get('kind') not in ('curves', 'vdb') for entry in scene.get('extra_geometry', [])):
        warnings.append('MoonLightIPR does not show points.')
    parts.append(struct.pack('<I', len(distant)))
    parts += [struct.pack('<7fI6fi4f', *light) for light in distant]
    parts += [struct.pack('<I', len(local))] + local
    parts += [struct.pack('<I', len(meshes))] + meshes + [struct.pack('<I', len(instances))] + instances
    if motion:
        # Form 'F': the lights' poses when the shutter closes, as many as there are lights of each kind.
        parts += [struct.pack('<I', len(closing['distant']))] + [struct.pack('<9f', *pose) for pose in closing['distant']]
        parts += [struct.pack('<I', len(closing['local']))] + [struct.pack('<12f', *pose) for pose in closing['local']]
    # Drop cached triangulations of meshes that have left the scene.
    for identity in [k for k, v in _packed.items() if v[0] not in used]:
        del _packed[identity]
    return b''.join(parts), used, list(dict.fromkeys(warnings))


# Fur read from a file, by the file and how much of it was taken: reading a million fibres is not done twice.
_FUR = {}
# The most fibres of a fur file the GPU preview draws.
FUR_MOST = 150000


def fur_from_file(entry):
    """A fur entry that names a file, with a share of the file's fibres in it as lists."""
    key = (entry['fur_file'], FUR_MOST)
    held = _FUR.get(key)
    if held is None:
        from . import fur_native
        try:
            vertices, counts, radii, places, fibres = fur_native.read(entry['fur_file'], FUR_MOST)
            # The preview draws a share of the fibres, each wider by as much as there are fewer, so that the fur
            # covers what the whole of it covers. (MoonRay renders every fibre at its own width.)
            if counts and fibres > len(counts):
                wider = (fibres / float(len(counts))) ** .5
                radii = [radius * wider for radius in radii]
        except (OSError, ValueError, EOFError):
            return entry
        if len(_FUR) >= 6:
            _FUR.pop(next(iter(_FUR)))
        held = _FUR[key] = dict(vertices=vertices, counts=counts, radii=radii, uvs=places)
    return dict(entry, **held)
