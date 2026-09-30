"""Pure Python scene serializer. Does not import or change the Modo scene."""
import math
from . import options, textures

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


def scene_text(scene, width=640, height=360, samples=2, environment=0.15, output_file=None):
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
        if kind not in ('DistantLight', 'SphereLight', 'RectLight', 'SpotLight'):
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
        elif kind == 'SpotLight':
            cone = light.get('cone', 45)
            lines += ['  ["outer_cone_angle"] = %s,' % number(cone),
                      '  ["inner_cone_angle"] = %s,' % number(max(0, cone - 2 * light.get('soft_edge', 0))),
                      '  ["lens_radius"] = %s,' % number(light.get('radius', .001))]
        lines.append('})')
    lines.append('local lightSet = LightSet("/modo/lightSet")(lights)')
    # Keep material handles in a table to avoid Lua's local variable limit.
    lines.append('local materials = {}')
    materials = dict(scene.get('materials', {}))
    materials.setdefault('', {'color': [0.5, 0.5, 0.5], 'roughness': 0.4, 'metallic': 0})
    for index, (tag, material) in enumerate(sorted(materials.items())):
        bindings = {}
        glass = (material.get('transmission', 0) > 0 or material.get('presence', 1) < 1 or
                 any(k.startswith('tran') for k in material.get('textures', {})))
        from .graph import bindings as graph_bindings
        moonshine = material.get('shader') == 'DwaBaseMaterial'
        bindings = graph_bindings(material, index, lines, glass and not moonshine)
        if moonshine:
            from .moonshine import emit
            emit(material, tag, index, bindings, lines)
            continue
        if glass:
            lines += ['materials[%s] = ModoGlassMaterial("/modo/material/%s") {' % (string(tag), index),
                      '  ["transmission"] = %s,' % number(material.get('transmission', 0)),
                      '  ["transmissionColor"] = %s,' % vector(material.get('transmission_color', [1, 1, 1]), 'Rgb'),
                      '  ["ior"] = %s,' % number(material.get('ior', 1.5)),
                      '  ["roughness"] = %s,' % number(material.get('roughness', 0)),
                      '  ["refractionRoughness"] = %s,' % number(material.get('refraction_roughness', 0)),
                      '  ["presence"] = %s,' % number(material.get('presence', 1)),
                      '  ["diffuseColor"] = %s,' % vector(material['color'], 'Rgb'),
                      '  ["emissiveColor"] = %s,' % vector(material.get('emission', [0, 0, 0]), 'Rgb')]
            for attribute, binding in bindings.items():
                lines.append('  [%s] = %s,' % (string(attribute), binding))
            lines.append('}')
            continue
        lines += ['materials[%s] = UsdPreviewSurface("/modo/material/%s") {' % (string(tag), index),
                  '  ["diffuseColor"] = %s,' % vector(material['color'], 'Rgb'),
                  '  ["roughness"] = %s,' % number(material.get('roughness', 0.4)),
                  '  ["metallic"] = %s,' % number(material.get('metallic', 0)),
                  '  ["emissiveColor"] = %s,' % vector(material.get('emission', [0, 0, 0]), 'Rgb'),
                  '  ["ior"] = %s,' % number(material.get('ior', 1.5)),
                  '  ["opacity"] = %s,' % number(material.get('opacity', 1)),
                  '  ["clearcoat"] = %s,' % number(material.get('clearcoat', 0)),
                  '  ["clearcoatRoughness"] = %s,' % number(material.get('clearcoat_roughness', .01))]
        if 'specular' in material and not material.get('metallic', 0):
            lines += ['  ["useSpecularWorkflow"] = 1,',
                      '  ["specularColor"] = %s,' % vector(material['specular'], 'Rgb')]
        for attribute, binding in bindings.items():
            lines.append('  [%s] = %s,' % (string(attribute), binding))
        lines.append('}')
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
        face_materials = mesh.get('face_materials')
        parts = {}
        if face_materials is not None:
            if len(face_materials) != len(faces):
                raise ValueError('Face materials must match the face count')
            for face_index, face_tag in enumerate(face_materials):
                face_tag = face_tag if face_tag in materials else ''
                parts.setdefault(face_tag, []).append(face_index)
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
                  '    ["smooth_normal"] = %s,' % ('true' if mesh.get('smooth', True) else 'false')]
        for source, attribute, kind in [('uvs', 'uv_list', 'Vec2'), ('normals', 'normal_list', 'Vec3')]:
            values = mesh.get(source, [])
            if source == 'normals' and (subdivision or not mesh.get('smooth', True)):
                continue
            if values:
                if len(values) != sum(map(len, faces)):
                    raise ValueError('Face-varying %s must match the corner count' % source)
                lines.append('    [%s] = %s,' % (string(attribute), array(vector(v, kind) for v in values)))
        if parts:
            lines += ['    ["part_list"] = %s,' % array(string('part%d' % i) for i in range(len(parts))),
                      '    ["part_face_count_list"] = %s,' % array(str(len(v)) for v in parts.values()),
                      '    ["part_face_indices"] = %s,' % array(str(f) for v in parts.values() for f in v)]
        lines += ['  }']
        if parts:
            for part_index, face_tag in enumerate(parts):
                lines.append('  table.insert(assignments, {geometry, %s, materials[%s], lightSet})' %
                             (string('part%d' % part_index), string(face_tag)))
        else:
            lines.append('  table.insert(assignments, {geometry, "", materials[%s], lightSet})' % string(tag))
        if 'instances' in mesh:
            if mesh['instances']:
                lines += ['  local instances = RdlInstancerGeometry("/modo/instances/%s") {' % index,
                          '    ["method"] = 2,',
                          '    ["references"] = {geometry},',
                          '    ["use_reference_xforms"] = false,',
                          '    ["use_reference_attributes"] = true,',
                          '    ["xform_list"] = %s,' % array(matrix(m) for m in mesh['instances']),
                          '  }', '  table.insert(geometries, instances)',
                          '  table.insert(assignments, {instances, "", materials[%s], lightSet})' % string(tag)]
        else:
            lines.append('  table.insert(geometries, geometry)')
        lines.append('end')
    lines += ['GeometrySet("/modo/geometrySet")(geometries)',
              'local layer = Layer("/modo/layer")(assignments)', 'SceneVariables {',
              '  ["camera"] = camera,', '  ["layer"] = layer,',
              '  ["image_width"] = %d,' % int(width), '  ["image_height"] = %d,' % int(height),
              '  ["pixel_samples"] = %d,' % int(samples),
              '  ["sampling_mode"] = 0,', '  ["enable_motion_blur"] = false,',
              # Renderer already writes into its private temp folder and atomically
              # publishes the finished EXR; avoid a second OS-specific staging layer.
              '  ["two_stage_output"] = false,']
    for key, value in options.render_values(scene.get('render_settings', {})).items():
        lines.append('  [%s] = %d,' % (string(key), value))
    lines.append('}')
    if output_file:
        selected = scene.get('aovs', ['alpha'])
        if any(key not in options.AOVS for key in selected):
            raise ValueError('Unknown AOV')
        outputs = [('beauty', {'result': 0}, '')]
        outputs += [(key, options.AOVS[key][1], options.AOVS[key][2]) for key in dict.fromkeys(selected)]
        for key, attributes, channel in outputs:
            lines += ['RenderOutput(%s) {' % string('/modo/aov/' + key),
                      '  ["file_name"] = %s,' % string(str(output_file)),
                      '  ["channel_name"] = %s,' % string(channel),
                      '  ["channel_format"] = 0,', '  ["compression"] = 1,']
            lines += ['  [%s] = %s,' % (string(attr), string(value) if isinstance(value, str) else number(value))
                      for attr, value in attributes.items()]
            lines.append('}')
    return '\n'.join(lines) + '\n'
