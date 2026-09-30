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


def first_map(mesh, map_type):
    accessor = lx.object.MeshMap(mesh.MeshMapAccessor())
    if not accessor.test():
        return None
    found = []
    class Maps(lxifc.Visitor):
        def vis_Evaluate(self):
            if accessor.Type() == map_type:
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


def snapshot():
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
    for name, default in [('offsetX', 0), ('offsetY', 0), ('filmRoll', 0), ('dof', 0), ('distort', 0), ('squeeze', 1)]:
        if channel(camera, name, default) != default:
            warnings.append('Camera %s is not translated.' % name)
    result = {'camera': {'matrix': world_matrix(camera),
                         'focal_mm': float(channel(camera, 'focalLen', .05)) * 1000,
                         'film_mm': aperture_x * 1000},
              'width': width, 'height': height, 'materials': {}, 'meshes': [], 'lights': []}
    for material in scene.items('advancedMaterial'):
        if not channel(material, 'enable', 1):
            continue
        parent = material.parent
        tag = ''
        if parent and parent.type == 'mask':
            if channel(parent, 'ptyp', '') not in ('Material', 'material', 'MATR'):
                warnings.append('Skipped non-material mask: ' + parent.name)
                continue
            tag = channel(parent, 'ptag', '')
        elif parent and parent.type != 'polyRender':
            warnings.append('Skipped nested material: ' + material.name)
            continue
        if tag in result['materials']:
            warnings.append('Multiple material layers for %s: using the last encountered.' % (tag or 'base material'))
        diffuse = color(material, 'diffCol', (.5, .5, .5))
        diffuse_amount = float(channel(material, 'diffAmt', 1))
        result['materials'][tag] = {'color': [c * diffuse_amount for c in diffuse],
                                    'roughness': float(channel(material, 'rough', .4)),
                                    'metallic': float(channel(material, 'metallic', 0)),
                                    'specular': [c * float(channel(material, 'specAmt', .04)) for c in color(material, 'specCol')],
                                    'emission': [c * float(channel(material, 'radiance', 0)) for c in color(material, 'lumiCol')],
                                    'ior': max(1.0, float(channel(material, 'refIndex', 1.5))),
                                    'opacity': 1.0 - float(channel(material, 'dissAmt', 0)),
                                    'clearcoat': float(channel(material, 'coatAmt', 0)),
                                    'clearcoat_roughness': float(channel(material, 'coatRough', .01))}
        if channel(material, 'subsAmt', 0) or channel(material, 'tranAmt', 0) or channel(material, 'aniso', 0):
            warnings.append('Subsurface, refractive transparency and anisotropy are not translated: ' + material.name)
    # Fresh read-only evaluated meshes; never change selection, time or scene geometry.
    for item in scene.items('mesh', superType=False):
        if not render_visible(item):
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
        uv_map = first_map(mesh, lx.symbol.i_VMAP_TEXTUREUV)
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
            groups.setdefault(subdivision, []).append((face, tag,
                corner_values(polygons, uv_map, count, 2), corner_values(polygons, normal_map, count, 3)))
        transform = world_matrix(item)
        object_settings = options.object_values(properties.read(item))
        for subdivision, tagged_faces in sorted(groups.items()):
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
    for kind in ('meshInst', 'replicator', 'imageMap', 'textureLayer', 'volume'):
        if scene.items(kind, superType=False):
            warnings.append('%s items are not translated in this version.' % kind)
    result['warnings'] = sorted(set(warnings))
    return result
