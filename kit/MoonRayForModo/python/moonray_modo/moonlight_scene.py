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
MESH_HAS_DATA, MESH_HAS_NORMALS, MESH_HAS_MATERIAL_IDS, MESH_SMOOTH, MESH_HAS_UVS = 1, 2, 4, 8, 16
SCENE_DENOISE = 1
ENVIRONMENT_ROWS = 64
ENVIRONMENT_IMAGE = (1024, 512)
GRADIENTS = ('constant', 'grad2', 'grad4', 'overcast')
LOCAL_LIGHTS = {'SphereLight': 0, 'RectLight': 1, 'DiskLight': 2, 'SpotLight': 3}
_packed = {}


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
    """Convert a latitude-longitude image once to a linear float file the session reads."""
    import os
    import tempfile
    from pathlib import Path
    from .moonlight_materials import Compiler
    source = Path(item['path'])
    stat = source.stat()
    srgb = bool(item.get('srgb'))
    digest = hashlib.sha256(repr((str(source.resolve()), stat.st_size, stat.st_mtime_ns, srgb, ENVIRONMENT_IMAGE, 'moonlight-env-v1')).encode()).hexdigest()
    target = Path(os.environ.get('LOCALAPPDATA', tempfile.gettempdir())) / 'MoonRayForModo/MoonLight' / (digest + '.pfm')
    if not target.is_file() or not target.stat().st_size:
        Compiler(runtime).convert(source, target, True, (['--colorconvert', 'sRGB', 'linear'] if srgb else [])
                                  + ['--resize', '%dx%d' % ENVIRONMENT_IMAGE])
    return str(target)


def environment_section(scene, environment, warnings, runtime):
    """Pack what lights the scene and what the camera sees behind it.

    Each is a column of rows from zenith to nadir, summing the preview light and every
    constant or gradient environment, plus at most one latitude-longitude image.
    """
    import subprocess
    from .working_space import color as working_color, enabled as working_enabled
    from .environments import gradient_color
    # MoonRay does not show the preview environment light to the camera.
    rows = {'lighting': [[max(0.0, float(environment))] * 3 for _ in range(ENVIRONMENT_ROWS)],
            'background': [[0.0] * 3 for _ in range(ENVIRONMENT_ROWS)]}
    images = {'lighting': None, 'background': None}
    for item in scene.get('environments', []):
        intensity = float(item['intensity'])
        targets = [name for name, visible in (('lighting', item.get('indirect', True)), ('background', item.get('camera', True))) if visible]
        if item['kind'] == 'image':
            try:
                matrix = finite(item.get('matrix', IDENTITY))
                # The image's own axes in world space, which the session turns directions into.
                record = (environment_image(item, runtime), intensity, unit(matrix[0:3]) + unit(matrix[4:7]) + unit(matrix[8:11]))
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                warnings.append('MoonLightIPR shows environment %s as uniform grey; its image could not be read (%s).' % (item.get('name', ''), exc))
            else:
                if working_enabled():
                    warnings.append('MoonLightIPR shows environment %s without the ACEScg conversion.' % item.get('name', ''))
                if item.get('color_space', '') not in ('', '(default)', '(none)', 'raw', 'Linear', 'linear', 'lin_rec709', 'srgb_texture', 'sRGB'):
                    warnings.append('MoonLightIPR ignores the OCIO colour space of environment %s.' % item.get('name', ''))
                # One image per scene: a second, or a different one behind the camera, falls back to grey.
                taken = next((images[name] for name in images if images[name]), None)
                fits = [name for name in targets if images[name] is None and (taken is None or taken[0] == record[0])]
                for name in fits:
                    images[name] = record
                targets = [name for name in targets if name not in fits]
                if not targets:
                    continue
                warnings.append('MoonLightIPR shows only one environment image; %s is uniform grey where another is in use.' % item.get('name', ''))
        elif item['kind'] not in GRADIENTS:
            # Layer stacks and physical skies are not translated.
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


def lights(scene, warnings):
    """Return (distant, local) light records, with MoonRay's default normalization applied."""
    from .working_space import color as working_color
    controls = scene.get('production', {}).get('lights', {})
    distant, local = [], []
    for index, light in enumerate(scene.get('lights', [])):
        settings = controls.get(light.get('identity', str(index)), {})
        kind = settings.get('kind') or light['kind']
        if kind not in LOCAL_LIGHTS and kind != 'DistantLight':
            warnings.append('MoonLightIPR does not show %s %s yet.' % (kind, light.get('name', '')))
            continue
        if settings.get('filter_enabled') or settings.get('decay_enabled') or settings.get('filters'):
            warnings.append('MoonLightIPR ignores light filters on %s.' % light.get('name', ''))
        matrix = finite(light.get('matrix', IDENTITY))
        color = [c * float(light['intensity']) for c in working_color(finite(light['color']))]
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
        area = 4 * math.pi * radius ** 2 if kind == 'SphereLight' else width * height if kind == 'RectLight' else math.pi * radius ** 2
        cone = float(light.get('cone', 45))
        # Normalized with MoonRay's default apply_scene_scale: color * intensity is flux / pi at scene scale 1.
        local.append(struct.pack('<I20f', LOCAL_LIGHTS[kind], *(matrix[12:15] + unit(matrix[0:3]) + unit(matrix[4:7])
            + [-v for v in unit(matrix[8:11])] + [width, height, radius] + [c / (math.pi * area) for c in color]
            + [cone, max(0.0, cone - 2 * float(light.get('soft_edge', 0)))])))
    if any(v.get('mesh_light') for v in scene.get('production', {}).get('objects', {}).values()):
        warnings.append('MoonLightIPR does not show mesh lights yet.')
    return distant, local


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
    # '' names the primary UVs; other keys are coordinates the capture baked for one projection.
    available = dict(mesh.get('uv_sets') or {})
    if mesh.get('uvs'):
        available[''] = mesh['uvs']
    sets = sorted((slot, available[key]) for key, slot in slots.items() if available.get(key))
    # Keyed by content, so a mesh recaptured into new lists is not triangulated again.
    signature = (content(vertices), content(faces), content(normals) if normals else '',
                 content(face_materials) if face_materials is not None else '', smooth,
                 tuple(sorted(material_index.items())) if face_materials is not None else (),
                 tuple((slot, content(values)) for slot, values in sets))
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
    if normals:
        # With per-corner normals every corner is its own vertex.
        indices = fan
        positions = array('f', chain.from_iterable(map(vertices.__getitem__, corners)))
        shading = array('f', chain.from_iterable(normals))
    else:
        if quads:
            indices = array('I', [face[k] for face in faces for k in (0, 1, 2, 0, 2, 3)])
        else:
            indices = array('I', [v for face in faces for i in range(1, len(face) - 1) for v in (face[0], face[i], face[i + 1])])
        positions, shading = array('f', chain.from_iterable(vertices)), array('f')
    # A sum is finite only if every term is.
    if not math.isfinite(sum(positions)) or not math.isfinite(sum(shading)):
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
             | (MESH_HAS_UVS if uvs else 0))
    payload = struct.pack('<2I', len(positions) // 3, len(indices) // 3) + positions.tobytes() + shading.tobytes() + indices.tobytes() + material_ids.tobytes()
    if uvs:
        payload += struct.pack('<I', len(uvs)) + b''.join(values.tobytes() for values in uvs)
    key = hashlib.blake2b(struct.pack('<I', flags) + payload, digest_size=8).digest()
    _packed[signature] = (key, flags, payload, struct.pack('<%di' % UV_SLOTS, *slot_map))
    return _packed[signature]


def pack(scene, width, height, environment=0.15, known=(), samples=256, denoise=True, runtime=None):
    """Serialize a snapshot. Return (bytes, mesh keys, warnings).

    known holds the mesh keys the receiving session has already loaded; their data is left out.
    runtime is the MoonRay folder whose oiiotool converts textures; the default runtime if omitted.
    """
    from .working_space import configuration as working_configuration
    with working_configuration(scene.get('asset_settings', {})):
        return _pack(scene, int(width), int(height), float(environment), set(known), int(samples), bool(denoise), runtime)


def _pack(scene, width, height, environment, known, samples, denoise, runtime):
    from . import geometry, options
    from .moonlight_materials import Compiler
    if not 16 <= width <= 16384 or not 16 <= height <= 16384:
        raise ValueError('Image dimensions must be between 16 and 16384')
    if samples < 1:
        raise ValueError('MoonLightIPR needs at least one sample')
    warnings = []
    camera = scene['camera']
    if camera.get('projection', 'persp') != 'persp':
        raise ValueError('MoonLightIPR previews perspective cameras only')
    if camera['focal_mm'] <= 0 or camera['film_mm'] <= 0:
        raise ValueError('Camera focal length and film width must be positive')
    for key, label in [('dof', 'depth of field'), ('region', 'the render region')]:
        if camera.get(key) or scene.get(key):
            warnings.append('MoonLightIPR ignores %s.' % label)
    if any(camera.get('film_offset', [0, 0])) or camera.get('pixel_aspect', 1) != 1:
        warnings.append('MoonLightIPR ignores film offset and pixel aspect.')
    matrix = finite(camera.get('matrix', IDENTITY))
    eye, up = matrix[12:15], unit(matrix[4:7])
    # The camera looks down its local -Z axis; MoonRay's field of view is horizontal.
    target = [e - z for e, z in zip(eye, unit(matrix[8:11]))]
    fov = math.degrees(2 * math.atan(camera['film_mm'] / (2 * camera['focal_mm']) * height / width))
    settings = options.render_values(scene.get('render_settings', {}))
    depths = [min(8, settings[key]) for key in ('max_depth', 'max_diffuse_depth', 'max_glossy_depth')]
    parts = [b'MLS6', struct.pack('<7I', width, height, *depths, samples, SCENE_DENOISE if denoise else 0),
             struct.pack('<10f', *(eye + target + up + [fov]))]

    materials = dict(scene.get('materials', {}))
    materials.setdefault('', {'color': [.5, .5, .5], 'roughness': .4, 'metallic': 0})
    from .clay import material as clay_material
    clay = clay_material(scene.get('_clay_preview'))
    if clay:
        materials = {tag: clay for tag in materials}
    material_index = {tag: index for index, tag in enumerate(sorted(materials))}
    compiler = Compiler(runtime)
    records = [compiler.material(materials[tag], tag or 'base material') for tag in sorted(materials)]
    # Images first: the session reads them before the layers that name them.
    parts += [struct.pack('<I', len(compiler.textures))] + list(compiler.textures)
    parts += [struct.pack('<I', len(records))] + records
    parts += [struct.pack('<I', len(compiler.layers))] + compiler.layers
    warnings += compiler.warnings()

    parts += environment_section(scene, environment, warnings, runtime)
    distant, local = lights(scene, warnings)
    parts.append(struct.pack('<I', len(distant)))
    parts += [struct.pack('<7f', *light) for light in distant]
    parts += [struct.pack('<I', len(local))] + local

    used, meshes, instances, order = set(), [], [], {}
    for mesh in geometry.render_meshes(scene.get('meshes', [])):
        if not mesh['faces']:
            continue
        if mesh.get('subdivision'):
            warnings.append('MoonLightIPR shows subdivision meshes as their control cage.')
        key, flags, payload, slot_map = mesh_payload(mesh, material_index, compiler.slots)
        if key not in order:
            order[key] = len(meshes)
            # Send the data once per session; later scenes refer to it by key.
            meshes.append(key + struct.pack('<I', flags | MESH_HAS_DATA) + slot_map + payload if key not in known
                          else key + struct.pack('<I', flags) + slot_map)
        used.add(key)
        material = material_index.get(mesh.get('material', ''), material_index[''])
        for placement in (mesh['instances'] if 'instances' in mesh else [mesh.get('matrix', IDENTITY)]):
            instances.append(struct.pack('<2I12f', order[key], material, *transform(placement)))
    if scene.get('extra_geometry'):
        warnings.append('MoonLightIPR does not show curves, volumes or other non-mesh geometry.')
    parts += [struct.pack('<I', len(meshes))] + meshes + [struct.pack('<I', len(instances))] + instances
    # Drop cached triangulations of meshes that have left the scene.
    for identity in [k for k, v in _packed.items() if v[0] not in used]:
        del _packed[identity]
    return b''.join(parts), used, list(dict.fromkeys(warnings))
