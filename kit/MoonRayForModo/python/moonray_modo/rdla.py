"""Pure Python scene serializer. Does not import or change the Modo scene."""
import math
from . import options, textures, __version__

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


def node_matrix(node):
    first = matrix(node.get('matrix',IDENTITY))
    return 'blur(%s, %s)' % (first,matrix(node['matrix_close'])) if 'matrix_close' in node else first


def array(values):
    return '{' + ', '.join(values) + '}'


def scene_text(scene, width=640, height=360, samples=2, environment=0.15, output_file=None):
    """Serialize a snapshot to an RDLA scene. samples is MoonRay's grid side."""
    if not 16 <= int(width) <= 16384 or not 16 <= int(height) <= 16384:
        raise ValueError("Image dimensions must be between 16 and 16384")
    if not 1 <= int(samples) <= 64:
        raise ValueError("Pixel sample grid must be between 1 and 64")
    camera = scene['camera']
    dof = bool(camera.get('dof', False))
    if dof and (camera.get('f_stop', 4) <= 0 or camera.get('focus_distance', 4) <= 0):
        raise ValueError('Depth of field requires positive f-stop and focus distance')
    orthographic = camera.get('projection','persp') == 'ortho'
    if not orthographic and (camera['focal_mm']<=0 or camera.get('focal_mm_close',camera['focal_mm'])<=0):
        raise ValueError('Camera focal length must be positive at both shutter endpoints')
    if orthographic and camera.get('ortho_width',1)<=0:
        raise ValueError('Orthographic width must be positive')
    if camera.get('pixel_aspect',1)<=0:
        raise ValueError('Camera pixel aspect must be positive')
    film_offset=camera.get('film_offset',[0,0])
    if len(film_offset)!=2:
        raise ValueError('Camera film offset must have two components')
    focal = number(camera['focal_mm']) if not orthographic else None
    if not orthographic and 'focal_mm_close' in camera:
        focal='blur(%s, %s)' % (focal,number(camera['focal_mm_close']))
    lines = ['-- MoonRayForModo %s; scene units are meters' % __version__,
             'local camera = %s("/modo/camera") {' % ('OrthographicCamera' if orthographic else 'PerspectiveCamera'),
             '  ["node_xform"] = %s,' % node_matrix(camera),
             *([] if orthographic else ['  ["focal"] = %s,' % focal]),
             '  ["horizontal_film_offset"] = %s,' % number(film_offset[0]),
             '  ["vertical_film_offset"] = %s,' % number(film_offset[1]),
             '  ["pixel_aspect_ratio"] = %s,' % number(camera.get('pixel_aspect',1)),
             '  ["film_width_aperture"] = %s,' % number(camera.get('ortho_width',1) if orthographic else camera['film_mm']),
             '  ["dof"] = %s,' % ('true' if dof else 'false'),
             '  ["dof_aperture"] = %s,' % number(camera.get('f_stop', 4)),
             '  ["dof_focus_distance"] = %s,' % number(camera.get('focus_distance', 4)),
             '  ["bokeh"] = %s,' % ('true' if camera.get('iris_blades', 0) >= 3 else 'false'),
             '  ["bokeh_sides"] = %d,' % max(0, int(camera.get('iris_blades', 0))),
             '  ["bokeh_angle"] = %s,' % number(math.degrees(camera.get('iris_rotation', 0))),
             '  ["mb_shutter_open"] = %s,' % number(scene.get('motion_steps',[-.25,.25])[0]),
             '  ["mb_shutter_close"] = %s,' % number(scene.get('motion_steps',[-.25,.25])[-1]),
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
                  '  ["node_xform"] = %s,' % node_matrix(light),
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
    from .environments import emit as emit_environments
    emit_environments(scene.get('environments', []), lines)
    lines.append('local lightSet = LightSet("/modo/lightSet")(lights)')
    # Keep material handles in a table to avoid Lua's local variable limit.
    lines.append('local materials = {}')
    materials = dict(scene.get('materials', {}))
    materials.setdefault('', {'color': [0.5, 0.5, 0.5], 'roughness': 0.4, 'metallic': 0})
    from . import absorption
    media = {tag:absorption.medium(material) for tag,material in materials.items()}
    native_index = [1000000000]
    for index, (tag, material) in enumerate(sorted(materials.items())):
        if material.get('material_stack'):
            from .moonshine import emit_stack
            emit_stack([absorption.surface(child) for child in material['material_stack']],tag,index,lines,scene.get('native_materials',{}),native_index)
            continue
        if material.get('node_graph'):
            from .nodes import emit as emit_graph
            ref=emit_graph(material,'/modo/nodes/%s'%index,native_index,lines,scene.get('native_materials',{}))
            lines.append('materials[%s] = %s'%(string(tag),ref))
            continue
        if material.get('native_shader'):
            from .shader_library import emit as emit_native
            ref = emit_native(material,'/modo/native/%s'%index,native_index,lines,scene.get('native_materials',{}))
            lines.append('materials[%s] = %s'%(string(tag),ref))
            continue
        material = absorption.surface(material)
        bindings = {}
        from .textures import EFFECT_ALIASES
        effects = {EFFECT_ALIASES.get(key,key) for key in material.get('textures', {})} | {
            EFFECT_ALIASES.get(layer['effect'], layer['effect']) for layer in (material.get('layers') or [])}
        glass = (material.get('transmission', 0) > 0 or material.get('presence', 1) < 1 or
                 'dissolve' in effects or any(k.startswith('tran') for k in effects))
        from .graph import bindings as graph_bindings
        moonshine = material.get('shader') == 'DwaBaseMaterial' or bool({'aniso','subsCol','subsAmt'} & effects) or material.get('subsurface_amount',0)>0
        if moonshine:
            material = dict(material,shader='DwaBaseMaterial')
        bindings = graph_bindings(material, index, lines, glass and not moonshine)
        if moonshine:
            from .moonshine import emit
            emit(material, tag, index, bindings, lines)
            continue
        bindings.pop('layerMask',None)
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
    lines.append('local volumes = {}')
    for index,(tag,material) in enumerate(sorted(media.items())):
        if material is not None:
            distance = material['absorption_distance']
            sigma = [-math.log(max(1e-6,min(1,float(c))))/distance for c in material.get('transmission_color',[1,1,1])]
            attenuation = vector(sigma,'Rgb')
            color_layers = absorption.color_layers(material)
            color_maps = {k:v for k,v in material.get('textures',{}).items() if textures.EFFECT_ALIASES.get(k,k)=='tranCol'}
            if any(absorption.effect(v)=='tranCol' for v in color_layers) or color_maps:
                from .graph import bindings as volume_bindings
                mapped = volume_bindings(dict(material,layers=color_layers if 'layers' in material else None,textures=color_maps),900000000+index,lines)
                name = '/modo/absorption/map/%d'%index
                lines += ['ModoTextureMap(%s) { ["mode"] = 4, ["foreground"] = %s, ["distance"] = %s }' %
                          (string(name),mapped['transmissionColor'],number(distance))]
                attenuation = 'bind(ModoTextureMap(%s), Rgb(1,1,1))'%string(name)
            lines += ['volumes[%s] = BaseVolume(%s) {' % (string(tag),string('/modo/absorption/%d'%index)),
                      '  ["diffuse_color"] = Rgb(0,0,0),',
                      '  ["attenuation_color"] = %s,' % attenuation,
                      '  ["attenuation_intensity"] = 1,', '  ["attenuation_factor"] = 1,',
                      '  ["match_diffuse"] = false,', '  ["invert_attenuation_color"] = false,', '}']
    lines += ['local function assign(g, part, tag)',
              '  local a = {g, part, materials[tag], lightSet}',
              '  if volumes[tag] then table.insert(a, volumes[tag]) end',
              '  table.insert(assignments, a)', 'end']
    from . import geometry
    for index, mesh in enumerate(scene.get('meshes', [])):
        mesh=geometry.prepare(mesh)
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
        user_data = []
        for uv_index, (uv_name, values) in enumerate(sorted(mesh.get('uv_sets', {}).items())):
            if len(values) != sum(map(len, faces)):
                raise ValueError('Named UV set must match polygon corners: '+uv_name)
            name = '/modo/mesh/%d/uv/%d' % (index,uv_index)
            lines += ['UserData(%s) {' % string(name),
                      '  ["vec2f_key"] = %s,' % string(uv_name),
                      '  ["rate"] = 6,',
                      '  ["vec2f_values_0"] = %s,' % array(vector(v,'Vec2') for v in values), '}']
            user_data.append('UserData(%s)' % string(name))
        lines += ['do', '  local geometry = RdlMeshGeometry("/modo/mesh/%s") {' % index,
                  '    ["node_xform"] = %s,' % node_matrix(mesh),
                  '    ["vertex_list_0"] = %s,' % array(vector(v) for v in vertices),
                  '    ["vertices_by_index"] = %s,' % array(str(v) for f in faces for v in f),
                  '    ["face_vertex_count"] = %s,' % array(str(len(f)) for f in faces),
                  '    ["is_subd"] = %s,' % ('true' if subdivision else 'false'),
                  *(['    ["mesh_resolution"] = %d,' % mesh.get('mesh_resolution',2 ** level)] if subdivision else []),
                  *(['    ["adaptive_error"] = %s,' % number(mesh['adaptive_error'])] if subdivision and 'adaptive_error' in mesh else []),
                  '    ["smooth_normal"] = %s,' % ('true' if mesh.get('smooth', True) else 'false')]
        if 'vertices_close' in mesh:
            if len(mesh['vertices_close']) != len(vertices):
                raise ValueError('Motion samples must have equal vertex counts')
            lines.append('    ["vertex_list_1"] = %s,' % array(vector(v) for v in mesh['vertices_close']))
        if user_data:
            lines.append('    ["primitive_attributes"] = %s,' % array(user_data))
        creases = mesh.get('creases', [])
        if creases:
            if not subdivision:
                raise ValueError('Creases require subdivision geometry')
            for a,b,sharpness in creases:
                if type(a) is not int or type(b) is not int or a == b or min(a,b)<0 or max(a,b)>=len(vertices) or sharpness<0:
                    raise ValueError('Invalid subdivision crease')
            lines += ['    ["subd_crease_indices"] = %s,' % array(str(v) for edge in creases for v in edge[:2]),
                      '    ["subd_crease_sharpnesses"] = %s,' % array(number(edge[2]) for edge in creases)]
        if 'visibility' in mesh:
            camera_v, indirect, reflection, refraction, subscatter, shadow = mesh['visibility']
            for attribute, value in [('visible_in_camera', camera_v), ('visible_shadow', shadow),
                    ('visible_diffuse_reflection', indirect), ('visible_diffuse_transmission', indirect),
                    ('visible_glossy_reflection', reflection), ('visible_mirror_reflection', reflection),
                    ('visible_glossy_transmission', refraction), ('visible_mirror_transmission', refraction)]:
                lines.append('    [%s] = %s,' % (string(attribute), 'true' if value else 'false'))
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
                lines.append('  assign(geometry, %s, %s)' %
                             (string('part%d' % part_index), string(face_tag)))
        else:
            lines.append('  assign(geometry, "", %s)' % string(tag))
        if 'instances' in mesh:
            if mesh['instances']:
                lines += ['  local instances = RdlInstancerGeometry("/modo/instances/%s") {' % index,
                          '    ["method"] = 2,',
                          '    ["references"] = {geometry},',
                          '    ["use_reference_xforms"] = false,',
                          '    ["use_reference_attributes"] = true,',
                          '    ["xform_list"] = %s,' % array(matrix(m) for m in mesh['instances']),
                          '  }', '  table.insert(geometries, instances)',
                          '  assign(instances, "", %s)' % string(tag)]
        else:
            lines.append('  table.insert(geometries, geometry)')
        lines.append('end')
    lines += ['GeometrySet("/modo/geometrySet")(geometries)',
              'local layer = Layer("/modo/layer")(assignments)', 'SceneVariables {',
              '  ["camera"] = camera,', '  ["layer"] = layer,',
              '  ["scene_scale"] = 1,',
              '  ["image_width"] = %d,' % int(width), '  ["image_height"] = %d,' % int(height),
              '  ["pixel_samples"] = %d,' % int(samples),
              '  ["enable_motion_blur"] = %s,' % ('true' if scene.get('motion_steps') else 'false'),
              '  ["motion_steps"] = %s,' % array(number(v) for v in scene.get('motion_steps',[-.25,.25])),
              '  ["enable_dof"] = %s,' % ('true' if dof else 'false'),
              # Renderer already writes into its private temp folder and atomically
              # publishes the finished EXR; avoid a second OS-specific staging layer.
              '  ["two_stage_output"] = false,']
    for key, value in options.render_values(scene.get('render_settings', {})).items():
        lines.append('  [%s] = %s,' % (string(key), number(value)))
    region = scene.get('region')
    if region is not None:
        if len(region) != 4 or any(not math.isfinite(float(v)) for v in region):
            raise ValueError('Render region requires four finite bounds')
        left, top, right, bottom = map(float, region)
        if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
            raise ValueError('Render region must have positive width/height within the image')
        # UI bounds use top-left coordinates, native sub_viewport uses bottom-left.
        bounds = [math.floor(left*width), math.floor((1-bottom)*height),
                  math.ceil(right*width), math.ceil((1-top)*height)]
        lines.append('  ["sub_viewport"] = %s,' % array(str(v) for v in bounds))
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
    preview_key = scene.get('preview_buffer','beauty')
    if not output_file and scene.get('preview_buffer_file'):
        if preview_key!='beauty' and preview_key not in options.AOVS: raise ValueError('Unknown preview buffer')
        buffer_file = scene.get('preview_buffer_file')
        if not buffer_file: raise ValueError('Missing preview buffer output path')
        lines += ['RenderOutput("/modo/preview/buffer") {',
                  '  ["file_name"] = %s,' % string(str(buffer_file)),
                  '  ["channel_format"] = 0,', '  ["compression"] = 1,']
        attributes = {'result':0} if preview_key=='beauty' else options.AOVS[preview_key][1]
        for attr,value in attributes.items():
            lines.append('  [%s] = %s,' % (string(attr),string(value) if isinstance(value,str) else number(value)))
        lines.append('}')
    for key,path in scene.get('_denoise_guides',{}).items():
        attributes={'result':7,'material_aov':'albedo'} if key=='albedo' else {'result':3,'state_variable':2}
        lines += ['RenderOutput(%s) {' % string('/modo/denoise/'+key),
                  '  ["file_name"] = %s,' % string(path), '  ["channel_format"] = 0,', '  ["compression"] = 1,']
        for attr,value in attributes.items(): lines.append('  [%s] = %s,' % (string(attr),string(value) if isinstance(value,str) else number(value)))
        lines.append('}')
    return '\n'.join(lines) + '\n'
