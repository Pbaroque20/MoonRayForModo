"""Pure Python scene serializer. Does not import or change the Modo scene."""
import math

IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def number(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("Scene contains a non-finite number")
    return format(value, '.12g')


def string(value):
    # RDLA is Lua, not JSON; escape UTF-8 bytes, not JSON unicode escapes.
    out = []
    for byte in str(value).encode('utf-8'):
        if byte == 34:
            out.append('\\"')
        elif byte == 92:
            out.append('\\\\')
        elif 32 <= byte < 127:
            out.append(chr(byte))
        else:
            out.append('\\%03d' % byte)
    return '"' + ''.join(out) + '"'


def vector(values, kind='Vec3'):
    expected = 2 if kind == 'Vec2' else 3
    if len(values) != expected:
        raise ValueError("Invalid vector dimension")
    return '%s(%s)' % (kind, ', '.join(number(v) for v in values))


def matrix(values):
    if len(values) != 16:
        raise ValueError("Transform must contain 16 values")
    return 'Mat4(%s)' % ', '.join(number(v) for v in values)


def array(values):
    return '{' + ', '.join(values) + '}'


def scene_text(scene, width=640, height=360, samples=2, environment=0.15):
    """Serialize a snapshot to an RDLA scene. samples is MoonRay's grid side."""
    if not 16 <= int(width) <= 16384 or not 16 <= int(height) <= 16384:
        raise ValueError("Image dimensions must be between 16 and 16384")
    if not 1 <= int(samples) <= 64:
        raise ValueError("Pixel sample grid must be between 1 and 64")
    camera = scene['camera']
    lines = ['-- MoonRayForModo 0.1.0; scene units are meters',
             'local camera = PerspectiveCamera("/modo/camera") {',
             '  ["node_xform"] = %s,' % matrix(camera['matrix']),
             '  ["focal"] = %s,' % number(camera['focal_mm']),
             '  ["film_width_aperture"] = %s,' % number(camera['film_mm']),
             '  ["near"] = 0.001,', '}',
             'local lights = {}', 'local geometries = {}', 'local assignments = {}']
    if float(environment) > 0:
        lines += ['table.insert(lights, EnvLight("/modo/environment") {',
                  '  ["intensity"] = %s,' % number(environment), '})']
    for index, light in enumerate(scene.get('lights', [])):
        kind = light['kind']
        if kind not in ('DistantLight', 'SphereLight', 'RectLight'):
            raise ValueError('Unsupported light: ' + kind)
        lines += ['table.insert(lights, %s("/modo/light/%s") {' % (kind, index),
                  '  ["node_xform"] = %s,' % matrix(light['matrix']),
                  '  ["color"] = %s,' % vector(light['color'], 'Rgb'),
                  '  ["intensity"] = %s,' % number(light['intensity'])]
        if kind == 'DistantLight':
            lines += ['  ["angular_extent"] = %s,' % number(light.get('angle', 0.5))]
        elif kind == 'SphereLight':
            lines += ['  ["radius"] = %s,' % number(max(0.001, light.get('radius', 0.05)))]
        elif kind == 'RectLight':
            lines += ['  ["width"] = %s,' % number(light['width']),
                      '  ["height"] = %s,' % number(light['height'])]
        lines.append('})')
    lines.append('local lightSet = LightSet("/modo/lightSet")(lights)')
    # Keep material handles in a table to avoid Lua's local variable limit.
    lines.append('local materials = {}')
    materials = dict(scene.get('materials', {}))
    materials.setdefault('', {'color': [0.5, 0.5, 0.5], 'roughness': 0.4, 'metallic': 0})
    for index, (tag, material) in enumerate(sorted(materials.items())):
        lines += ['materials[%s] = UsdPreviewSurface("/modo/material/%s") {' % (string(tag), index),
                  '  ["diffuseColor"] = %s,' % vector(material['color'], 'Rgb'),
                  '  ["roughness"] = %s,' % number(material.get('roughness', 0.4)),
                  '  ["metallic"] = %s,' % number(material.get('metallic', 0)), ' }']
    for index, mesh in enumerate(scene.get('meshes', [])):
        vertices = mesh['vertices']
        faces = mesh['faces']
        if not faces:
            continue
        for face in faces:
            if len(face) < 3 or any(type(v) is not int or v < 0 or v >= len(vertices) for v in face):
                raise ValueError('Invalid face in ' + mesh['name'])
        tag = mesh.get('material', '')
        if tag not in materials:
            tag = ''
        subdivision = bool(mesh.get('subdivision', False))
        level = mesh.get('subdivision_level', 3)
        if type(level) is not int or not 1 <= level <= 5:
            raise ValueError('Subdivision level must be an integer between 1 and 5')
        lines += ['do', '  local geometry = RdlMeshGeometry("/modo/mesh/%s") {' % index,
                  '    ["node_xform"] = %s,' % matrix(mesh.get('matrix', IDENTITY)),
                  '    ["vertex_list_0"] = %s,' % array(vector(v) for v in vertices),
                  '    ["vertices_by_index"] = %s,' % array(str(v) for f in faces for v in f),
                  '    ["face_vertex_count"] = %s,' % array(str(len(f)) for f in faces),
                  '    ["is_subd"] = %s,' % ('true' if subdivision else 'false'),
                  *(['    ["mesh_resolution"] = %d,' % (2 ** level)] if subdivision else []),
                  '    ["smooth_normal"] = true,', '  }',
                  '  table.insert(geometries, geometry)',
                  '  table.insert(assignments, {geometry, "", materials[%s], lightSet})' % string(tag), 'end']
    lines += ['GeometrySet("/modo/geometrySet")(geometries)',
              'local layer = Layer("/modo/layer")(assignments)', 'SceneVariables {',
              '  ["camera"] = camera,', '  ["layer"] = layer,',
              '  ["image_width"] = %d,' % int(width), '  ["image_height"] = %d,' % int(height),
              '  ["pixel_samples"] = %d,' % int(samples),
              '  ["shadow_terminator_fix"] = 1,',
              '  ["sampling_mode"] = 0,', '  ["enable_motion_blur"] = false,', '}']
    return '\n'.join(lines) + '\n'
