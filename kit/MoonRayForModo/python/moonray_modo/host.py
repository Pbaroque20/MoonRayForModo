"""Modo 16.1 scene sampling. Call only from Modo's main/UI thread."""
import math
import lx
import lxu.utils
import lxifc
import modo
from . import properties, options


def channel(item, name, default=None):
    value = item.channel(name)
    return value.get() if value is not None else default


def color(item, prefix, default=(1, 1, 1)):
    return [float(channel(item, prefix + '.' + axis, default[i])) for i, axis in enumerate('RGB')]


def world_matrix(item):
    rows = lx.object.Matrix(item.channel('worldMatrix').get()).Get4()
    return [float(value) for row in rows for value in row]


def first_map(mesh, map_type, name=None):
    accessor = lx.object.MeshMap(mesh.MeshMapAccessor())
    if not accessor.test():
        return None
    found = []
    class Maps(lxifc.Visitor):
        def vis_Evaluate(self):
            if accessor.Type() == map_type and (not name or accessor.Name() == name):
                found.append((accessor.Name(), int(accessor.ID())))
    visitor = Maps()
    accessor.Enumerate(lx.symbol.iMARK_ANY, visitor, 0)
    return sorted(found)[0][1] if found else None


def corner_values(polygons, map_id, count, dimension):
    if map_id is None:
        return []
    storage = lx.object.storage()
    storage.setType('f')
    storage.setSize(dimension)
    values = []
    for corner in range(count):
        try:
            polygons.MapEvaluate(map_id, polygons.VertexByIndex(corner), storage)
            values.append(list(storage.get()))
        except LookupError:
            return []
    return values


def render_visible(item):
    while item is not None:
        value = channel(item, 'render', 'default')
        if value in ('off', 'no', False):
            return False
        if value in ('on', 'yes'):
            return True
        item = item.parent
    return True


def image_layers(scene, materials, warnings, baked_effects=()):
    from .layers import collect
    collect(scene, materials, warnings, baked_effects=baked_effects)


def material_values(material):
    diffuse = color(material, 'diffCol', (.5, .5, .5))
    diffuse_amount = float(channel(material, 'diffAmt', 1))
    return {'color': [c * diffuse_amount for c in diffuse],
                                'shader': properties.read(material).get('shader',''),
                                'thin_geometry': properties.read(material).get('thin_geometry',False),
                                'diffuse_amount': diffuse_amount,
                                'raw_color': diffuse,
                                'raw_specular': color(material, 'specCol'),
                                'raw_emission': color(material, 'lumiCol'),
                                'bump_strength': float(channel(material, 'bumpAmp', .005)),
                                'base_layer_id': material.id,
                                'specular_amount': float(channel(material, 'specAmt', .04)),
                                'emission_amount': float(channel(material, 'radiance', 0)),
                                'roughness': float(channel(material, 'rough', .4)),
                                'anisotropy': float(channel(material, 'aniso', 0)),
                                'metallic': float(channel(material, 'metallic', 0)),
                                'specular': [c * float(channel(material, 'specAmt', .04)) for c in color(material, 'specCol')],
                                'emission': [c * float(channel(material, 'radiance', 0)) for c in color(material, 'lumiCol')],
                                'ior': max(1.0, float(channel(material, 'refIndex', 1.5))),
                                'transmission': min(1.0, max(0.0, float(channel(material, 'tranAmt', 0)))),
                                'transmission_color': color(material, 'tranCol'),
                                'refraction_roughness': min(1.0, max(0.0, float(channel(material, 'tranRough', 0)))),
                                'presence': 1.0 - min(1.0, max(0.0, float(channel(material, 'dissAmt', 0)))),
                                'opacity': 1.0 - float(channel(material, 'dissAmt', 0)),
                                'clearcoat': float(channel(material, 'coatAmt', 0)),
                                'clearcoat_roughness': float(channel(material, 'coatRough', .01))}


def snapshot(evaluated_geometry=False):
    scene = modo.Scene()
    camera = scene.renderCamera
    if camera is None:
        raise ValueError('The scene needs a render camera.')
    if channel(camera, 'projType', 'persp') != 'persp':
        raise ValueError('This version supports perspective cameras only.')
    warnings = []
    render = scene.renderItem
    width, height = int(channel(render, 'resX', 1280)), int(channel(render, 'resY', 720))
    if channel(camera, 'resOverride', 0):
        width, height = int(channel(camera, 'resX', width)), int(channel(camera, 'resY', height))
    aperture_x = float(channel(camera, 'apertureX', .036))
    aperture_y = float(channel(camera, 'apertureY', .024))
    aspect = width / max(height, 1)
    fit = channel(camera, 'filmFit', 'fill')
    # Match fill/overscan and horizontal/vertical fit with a horizontal frustum.
    if fit in ('vertical', 'vert') or (fit == 'fill' and aspect < aperture_x / aperture_y) or (fit == 'overscan' and aspect > aperture_x / aperture_y):
        aperture_x = aperture_y * aspect
    for name, default in [('offsetX', 0), ('offsetY', 0), ('filmRoll', 0), ('distort', 0), ('squeeze', 1)]:
        if channel(camera, name, default) != default:
            warnings.append('Camera %s is not translated.' % name)
    result = {'camera': {'matrix': world_matrix(camera),
                         'focal_mm': float(channel(camera, 'focalLen', .05)) * 1000,
                         'film_mm': aperture_x * 1000,
                         'dof': bool(channel(camera, 'dof', 0)),
                         'f_stop': float(channel(camera, 'fStop', 4)),
                         'focus_distance': float(channel(camera, 'focusDist', 4)),
                         'iris_blades': int(channel(camera, 'irisBlades', 0)),
                         'iris_rotation': float(channel(camera, 'irisRot', 0))},
              'width': width, 'height': height, 'materials': {}, 'meshes': [], 'lights': []}
    from .layers import ordered_items, material_tag
    for material in reversed(list(ordered_items(scene.renderItem))):
        if material.type != 'advancedMaterial' or not channel(material, 'enable', 1):
            continue
        try:
            tag = material_tag(material)
        except ValueError as exc:
            if not evaluated_geometry:
                warnings.append('Material %s: %s' % (material.name, exc))
            continue
        if tag is None:
            continue
        if tag in result['materials'] and not evaluated_geometry:
            warnings.append('Multiple material layers for %s: using the uppermost; BSDF layering is unsupported.' % (tag or 'base material'))
        result['materials'][tag] = material_values(material)
        if channel(material, 'subsAmt', 0):
            warnings.append('Subsurface is not translated: ' + material.name)
        if channel(material, 'aniso', 0) and result['materials'][tag]['shader'] != 'DwaBaseMaterial':
            warnings.append('Anisotropy requires MoonShine Material: ' + material.name)
        if channel(material, 'tranAmt', 0):
            if channel(material, 'tranDist', 0) or channel(material, 'disperse', 0):
                warnings.append('Glass uses surface tint; absorption distance and dispersion are not translated: ' + material.name)
            if channel(material, 'metallic', 0) or channel(material, 'coatAmt', 0):
                warnings.append('Glass uses dielectric Fresnel reflection; metalness and clearcoat are not translated: ' + material.name)
    if not evaluated_geometry:
        image_layers(scene, result['materials'], warnings)
    for tag, material in result['materials'].items():
        maps = material.get('textures', {})
        if material.get('shader') == 'DwaBaseMaterial':
            if 'specCol' in maps:
                warnings.append('MoonShine uses dielectric IOR or metallic base color; specular-color maps are not translated: ' + (tag or 'base material'))
            continue
        if material['transmission'] > 0 or material['presence'] < 1 or 'dissolve' in maps or any(k.startswith('tran') for k in maps):
            if any(k in maps for k in ('specCol', 'specAmt', 'coatAmt', 'coatRough', 'metallic')):
                warnings.append('The standard glass/dissolve material ignores specular-color, clearcoat and metalness maps. MoonShine supports mapped clearcoat and metalness: ' + (tag or 'base material'))
    if evaluated_geometry:
        from . import evaluated
        data = evaluated.capture(lx.service.Selection().GetTime())
        result['materials'] = evaluated.assign_materials(data, scene, warnings)
        result['meshes'] = evaluated.meshes(data, result['materials'], warnings)
    # Resolve each visible instance to one mesh prototype, including hidden sources.
    instances = {}
    for instance in ([] if evaluated_geometry else scene.items('meshInst', superType=False)):
        if not render_visible(instance):
            continue
        source, visited = instance, set()
        try:
            while source.type == 'meshInst':
                if source.id in visited:
                    raise ValueError('cyclic instance source')
                visited.add(source.id)
                links = source.itemGraph('source').forward()
                if len(links) != 1:
                    raise ValueError('missing or ambiguous source')
                source = links[0]
            if source.type != 'mesh':
                raise ValueError('source is not a mesh')
            instances.setdefault(source.id, []).append(world_matrix(instance))
        except (ValueError, LookupError) as exc:
            warnings.append('Instance %s: %s.' % (instance.name, exc))
    # Fresh read-only evaluated meshes; never change selection, time or scene geometry.
    for item in ([] if evaluated_geometry else scene.items('mesh', superType=False)):
        if not render_visible(item) and item.id not in instances:
            continue
        mesh = modo.meshgeometry.MeshProvider.meshFromMeshChannel(item._item, 'deformed')
        if not mesh.PolygonCount():
            continue
        points = lx.object.Point(mesh.PointAccessor())
        polygons = lx.object.Polygon(mesh.PolygonAccessor())
        vertices, point_indices = [], {}
        for index in range(mesh.PointCount()):
            points.SelectByIndex(index)
            point_indices[int(points.ID())] = index
            vertices.append(list(points.Pos()))
        groups = {}
        uv_maps = {}
        normal_map = first_map(mesh, lx.symbol.i_VMAP_NORMAL)
        tags = lx.object.StringTag(polygons)
        for index in range(mesh.PolygonCount()):
            polygons.SelectByIndex(index)
            count = polygons.VertexCount()
            if count < 3:
                warnings.append('Skipped curve/line polygon in ' + item.name)
                continue
            try:
                tag = tags.Get(lx.symbol.i_POLYTAG_MATERIAL) or ''
            except LookupError:
                tag = ''
            face = [point_indices[int(polygons.VertexByIndex(v))] for v in range(count)]
            subdivision = lxu.utils.decodeID4(polygons.Type()) in ('SUBD', 'PSUB')
            maps = result['materials'].get(tag, {}).get('textures', {})
            uv_name = result['materials'].get(tag, {}).get('uv_map', '') or (next(iter(maps.values()))['uv_map'] if maps else '')
            if uv_name not in uv_maps:
                uv_maps[uv_name] = first_map(mesh, lx.symbol.i_VMAP_TEXTUREUV, uv_name)
            face_uv = corner_values(polygons, uv_maps[uv_name], count, 2)
            if uv_name and not face_uv:
                raise ValueError('Mesh %s is missing UV values in map %s.' % (item.name, uv_name))
            groups.setdefault((subdivision, uv_name), []).append((face, tag,
                face_uv, corner_values(polygons, normal_map, count, 3)))
        transform = world_matrix(item)
        object_settings = options.object_values(properties.read(item))
        transforms = instances.get(item.id, [])
        if item.id in instances and render_visible(item):
            transforms = [transform] + transforms
        for (subdivision, uv_name), tagged_faces in sorted(groups.items()):
            faces, face_materials, face_uvs, face_normals = zip(*tagged_faces)
            result['meshes'].append({'name': item.name, 'vertices': vertices,
                                     'faces': list(faces), 'matrix': transform, 'material': '',
                                     'face_materials': list(face_materials),
                                     'uvs': [uv for values in face_uvs for uv in values] if all(face_uvs) else [],
                                     'normals': [n for values in face_normals for n in values] if all(face_normals) else [],
                                     'object_override': object_settings['override'],
                                     'smooth': object_settings['smooth'] if object_settings['override'] else True,
                                     'subdivision_level': object_settings['level'],
                                     'subdivision': object_settings['subdivision'] if object_settings['override'] else subdivision})
            if item.id in instances:
                result['meshes'][-1]['instances'] = transforms
    for item in scene.items('light'):
        if not render_visible(item):
            continue
        types = {'sunLight': 'DistantLight', 'pointLight': 'SphereLight', 'areaLight': 'RectLight', 'spotLight': 'SpotLight'}
        if item.type not in types:
            warnings.append('Skipped unsupported light: ' + item.name)
            continue
        material = item.material
        light = {'kind': types[item.type], 'matrix': world_matrix(item),
                 'color': color(material, 'lightCol') if material else [1, 1, 1],
                 'intensity': float(channel(item, 'radiance', 1)),
                 'angle': max(.01, math.degrees(float(channel(item, 'spread', 0)))),
                 'radius': max(.001, float(channel(item, 'radius', .05))),
                 'cone': min(179.0, max(.01, math.degrees(float(channel(item, 'cone', math.pi / 4))))),
                 'soft_edge': max(0.0, math.degrees(float(channel(item, 'edge', 0)))),
                 'width': float(channel(item, 'width', 1)), 'height': float(channel(item, 'height', 1))}
        if item.type == 'spotLight':
            # Modo emits along local +Z; MoonRay's authored spot emits along -Z.
            # Precompose a local X half-turn, keeping the world position intact.
            light['matrix'][4:12] = [-v for v in light['matrix'][4:12]]
        result['lights'].append(light)
    for kind in (('textureLayer', 'volume') if evaluated_geometry else ('replicator', 'textureLayer', 'volume')):
        if scene.items(kind, superType=False):
            warnings.append('%s items are not translated in this version.' % kind)
    from .environments import collect as collect_environments
    result['environments'] = collect_environments(scene, warnings)
    result['warnings'] = sorted(set(warnings))
    return result
