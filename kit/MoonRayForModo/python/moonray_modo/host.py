"""Modo 16.1 scene sampling. Call only from Modo's main/UI thread."""
import math
import lx
import lxu.utils
import modo


def channel(item, name, default=None):
    value = item.channel(name)
    return value.get() if value is not None else default


def color(item, prefix, default=(1, 1, 1)):
    return [float(channel(item, prefix + '.' + axis, default[i])) for i, axis in enumerate('RGB')]


def world_matrix(item):
    rows = lx.object.Matrix(item.channel('worldMatrix').get()).Get4()
    return [float(value) for row in rows for value in row]


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
        result['materials'][tag] = {'color': color(material, 'diffCol', (.5, .5, .5)),
                                    'roughness': float(channel(material, 'rough', .4)),
                                    'metallic': float(channel(material, 'metallic', 0))}
        if channel(material, 'tranAmt', 0) or channel(material, 'subsAmt', 0) or channel(material, 'radiance', 0):
            warnings.append('Transmission, subsurface and emission are not translated: ' + material.name)
    # Fresh read-only evaluated meshes; never change selection, time or scene geometry.
    for item in scene.items('mesh', superType=False):
        if not render_visible(item):
            continue
        mesh = modo.meshgeometry.MeshProvider.meshFromMeshChannel(item._item, 'deformed')
        points = lx.object.Point(mesh.PointAccessor())
        polygons = lx.object.Polygon(mesh.PolygonAccessor())
        vertices, point_indices = [], {}
        for index in range(mesh.PointCount()):
            points.SelectByIndex(index)
            point_indices[int(points.ID())] = index
            vertices.append(list(points.Pos()))
        groups = {}
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
            groups.setdefault((tag, subdivision), []).append(face)
        transform = world_matrix(item)
        if len(groups) > 1 and any(key[1] for key in groups):
            warnings.append('Subdivision material boundaries may form seams: ' + item.name)
        for (tag, subdivision), faces in sorted(groups.items()):
            result['meshes'].append({'name': item.name, 'vertices': vertices,
                                     'faces': faces, 'matrix': transform, 'material': tag,
                                     'subdivision': subdivision})
    for item in scene.items('light'):
        if not render_visible(item):
            continue
        types = {'sunLight': 'DistantLight', 'pointLight': 'SphereLight', 'areaLight': 'RectLight'}
        if item.type not in types:
            warnings.append('Skipped unsupported light: ' + item.name)
            continue
        material = item.material
        light = {'kind': types[item.type], 'matrix': world_matrix(item),
                 'color': color(material, 'lightCol') if material else [1, 1, 1],
                 'intensity': float(channel(item, 'radiance', 1)),
                 'angle': max(.01, math.degrees(float(channel(item, 'spread', 0)))),
                 'radius': max(.001, float(channel(item, 'radius', .05))),
                 'width': float(channel(item, 'width', 1)), 'height': float(channel(item, 'height', 1))}
        result['lights'].append(light)
    for kind in ('meshInst', 'replicator', 'imageMap', 'textureLayer', 'volume'):
        if scene.items(kind, superType=False):
            warnings.append('%s items are not translated in this version.' % kind)
    result['warnings'] = sorted(set(warnings))
    return result
