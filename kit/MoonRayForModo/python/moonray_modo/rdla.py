"""Pure Python scene serializer. Does not import or change the Modo scene."""
import math
from . import options, textures, outputs, __version__

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
    expected = 2 if kind == 'Vec2' else (4 if kind in ('Vec4', 'Rgba') else 3)
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


def many_vectors(values,kind):
    """A long list of vectors as text, written without a step of Python for each number: a heavy mesh has millions.
    The same text as vector() gives for each. Anything out of the ordinary is left to vector(), which says what is wrong."""
    from itertools import chain
    size = 2 if kind == 'Vec2' else (4 if kind in ('Vec4', 'Rgba') else 3)
    try:
        # One sum finds a number that is not finite, or a vector of the wrong size, among them all.
        if sum(map(len, values)) != size * len(values) or not math.isfinite(math.fsum(chain.from_iterable(values))):
            return None
        template = kind + '(' + ', '.join(['%.12g'] * size) + ')'
        return '{' + ', '.join(map(template.__mod__, map(tuple, values))) + '}'
    except (TypeError, ValueError, OverflowError):
        return None


def vector_array(values,kind='Vec3'):
    from .serialization import array as cached
    def write():
        whole = many_vectors(values,kind) if len(values) > 1000 else None
        return whole if whole is not None else array(vector(v,kind) for v in values)
    return cached(kind,values,write)

def mesh_array(values,counts=False):
    from .serialization import array as cached
    from itertools import chain
    # map and chain run through a heavy mesh's faces without a step of Python for each corner.
    return cached('counts' if counts else 'indices',values,lambda:array(map(str,map(len,values))) if counts else array(map(str,chain.from_iterable(values))))

# Meshes cut apart by apart(), kept by the lists they were cut from: the pieces' own lists must stay the same from one
# render to the next for their text to be reused.
_APART = {}


def apart(meshes, filled):
    """Give every part of a mesh that holds a volume a mesh of its own.

    MoonRay stops (an access violation as the render begins) when a volume is assigned to one part of a mesh of
    several parts, as when one glass ball with an absorption depth shares a mesh with other balls. A mesh that is
    all one material with that volume renders, so each such part is written out as that. filled is the set of
    material tags that carry a volume."""
    result = []
    for mesh in meshes:
        tags = mesh.get('face_materials')
        inside = sorted({tag for tag in tags if tag in filled}) if tags else []
        if not inside or len(set(tags)) < 2 or len(tags) != len(mesh['faces']):
            result.append(mesh)
            continue
        key = (id(mesh['faces']), id(tags), id(mesh['vertices']), tuple(inside))
        held = _APART.get(key)
        if held is None or held[0] is not mesh['faces'] or held[1] is not tags or held[2] is not mesh['vertices']:
            if len(_APART) >= 64:
                _APART.pop(next(iter(_APART)))
            held = _APART[key] = (mesh['faces'], tags, mesh['vertices'], _pieces(mesh, inside))
        for own, changed in held[3]:
            result.append(dict(mesh, **changed) if own is None else dict({k: v for k, v in mesh.items() if k != 'face_materials'}, **changed))
    return result


def _pieces(mesh, inside):
    """What changes in a mesh for each piece of it: first what is left, then one piece for each tag in inside."""
    faces, tags = mesh['faces'], mesh['face_materials']
    starts, total = [], 0
    for face in faces:
        starts.append(total)
        total += len(face)
    corner_lists = {key: mesh[key] for key in ('uvs', 'normals') if mesh.get(key) and len(mesh[key]) == total}
    sets = {key: values for key, values in (mesh.get('uv_sets') or {}).items() if len(values) == total}

    def piece(chosen, own):
        # Only the points the piece uses, renumbered: a subdivision surface must not be handed points no face holds.
        order, used = {}, []
        cut = []
        for index in chosen:
            face = []
            for vertex in faces[index]:
                if vertex not in order:
                    order[vertex] = len(used)
                    used.append(vertex)
                face.append(order[vertex])
            cut.append(face)
        corners = [corner for index in chosen for corner in range(starts[index], starts[index] + len(faces[index]))]
        changed = {'faces': cut, 'vertices': [mesh['vertices'][v] for v in used]}
        if 'vertices_close' in mesh and len(mesh['vertices_close']) == len(mesh['vertices']):
            changed['vertices_close'] = [mesh['vertices_close'][v] for v in used]
        for key, values in corner_lists.items():
            changed[key] = [values[c] for c in corners]
        if mesh.get('uv_sets') is not None:
            changed['uv_sets'] = {key: [values[c] for c in corners] for key, values in sets.items()}
        if mesh.get('creases'):
            changed['creases'] = [(order[a], order[b], sharpness) for a, b, sharpness in mesh['creases'] if a in order and b in order]
        if own is None:
            changed['face_materials'] = [tags[index] for index in chosen]
        else:
            # One material throughout, and a name of its own among the scene's shapes.
            changed.update(material=own, identity=str(mesh.get('identity', mesh.get('name', ''))) + '|volume|' + own)
        return own, changed
    rest = [index for index, tag in enumerate(tags) if tag not in inside]
    made = [piece(rest, None)] if rest else []
    return made + [piece([index for index, tag in enumerate(tags) if tag == own], own) for own in inside]


def scene_text(scene, width=640, height=360, samples=2, environment=0.15, output_file=None):
    from .serialization import revision
    from .scene_references import configuration as reference_configuration
    from .working_space import configuration as working_configuration
    with working_configuration(scene.get('asset_settings',{})),reference_configuration(scene),textures.configuration(scene.get("asset_settings",{})),revision(scene.get("_geometry_revision")):
        return _scene_text(scene,width,height,samples,environment,output_file)

def _scene_text(scene, width=640, height=360, samples=2, environment=0.15, output_file=None):
    """Serialize a snapshot to an RDLA scene. samples is MoonRay's grid side."""
    if not 16 <= int(width) <= 16384 or not 16 <= int(height) <= 16384:
        raise ValueError("Image dimensions must be between 16 and 16384")
    if not 1 <= int(samples) <= 64:
        raise ValueError("Pixel sample grid must be between 1 and 64")
    from . import entities
    # A MeshLight item makes the mesh it names emit, through the same settings as Object controls.
    scene = entities.mesh_lights(scene)
    if entities.replaces_environment(scene):
        # A MoonRay environment light set to replace Modo's: neither the Modo environments nor
        # the preview environment light are written.
        scene = dict(scene, environments=[])
        environment = 0
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
    entity_camera=entities.render_camera(scene)
    if entity_camera:
        # A MoonRay camera item set to render takes the place of the Modo camera.
        lines[1:lines.index('}')+1]=entities.camera_lines(scene,entity_camera)
    from . import geometry, lighting
    from . import cryptomatte
    crypto=bool((output_file or scene.get('preview_buffer_files')) and cryptomatte.enabled(scene))
    render_meshes=list(geometry.render_meshes(scene.get('meshes',[]),expand_instances=True if scene.get('native_light_links',{}).get('lights') else {identity for identity,v in scene.get('production',{}).get('objects',{}).items() if v.get('link_enabled') or v.get('shadow_exclude') or v.get('mesh_light')}))
    multi_crypto=crypto and cryptomatte.multiple(scene)
    if multi_crypto and not scene.get('_crypto_categories'):
        raise ValueError('Multiple Cryptomatte categories require a matching category-enabled runtime')
    if multi_crypto and any(g.get('kind')=='vdb' for g in scene.get('extra_geometry',[])):
        raise ValueError('Volume Cryptomatte coverage is not implemented; disable Cryptomatte or exclude volumes')
    if output_file:
        cryptomatte.metadata(render_meshes+scene.get('extra_geometry',[]),lines,crypto and not multi_crypto,scene)
        if multi_crypto:
            for cat in ('object','material','asset'):
                cryptomatte.metadata(render_meshes+scene.get('extra_geometry',[]),lines,True,scene,cat)
    lighting.emit(scene,render_meshes,float(environment),lines)
    # Keep material handles in a table to avoid Lua's local variable limit.
    lines.append('local materials = {}')
    materials = dict(scene.get('materials', {}))
    materials.setdefault('', {'color': [0.5, 0.5, 0.5], 'roughness': 0.4, 'metallic': 0})
    from . import absorption
    from .clay import material as clay_material
    clay=clay_material(scene.get('_clay_preview'))
    media = {tag:None if clay else absorption.medium(material) for tag,material in materials.items()}
    native_index = [1000000000]
    for index, (tag, material) in enumerate(sorted(materials.items())):
        if clay:material=dict(clay)
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
        moonshine = glass or material.get('dispersion_abbe',0)>0 or material.get('shader') == 'DwaBaseMaterial' or bool({'aniso','subsCol','subsAmt','normalCoat','coatBump','diffRough'} & effects) or material.get('subsurface_amount',0)>0 or material.get('diffuse_roughness',0)>0
        if moonshine:
            material = dict(material,shader='DwaBaseMaterial')
        bindings = graph_bindings(material, index, lines, glass and not moonshine)
        if moonshine:
            from .moonshine import emit
            emit(material, tag, index, bindings, lines)
            continue
        bindings.pop('layerMask',None)
        from .working_space import color as working_color,surface as working_surface
        material=dict(material)
        for key in ('color','emission','specular','transmission_color'):
            if key in material:material[key]=working_color(material[key])
        bindings=working_surface(bindings,'/modo/material/'+str(index),lines,{'diffuseColor','specularColor','emissiveColor','transmissionColor'})
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
    displacement_tags=set()
    lines.append('local displacements = {}')
    for index,(tag,material) in enumerate(sorted(materials.items())):
        # The topmost explicit displacement assignment wins across material layers.
        source=next((m for m in reversed(material.get('material_stack',[material])) if m.get('node_graph',{} ) and m['node_graph'].get('displacement')),None)
        if source:
            from .nodes import emit as emit_graph
            ref=emit_graph(source,'/modo/displacement/%d'%index,native_index,lines,scene.get('native_materials',{}),output='displacement')
            lines.append('displacements[%s] = %s'%(string(tag),ref));displacement_tags.add(tag)
    lines.append('local volumes = {}')
    for index,(tag,material) in enumerate(sorted(media.items())):
        if material is not None:
            if material.get('stack_medium'):
                from .material_groups import merged
                from .graph import bindings as volume_bindings
                attenuation=volume_bindings(merged(material['stack_medium']),900000000+index,lines,absorption=True)['transmissionColor']
            else:
                distance = material['absorption_distance']
                from .working_space import color as working_color
                sigma = [-math.log(max(1e-6,min(1,float(c))))/distance for c in working_color(material.get('transmission_color',[1,1,1]))]
                attenuation = vector(sigma,'Rgb')
                color_layers = absorption.color_layers(material)
                color_maps = {k:v for k,v in material.get('textures',{}).items() if textures.EFFECT_ALIASES.get(k,k)=='tranCol'}
                if any(absorption.effect(v)=='tranCol' for v in color_layers) or color_maps:
                    from .graph import bindings as volume_bindings
                    mapped = volume_bindings(dict(material,layers=color_layers if 'layers' in material else None,textures=color_maps),900000000+index,lines)
                    from .working_space import expression as working_expression
                    mapped['transmissionColor']=working_expression(mapped['transmissionColor'],'/modo/absorption/working/'+str(index),lines)
                    name = '/modo/absorption/map/%d'%index
                    lines += ['ModoTextureMap(%s) { ["mode"] = 4, ["foreground"] = %s, ["distance"] = %s }' %
                              (string(name),mapped['transmissionColor'],number(distance))]
                    attenuation = 'bind(ModoTextureMap(%s), Rgb(1,1,1))'%string(name)
            lines += ['volumes[%s] = BaseVolume(%s) {' % (string(tag),string('/modo/absorption/%d'%index)),
                      '  ["diffuse_color"] = Rgb(0,0,0),',
                      '  ["attenuation_color"] = %s,' % attenuation,
                      '  ["attenuation_intensity"] = 1,', '  ["attenuation_factor"] = 1,',
                      '  ["match_diffuse"] = false,', '  ["invert_attenuation_color"] = false,', '}']
    lines += ['local function assign(g, part, tag, owner)',
              '  local a = {g, part, materials[tag], objectLightSets[owner] or (nativeLightSets[owner] and nativeLightSets[owner][tag]) or lightSet}',
              '  if objectShadowSets[owner] then table.insert(a, objectShadowSets[owner]) end',
              '  if displacements[tag] then table.insert(a, displacements[tag]) end',
              '  if volumes[tag] then table.insert(a, volumes[tag]) end',
              '  table.insert(assignments, a)', 'end']
    from . import geometry
    render_meshes = apart(render_meshes, {tag for tag, medium in media.items() if medium is not None})
    for index, mesh in enumerate(render_meshes):
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
        displaced=bool(({tag}|set(parts)) & displacement_tags)
        if displaced and not mesh.get('subdivision'):
            settings=options.object_values(mesh.get('geometry_settings',{}))
            mesh=dict(mesh,adaptive_error=settings['adaptive_error'])
        level = mesh.get('subdivision_level', 3)
        if type(level) is not int or not 1 <= level <= 5:
            raise ValueError('Subdivision level must be an integer between 1 and 5')
        user_data = cryptomatte.userdata_set(mesh,lines,scene) if crypto else []
        named_uvs=dict(mesh.get('uv_sets',{}))
        if named_uvs:
            if not mesh.get('uvs'):
                from .coordinates import fallback_uvs
                mesh=dict(mesh,uvs=fallback_uvs(faces))
            named_uvs['modo_primary_uv']=mesh['uvs']
        for uv_index, (uv_name, values) in enumerate(sorted(named_uvs.items())):
            if len(values) != sum(map(len, faces)):
                raise ValueError('Named UV set must match polygon corners: '+uv_name)
            name = '/modo/mesh/%d/uv/%d' % (index,uv_index)
            lines += ['UserData(%s) {' % string(name),
                      '  ["vec2f_key"] = %s,' % string(uv_name),
                      '  ["rate"] = 6,',
                      '  ["vec2f_values_0"] = %s,' % vector_array(values,'Vec2'), '}']
            user_data.append('UserData(%s)' % string(name))
        from . import primitive_attributes
        instance_values = []
        if mesh.get('instance_attributes') and len(mesh['instance_attributes']) == len(mesh.get('instances') or []):
            # One value for each instance, on the instancer.
            instance_values = primitive_attributes.emit('/modo/instances/%s/attribute' % index, mesh['instance_attributes'], lines)
        elif mesh.get('attributes') and 'instances' not in mesh:
            user_data += primitive_attributes.emit('/modo/mesh/%s/attribute' % index, [mesh['attributes']], lines)
        lines += ['do', '  local geometry = RdlMeshGeometry("/modo/mesh/%s") {' % index,
                  '    ["node_xform"] = %s,' % node_matrix(mesh),
                  '    ["vertex_list_0"] = %s,' % vector_array(vertices),
                  '    ["vertices_by_index"] = %s,' % mesh_array(faces),
                  '    ["face_vertex_count"] = %s,' % mesh_array(faces,True),
                  '    ["is_subd"] = %s,' % ('true' if subdivision else 'false'),
                  *(['    ["mesh_resolution"] = %d,' % mesh.get('mesh_resolution',2 ** level)] if subdivision or displaced else []),
                  *(['    ["adaptive_error"] = %s,' % number(mesh['adaptive_error'])] if (subdivision or displaced) and 'adaptive_error' in mesh else []),
                  '    ["smooth_normal"] = %s,' % ('true' if mesh.get('smooth', True) else 'false')]
        if 'vertices_close' in mesh:
            if len(mesh['vertices_close']) != len(vertices):
                raise ValueError('Motion samples must have equal vertex counts')
            lines.append('    ["vertex_list_1"] = %s,' % vector_array(mesh['vertices_close']))
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
                lines.append('    [%s] = %s,' % (string(attribute), vector_array(values,kind)))
        if parts:
            lines += ['    ["part_list"] = %s,' % array(string('part%d' % i) for i in range(len(parts))),
                      '    ["part_face_count_list"] = %s,' % array(str(len(v)) for v in parts.values()),
                      '    ["part_face_indices"] = %s,' % array(str(f) for v in parts.values() for f in v)]
        lines += ['  }']
        if scene.get('production',{}).get('objects',{}).get(lighting.owner(mesh),{}).get('mesh_light'):
            # MoonRay refuses a MeshLight whose geometry is also in the layer, so the light gets its own copy.
            opening=len(lines)-1-lines[::-1].index('  local geometry = RdlMeshGeometry("/modo/mesh/%s") {' % index)
            lines += ['  RdlMeshGeometry("/modo/meshLight/geometry/%s") {' % index]+lines[opening+1:]
        if parts:
            for part_index, face_tag in enumerate(parts):
                lines.append('  assign(geometry, %s, %s, %s)' %
                             (string('part%d' % part_index), string(face_tag),string(lighting.owner(mesh))))
        else:
            lines.append('  assign(geometry, "", %s, %s)' % (string(tag),string(lighting.owner(mesh))))
        if mesh.get('instance_transform_motion') and mesh.get('instances'):
            from .instance_motion import emit as emit_instance_motion
            emit_instance_motion(mesh,index,tag,scene,crypto,lines)
        elif 'instances' in mesh:
            if mesh['instances']:
                instance_crypto=cryptomatte.instance_userdata(mesh,lines,scene) if crypto else None
                lines += ['  local instances = RdlInstancerGeometry("/modo/instances/%s") {' % index,
                          *(['    ["primitive_attributes"] = {%s},'%', '.join(([instance_crypto] if instance_crypto else [])+instance_values)] if instance_crypto or instance_values else []),
                          '    ["method"] = 2,',
                          '    ["references"] = {geometry},',
                          '    ["use_reference_xforms"] = false,',
                          '    ["use_reference_attributes"] = true,',
                          '    ["xform_list"] = %s,' % array(matrix(m) for m in mesh['instances']),
                          *(['    ["velocities"] = %s,'%array(vector(v) for v in mesh['instance_velocities']),
                             '    ["evaluation_frame"] = %s,'%number(mesh['instance_evaluation_frame'])] if 'instance_velocities' in mesh else []),
                          '  }', '  table.insert(geometries, instances)',
                          '  assign(instances, "", %s, %s)' % (string(tag),string(lighting.owner(mesh)))]
        else:
            lines.append('  table.insert(geometries, geometry)')
        lines.append('end')
    from .extra_geometry import emit as emit_extra
    emit_extra(scene,materials,lines,crypto)
    entities.emit_geometry(scene,materials,lines)
    lines += ['GeometrySet("/modo/geometrySet")(geometries)',
              'local layer = Layer("/modo/layer")(assignments)', 'SceneVariables {',
              '  ["camera"] = camera,', '  ["layer"] = layer,',
              '  ["scene_scale"] = 1,',
              '  ["fps"] = %s,'%number(scene.get('fps',24)),
              '  ["texture_cache_size"] = %d,'%max(64,min(131072,int(scene.get('asset_settings',{}).get('texture_cache_mb',4000)))),
              '  ["image_width"] = %d,' % int(width), '  ["image_height"] = %d,' % int(height),
              '  ["pixel_samples"] = %d,' % int(samples),
              '  ["enable_motion_blur"] = %s,' % ('true' if scene.get('motion_steps') else 'false'),
              '  ["motion_steps"] = %s,' % array(number(v) for v in scene.get('motion_steps',[-.25,.25])),
              '  ["enable_dof"] = %s,' % ('true' if dof else 'false'),
              # Renderer already writes into its private temp folder and atomically
              # publishes the finished EXR; avoid a second OS-specific staging layer.
              '  ["two_stage_output"] = false,']
    if crypto:lines.append('  ["deep_id_attribute_names"] = '+array(string('modo_'+cat+'_id') for cat in (('object','material','asset') if multi_crypto else ('object',)))+',')
    for key, value in options.render_values(scene.get('render_settings', {})).items():
        if key in options.BOOLS:
            lines.append('  [%s] = %s,' % (string(key), 'true' if value else 'false'))
        elif key not in ('batch_tile_order','bucket_size'):
            lines.append('  [%s] = %s,' % (string(key), number(value)))
        if key=='batch_tile_order':
            lines.extend('  [%s] = %s,'%(string(name),number(value)) for name in ('progressive_tile_order','checkpoint_tile_order'))
    recovery=scene.get('_recovery') if output_file else None
    if recovery:
        lines += ['  ["checkpoint_active"] = true,','  ["resumable_output"] = true,','  ["checkpoint_bg_write"] = false,',
                  '  ["checkpoint_interval"] = %s,'%number(recovery['minutes']),
                  '  ["resume_render"] = %s,'%('true' if recovery['resume'] else 'false')]
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
    # Scene variables the scene holds beyond the plugin's own settings, as a scene brought in from MoonRay does: each
    # has the last word over what the plugin would have written for it.
    for key, value in sorted((scene.get('scene_variables') or {}).items()):
        if not isinstance(key, str) or not key.replace('_', '').isalnum() or not isinstance(value, (bool, int, float)):
            continue
        opening = len(lines) - 1 - lines[::-1].index('SceneVariables {')
        lines[opening:] = [line for line in lines[opening:] if not line.startswith('  [%s] = ' % string(key))]
        lines.append('  [%s] = %s,' % (string(key), ('true' if value else 'false') if isinstance(value, bool) else str(value) if isinstance(value, int) else number(value)))
    lines.append('}')
    if output_file:
        selected = scene.get('aovs', ['alpha'])
        if any(key not in options.AOVS for key in selected):
            raise ValueError('Unknown AOV')
        render_outputs = [('beauty', {'result': 0}, '')]
        render_outputs += [(key, options.AOVS[key][1], options.AOVS[key][2]) for key in dict.fromkeys(selected)]
        if crypto:render_outputs.append(('object_id',{'result':4,'primitive_attribute':'modo_object_id','primitive_attribute_type':0},'modo_object_id'))
        render_outputs += [(v['name'],outputs.attributes(v,multi_crypto),v['name']) for v in outputs.values(scene.get('custom_aovs',[]))]
        if recovery:
            # MoonRay needs sample weights and odd-sample beauty/alpha to resume.
            # Keep these in the primary EXR part alongside the regular beauty AOV.
            present={attrs.get('result') for _,attrs,_ in render_outputs}
            for name,result in (('weight',11),('beauty_aux',12),('alpha_aux',14)):
                if result not in present:
                    render_outputs.append(('__recovery_'+name,{'result':result},'__recovery_'+name))
            # OIIO invents names for unnamed multipart EXRs. MoonRay's resume
            # reader requires exact part names, so name the primary part explicitly.
            used_parts={attrs.get('file_part','') for _,attrs,_ in render_outputs}
            primary_part='__modo_main'
            while primary_part in used_parts:primary_part+='_'
            render_outputs=[(name,dict(attrs,file_part=attrs.get('file_part') or primary_part),channel)
                            for name,attrs,channel in render_outputs]
        from .recovery import attributes as recovery_attributes
        for key, attributes, channel in render_outputs:
            crypto_category=next((v.get('category','object') for v in scene.get('custom_aovs',[]) if v.get('name')==key and v.get('kind')=='cryptomatte'),None)
            metadata_path='/modo/outputMetadata'+('/'+crypto_category if multi_crypto and crypto_category else '')
            attributes=dict(attributes,**recovery_attributes(recovery))
            attributes=dict(channel_format=0,**attributes) if 'channel_format' not in attributes else attributes
            lines += ['RenderOutput(%s) {' % string('/modo/aov/' + key),
                      '  ["file_name"] = %s,' % string(str(output_file)),
                      *(['  ["channel_name"] = %s,' % string(channel)] if 'channel_name' not in attributes else []),
                      '  ["exr_header_attributes"] = Metadata('+string(metadata_path)+'),',
                      '  ["compression"] = 1,']
            lines += ['  [%s] = %s,' % (string(attr), string(value) if isinstance(value,str) else ('true' if value else 'false') if isinstance(value,bool) else number(value))
                      for attr, value in attributes.items()]
            lines.append('}')
    preview_files=scene.get('preview_buffer_files',{})
    if not preview_files and scene.get('preview_buffer_file'):
        preview_files={scene.get('preview_buffer','beauty'):scene['preview_buffer_file']}
    if not output_file:
        for key,path in preview_files.items():
            available=outputs.preview(scene)
            if key not in available:raise ValueError('Unknown preview buffer')
            if not path:raise ValueError('Missing preview buffer output path')
            lines += ['RenderOutput(%s) {'%string('/modo/preview/'+key),
                      '  ["file_name"] = %s,'%string(str(path)),
                      '  ["channel_format"] = 0,', '  ["compression"] = 1,']
            attributes={k:v for k,v in available[key].items() if k!='channel_format'}
            for attr,value in attributes.items():
                lines.append('  [%s] = %s,'%(string(attr),string(value) if isinstance(value,str) else ('true' if value else 'false') if isinstance(value,bool) else number(value)))
            lines.append('}')
    for key,path in scene.get('_denoise_guides',{}).items():
        attributes={'result':7,'material_aov':'albedo'} if key=='albedo' else {'result':3,'state_variable':2}
        if recovery:
            from .recovery import attributes as recovery_attributes
            attributes.update(recovery_attributes(recovery,key))
        lines += ['RenderOutput(%s) {' % string('/modo/denoise/'+key),
                  '  ["file_name"] = %s,' % string(path), '  ["channel_format"] = 0,', '  ["compression"] = 1,']
        for attr,value in attributes.items(): lines.append('  [%s] = %s,' % (string(attr),string(value) if isinstance(value,str) else ('true' if value else 'false') if isinstance(value,bool) else number(value)))
        lines.append('}')
    return '\n'.join(lines) + '\n'
