"""Modo 16.1 scene sampling. Call only from Modo's main/UI thread."""
import math
import lx
import lxu.utils
import lxifc
import modo
from . import properties, options, coordinates, face_tags


def channel(item, name, default=None):
    value = item.channel(name)
    return value.get() if value is not None else default


def color(item, prefix, default=(1, 1, 1)):
    return [float(channel(item, prefix + '.' + axis, default[i])) for i, axis in enumerate('RGB')]


def world_matrix(item, time=None):
    """The item's world matrix now, or at time (seconds) where given."""
    rows = lx.object.Matrix(item.channel('worldMatrix').get() if time is None else item.channel('worldMatrix').get(time)).Get4()
    return [float(value) for row in rows for value in row]


def subdivision_creases(mesh, faces):
    """Modo's subdivision weights on a subdivided mesh's edges and points, as MoonRay's creases: (a, b, sharpness) for
    each weighted edge of faces, and (point, sharpness) for each weighted point, by point index. A weight of 1 (100%)
    is a sharpness of 10, as sharp as MoonRay's creases go; the importer reads them back the same way (rdl_import). None
    of either for a mesh without a Subdivision weight map."""
    map_id = first_map(mesh, lx.symbol.i_VMAP_SUBDIV)
    if map_id is None:
        return [], []
    held = creases_natively(mesh, map_id, faces)
    if held is not None:
        return held
    points = lx.object.Point(mesh.PointAccessor())
    edge = lx.object.Edge(mesh.EdgeAccessor())
    value = lx.object.storage('f', 1)
    ids = {}

    def point_id(index):
        if index not in ids:
            points.SelectByIndex(index)
            ids[index] = points.ID()
        return ids[index]

    creases, seen = [], set()
    for face in faces:
        for a, b in zip(face, face[1:] + face[:1]):
            pair = (min(a, b), max(a, b))
            if pair in seen:
                continue
            seen.add(pair)
            try:
                edge.SelectEndpoints(point_id(pair[0]), point_id(pair[1]))
                found = edge.MapValue(map_id, value)
            except (LookupError, RuntimeError):
                continue
            weight = value.get()[0] if found else 0.0
            if weight > 0:
                creases.append((pair[0], pair[1], min(1.0, weight) * 10.0))
    corners = []
    for index in sorted({v for face in faces for v in face}):
        try:
            points.Select(point_id(index))
            found = points.MapValue(map_id, value)
        except (LookupError, RuntimeError):
            continue
        weight = value.get()[0] if found else 0.0
        if weight > 0:
            corners.append((index, min(1.0, weight) * 10.0))
    return creases, corners


def creases_natively(mesh, map_id, faces):
    """subdivision_creases() by the geometry adapter in one call (native-modo/subdivision_creases.cpp); None where it
    cannot."""
    import ctypes
    from array import array
    from . import mesh_reader, rows
    library = mesh_reader.bridge()
    reader = getattr(library, 'MR_subdivision_creases', None) if library is not None else None
    if reader is None:
        return None
    try:
        address = mesh.__peekobj__()
    except AttributeError:
        return None
    corners = rows.corners(faces)
    corners = corners if corners is not None and corners.typecode in ('I', 'i', 'L', 'l') and corners.itemsize == 4 else array('I', (v for face in faces for v in face))
    counts = rows.counts(faces)
    counts = counts if counts is not None and counts.itemsize == 4 else array('i', map(len, faces))
    room = len(corners)
    edges, edge_weights = array('i', bytes(8 * room)), array('f', bytes(4 * room))
    points, point_weights = array('i', bytes(4 * room)), array('f', bytes(4 * room))
    made = (ctypes.c_longlong * 2)()
    pointer = ctypes.c_void_p
    reader.argtypes = [pointer, pointer, pointer, pointer, ctypes.c_longlong, pointer, pointer, ctypes.c_longlong,
                       pointer, pointer, ctypes.c_longlong, pointer]
    reader.restype = ctypes.c_char_p
    address_of = rows._address
    if reader(pointer(address), pointer(int(map_id)), pointer(address_of(corners) if room else None), pointer(address_of(counts) if len(counts) else None),
              len(counts), address_of(edges) if room else None, address_of(edge_weights) if room else None, room,
              address_of(points) if room else None, address_of(point_weights) if room else None, room, ctypes.addressof(made)):
        return None
    # As the slow reading makes them: a weight of 1 (100%) a sharpness of 10.
    creases = [(edges[2 * k], edges[2 * k + 1], min(1.0, edge_weights[k]) * 10.0) for k in range(made[0])]
    return creases, [(points[k], min(1.0, point_weights[k]) * 10.0) for k in range(made[1])]


def first_map(mesh, map_type, name=None):
    accessor = lx.object.MeshMap(mesh.MeshMapAccessor())
    if not accessor.test():
        return None
    found = []
    class Maps(lxifc.Visitor):
        def vis_Evaluate(self):
            if accessor.Type() == map_type and (not name or str(name).startswith('@index:') or accessor.Name() == name):
                found.append((accessor.Name(), int(accessor.ID())))
    visitor = Maps()
    accessor.Enumerate(lx.symbol.iMARK_ANY, visitor, 0)
    index=int(name.split(':',1)[1]) if str(name).startswith('@index:') else 0
    return sorted(found)[index][1] if len(found)>index else None


def corner_values(polygons, map_id, count, dimension):
    if map_id is None:
        return []
    storage = lx.object.storage()
    storage.setType('f')
    storage.setSize(dimension)
    values = []
    for corner in range(count):
        try:
            # Missing per-corner data returns false without raising. The storage
            # buffer is then untouched and must never be exported or hashed.
            if not polygons.MapEvaluate(map_id, polygons.VertexByIndex(corner), storage):
                return []
            values.append(list(storage.get()))
        except LookupError:
            return []
    return values


def dicing_view(scene, identity, width, height, pixel_aspect, warnings, time=None):
    """The camera chosen to work adaptive tessellation out for: {'entity': id} for a MoonRay camera item, a Modo
    camera's view framed as the render camera's is, or None for the render camera itself or one that is gone."""
    try:
        item = scene.item(identity)
    except LookupError:
        warnings.append('The dicing camera chosen is no longer in the scene; the render camera is used.')
        return None
    from .entities import class_of
    if item.type != 'camera' or class_of(item) is not None:
        return {'entity': item.id}
    if item.id == scene.renderCamera.id and time is None:
        return None
    projection = channel(item, 'projType', 'persp')
    if projection not in ('persp', 'ortho'):
        warnings.append('The dicing camera %s has a projection MoonRay does not dice for; the render camera is used.' % item.name)
        return None
    from .camera import framing, offsets
    aperture_x, moonray_pixel_aspect = framing(width, height, float(channel(item, 'apertureX', .036)), float(channel(item, 'apertureY', .024)),
                                               pixel_aspect, channel(item, 'filmFit', 'fill'))
    ortho_width = float(properties.read(item).get('ortho_width', aperture_x * float(channel(item, 'target', 1)) / max(1e-9, float(channel(item, 'focalLen', .05)))))
    return {'matrix': world_matrix(item, time), 'identity': item.id, 'projection': projection, 'ortho_width': ortho_width,
            'film_offset': offsets(float(channel(item, 'offsetX', 0)), float(channel(item, 'offsetY', 0)), projection, aperture_x, ortho_width, pixel_aspect),
            'pixel_aspect': moonray_pixel_aspect, 'focal_mm': float(channel(item, 'focalLen', .05)) * 1000, 'film_mm': aperture_x * 1000}


def render_visible(item):
    """Whether Modo would render the item. Render: Yes or No settles it, for the item and what is under it. Left at
    Default, an item renders as it is shown: not with its eye off, nor under a parent hidden with its children."""
    own = True
    while item is not None:
        value = channel(item, 'render', 'default')
        if value in ('off', 'no', False):
            return False
        if value in ('on', 'yes'):
            return True
        shown = channel(item, 'visible', 'default')
        if shown == 'allOff' or (own and shown in ('off', 'no', False)):
            return False
        own = False
        item = item.parent
    return True


def worn_tags(found):
    """The material tags a reading's meshes, extra geometry (fur, curves, points, volumes) and native shapes wear, and
    '' (the base material, which every surface not otherwise tagged wears)."""
    worn = {''}
    for mesh in found.get('meshes') or []:
        worn.update(face_tags.worn(mesh))
    for extra in found.get('extra_geometry') or []:
        worn.add(extra.get('material', ''))
    for entity in found.get('entities') or []:
        worn.add((entity.get('parameters') or {}).get('modo_material') or '')
    worn.discard(None)
    return worn


def unworn(scene, result, warnings):
    """Say where a MoonRay material is on nothing: it sits in a group for a material tag that no polygon being
    rendered carries, as happens when a material is dragged into another group after being assigned. It then renders
    nowhere, whatever images it has, and nothing else says so."""
    from . import properties
    data = result.get('_evaluated_data')
    if data:
        carried = {surface.get('source_material', surface.get('material')) for surface in data.get('surfaces', [])}
    else:
        carried = set()
        for mesh in result.get('meshes', []):
            carried.update(face_tags.worn(mesh))
    carried.discard(None)
    if not carried:
        return
    for mask in scene.items('mask', superType=False):
        try:
            tag = channel(mask, 'ptag', '') or ''
            if not tag or tag == '(all)' or tag in carried or channel(mask, 'ptyp', '') not in ('Material', '') or not channel(mask, 'enable', 1):
                continue
            for child in mask.children():
                if child.type == 'advancedMaterial' and properties.read(child).get('native_shader') and channel(child, 'enable', 1):
                    named = sorted(tag for tag in carried if tag)
                    if not named:
                        # Modo's own account of the surfaces names no tag where no group took them: the meshes are asked.
                        found = set()
                        for mesh in scene.items('mesh', superType=False):
                            polygons = mesh.geometry.polygons
                            found.update(polygons[index].materialTag for index in range(0, len(polygons), max(1, len(polygons) // 2000)))
                        named = sorted(tag for tag in found if tag)
                    warnings.append('Material %s is on nothing: its group is for the material tag %s, which no polygon carries. The polygons are tagged %s. '
                                    "Set the group's Polygon Tag to that, or assign the material again."
                                    % (child.name, tag, ', '.join(named[:4]) + (' and others' if len(named) > 4 else '') if named else 'with no material'))
        except (LookupError, RuntimeError, AttributeError, TypeError):
            continue


def image_layers(scene, materials, warnings, baked_effects=()):
    from .layers import collect
    collect(scene, materials, warnings, baked_effects=baked_effects)


def arranged(graph):
    """A graph without where its nodes sit in the editor, which is no part of how it renders;
    moving a node must not look like an edit to the material."""
    if not graph or not isinstance(graph.get('nodes'),dict):return graph
    return dict(graph,nodes={key:{k:v for k,v in node.items() if k!='position'} for key,node in graph['nodes'].items()})


def relinked_graph(graph, warnings=None):
    """A material's graph with each image it names that is not where it says found as the scene's image clips are
    (textures.relink_graph): beside the scene by its last folders, or by its name in a folder the scene's own images are
    in. The scene is not changed (Relink Images does that); each image found elsewhere is said in warnings."""
    from . import textures
    if not isinstance(graph, dict) or not isinstance(graph.get('nodes'), dict):
        return graph
    values = [value for node in graph['nodes'].values() if isinstance(node, dict)
              for value in (node.get('parameters') or {}).values() if textures.graph_image_value(value)]
    if not values or all(not textures.missing(value) for value in values):
        return graph
    scene = modo.Scene()
    filename = getattr(scene, 'filename', None)
    graph, changes = textures.relink_graph(graph, filename, _image_folders(scene))
    if warnings is not None:
        for _, _, old, new, how in changes:
            note = 'Graph image %s found %s: %s' % (old, "by its name in the scene's images folder" if how == 'same name' else 'beside the scene', new)
            if note not in warnings:
                warnings.append(note)
    return graph


_FOLDERS = {}


def _image_folders(scene):
    """The folders of the scene's image clips (textures.image_folders), kept while its clips are the same."""
    from . import textures
    clips = tuple(channel(clip, 'filename', '') for clip in scene.items('videoStill', superType=False))
    key = (getattr(scene, 'filename', None), clips)
    if key not in _FOLDERS:
        _FOLDERS.clear()
        _FOLDERS[key] = textures.image_folders(scene)
    return _FOLDERS[key]


def material_values(material, warnings=None):
    from .material_settings import values as material_settings
    settings = properties.read(material)
    settings=dict(settings)
    if settings.get('materialx_override'):
        from .nodes import validate as validate_graph
        graph=settings.get('materialx_graph')
        resolved=validate_graph(graph);root=resolved['nodes'][resolved['root']]
        settings.update(node_graph=graph,native_shader=root['type'],native_parameters=root.get('parameters',{}))
    if material.type!='material.moonrayMaterialX':
        from .material_override import effective
        settings=effective(settings)
    controls = material_settings(settings)
    diffuse = color(material, 'diffCol', (.5, .5, .5))
    # Modo's Principled model shows the diffuse colour in full, whatever the diffuse amount is set to.
    diffuse_amount = 1.0 if channel(material, 'brdfType', '') == 'principled' else float(channel(material, 'diffAmt', 1))
    # Modo's Blinn and Ashikhmin highlights are another lobe of MoonRay's, at another roughness and strength.
    from .shading_models import translated
    model = str(channel(material, 'brdfType', 'gtr'))
    lobe_roughness, lobe_strength, beckmann = translated(model, float(channel(material, 'rough', .4)))
    value = {'name':material.name,'item':material.id,'crypto_name':str(settings.get('crypto_name') or '').strip(),
             'crypto_id':int(settings.get('crypto_id') or 0),'color': [c * diffuse_amount for c in diffuse],
                                **controls,
                                'node_graph': arranged(relinked_graph(settings.get('node_graph'), warnings)),
                                'node_override': settings.get('node_override',False) or material.type in ('material.moonrayMaterialX','material.moonrayMoonShine'),
                                'native_shader': settings.get('native_shader',''),
                                'native_parameters': settings.get('native_parameters',{}),
                                'shader': settings.get('shader',''),
                                'standard_material': settings.get('shader','')!='DwaBaseMaterial',
                                'specular_fresnel':float(channel(material,'specFres',1)),
                                'reflection_fresnel':float(channel(material,'reflFres',1)),
                                'thin_geometry': settings.get('thin_geometry',False),
                                # A MoonRay volume item that fills what wears this material, and whether the material is
                                # that volume alone, with no surface (as a MoonRay scene's mesh full of fog is).
                                'moonray_volume': settings.get('moonray_volume',''),
                                'volume_only': bool(settings.get('volume_only',False)),
                                # The objects whose surfaces join in this material's subsurface light: MoonRay's sss trace set.
                                'rdl_layer_links': settings.get('rdl_layer_links', {}),
                                'sss_trace_set': sorted(str(v) for v in (settings.get('sss_trace_set') or [])),
                                # Where a material says how its polygons are smoothed: 0 for flat, otherwise the angle within which
                                # neighbours are smoothed together. None leaves the mesh to be smoothed as it otherwise would be.
                                'smoothing_angle': (float(settings.get('smoothing_angle',40.0)) if settings['smoothing'] else 0.0) if settings.get('smoothing') is not None else None,
                                # Modo's own word on the same, which holds where the MoonRay settings say nothing: its material's
                                # Smoothing and Smoothing Angle.
                                'modo_smoothing_angle': math.degrees(float(channel(material, 'smAngle', math.radians(40.0)))) if float(channel(material, 'smooth', 1.0)) > 0 else 0.0,
                                'diffuse_amount': diffuse_amount,
                                'raw_color': diffuse,
                                'raw_specular': color(material, 'specCol'),
                                'raw_emission': color(material, 'lumiCol'),
                                'bump_strength': float(channel(material, 'bumpAmp', .005)),
                                'base_layer_id': material.id,
                                'specular_amount': float(channel(material, 'specAmt', .04)),
                                'shading_model': model, '_beckmann': beckmann, '_specular_strength': lobe_strength,
                                'emission_amount': float(channel(material, 'radiance', 0)),
                                'roughness': lobe_roughness,
                                'raw_roughness': float(channel(material, 'rough', .4)),
                                'diffuse_roughness': float(channel(material, 'diffRough', 0)),
                                'subsurface_amount': min(1,max(0,float(channel(material,'subsAmt',0)))),
                                'subsurface_distance': max(0,float(channel(material,'subsDist',0))),
                                'subsurface_color': color(material,'subsCol'),
                                'absorption_distance': max(0,float(channel(material,'tranDist',0))),
                                'layer_opacity': float(channel(material,'opacity',1)),
                                'layer_blend': channel(material,'blend','normal'),
                                'layer_invert': bool(channel(material,'invert',False)),
                                # Modo stretches a highlight only along a UV map (or vector map) named on the material: without
                                # one it draws a round highlight, whatever the Anisotropy (seen in its own renders).
                                'anisotropy': float(channel(material, 'aniso', 0)) if channel(material, 'uvMap', '') or channel(material, 'isVectorMap', 0) else 0.0,
                                # Modo's material is a metal only under its Principled shading model; the others ignore the setting.
                                'metallic': float(channel(material, 'metallic', 0)) if channel(material, 'brdfType', '') == 'principled' else 0.0,
                                'specular': [c * float(channel(material, 'specAmt', .04)) for c in color(material, 'specCol')],
                                'principled': channel(material, 'brdfType', '') == 'principled',
                                'emission': [c * float(channel(material, 'radiance', 0)) for c in color(material, 'lumiCol')],
                                'ior': max(1.0, float(channel(material, 'refIndex', 1.5))),
                                'dispersion_abbe': settings.get('dispersion_abbe',max(0,float(channel(material,'refIndex',1.5))-1)/float(channel(material,'disperse',0)) if float(channel(material,'disperse',0))>0 else 0),
                                'transmission': min(1.0, max(0.0, float(channel(material, 'tranAmt', 0)))),
                                'transmission_color': color(material, 'tranCol'),
                                'refraction_roughness': min(1.0, max(0.0, float(channel(material, 'tranRough', 0)))),
                                'presence': 1.0 - min(1.0, max(0.0, float(channel(material, 'dissAmt', 0)))),
                                'opacity': 1.0 - float(channel(material, 'dissAmt', 0)),
                                'clearcoat': float(channel(material, 'coatAmt', 0)),
                                'clearcoat_roughness': float(channel(material, 'coatRough', .01)),
                                # Clearcoat Bump Strength: how much of the bump and normal maps the coat takes.
                                'clearcoat_bump': min(1.0, max(0.0, float(channel(material, 'coatBump', 1.0)))),
                                # Displacement Distance, and the value the Shader Tree's displacement layers start from.
                                'displacement_distance': float(channel(material, 'displace', .02)),
                                'displacement_value': float(channel(material, 'dispVal', 0)),
                                # Sheen and its tint, which Modo's Principled model alone draws.
                                'sheen': max(0.0, float(channel(material, 'sheen', 0))) if channel(material, 'brdfType', '') == 'principled' else 0.0,
                                'sheen_tint': min(1.0, max(0.0, float(channel(material, 'sheenTint', 0))))}
    from .group_scale import material as scale_material
    return scale_material(material,value,channel)


# The sun's width in the sky, in degrees, at a solar disc size of 100%.
SUN_DEGREES = 0.53
# The most polygons a mesh may have for its material's Modo smoothing angle to be worked out for it in Python: about
# three seconds' work for 75,000 polygons and ten for 250,000, done once for a mesh and kept until the mesh changes.
# Where the geometry adapter smooths (rows.smooth_normals, about a second for 1.5 million polygons) there is no limit.
SMOOTHING_ANGLE_FACES = 300000
# Textures that lay their own UVs out worked out for a whole mesh the adapter read at once (whole_mesh_sets); off, a
# polygon at a time, as before 0.5.3.1 (for comparing the two: tools/probe_cl_whole_sets.py).
WHOLE_MESH_SETS = True
# Why each mesh the adapter read was then taken a polygon at a time, by its name: the latest reading's.
SLOW_READS = {}


def solar_discs(result):
    """Show the sun of a physically based sky as a disc. The camera sees a disc of Modo's width and of the colour
    Modo's own renderer gives it, which Disc In-Scatter changes; that disc lights nothing. The sun light itself is
    made as wide, and one given a spread wider than the disc keeps it, for its softer shadows."""
    import math
    from .daylight import disc as disc_radiance
    for environment in result.get('environments', []):
        for layer in environment.get('layers', []):
            if layer.get('kind') != 'physical' or layer.get('solar_disc', 0) <= 0 or not environment.get('camera', True):
                continue
            for light in result.get('lights', []):
                if light.get('identity') == layer.get('sun_identity'):
                    light['angle'] = max(light.get('angle', 0), SUN_DEGREES * layer['solar_disc'])
                    toward = layer['sun_direction']
                    length = math.sqrt(sum(v * v for v in toward)) or 1.0
                    seen = disc_radiance(math.degrees(math.asin(max(-1.0, min(1.0, toward[1] / length)))), float(layer.get('haze', 2.0)),
                                         float(layer.get('inscatter', 0.0)), bool(layer.get('normalize')))
                    light['disc'] = {'radiance': [v * float(environment.get('intensity', 1.0)) for v in seen], 'angle': SUN_DEGREES * layer['solar_disc']}


def picture_size(scene, camera=None):
    """The size the picture is rendered at: the Render item's resolution, or the camera's where it overrides it (the
    render camera's, unless another is given)."""
    render, camera = scene.renderItem, camera or scene.renderCamera
    width, height = int(channel(render, 'resX', 1280)), int(channel(render, 'resY', 720))
    if camera is not None and channel(camera, 'resOverride', 0):
        width, height = int(channel(camera, 'resX', width)), int(channel(camera, 'resY', height))
    return width, height


def camera_motion_blur(scene):
    """Whether Motion Blur is on on the scene's render camera, Modo's own switch."""
    try:
        return bool(int(channel(scene.renderCamera, 'motionBlur', 0)))
    except Exception:
        return False


# A Modo Mesh Light's shape is its Prototype mesh's (Properties > Prototype), read for the light alone: past this many
# polygons it is left out, said in a notice.
MESH_LIGHT_POLYGONS = 200000


def mesh_light_prototypes(scene):
    """The ids of the meshes Modo's Mesh Lights take their shapes from. Modo never renders such a mesh as a surface: it
    is the light (tools/probe_cl_mesh_light_modo.py: seen with Visible to Camera off, it is not there at all)."""
    found = set()
    for light in scene.items('meshLight', superType=False):
        try:
            found.update(i.id for i in light.itemGraph('shadeLoc').forward() if i.type == 'mesh')
        except Exception:
            pass
    return found


def without_mesh_light_prototypes(meshes, prototypes):
    """The meshes, less those that are Mesh Lights' Prototypes (mesh_light_prototypes)."""
    if not prototypes:
        return meshes
    return [m for m in meshes if str(m.get('source_item') or m.get('identity', '')).split('|')[0] not in prototypes]


def mesh_light_shape(light, warnings):
    """A Modo Mesh Light's shape: its Prototype mesh as rendered (deformed), in local points and polygons, with the
    matrix it stands at (the prototype's where the light says Use Prototype Transform, else the light's own). None,
    with a notice, where it has no prototype, the prototype is hidden (Modo's own renderer then gives no light) or has
    no polygons."""
    import modo
    try:
        prototypes = [i for i in light.itemGraph('shadeLoc').forward() if i.type == 'mesh']
    except Exception:
        prototypes = []
    if len(prototypes) != 1:
        warnings.append('Mesh light %s gives no light: it needs one mesh as its Prototype.' % light.name)
        return None
    prototype = prototypes[0]
    if not render_visible(prototype):
        warnings.append('Mesh light %s gives no light: its Prototype %s is hidden, and Modo lights only from a shown one.' % (light.name, prototype.name))
        return None
    mesh = modo.meshgeometry.MeshProvider.meshFromMeshChannel(prototype._item, 'deformed')
    count = mesh.PolygonCount()
    if not count or count > MESH_LIGHT_POLYGONS:
        warnings.append('Mesh light %s gives no light: its Prototype %s has %s polygons.' % (
            light.name, prototype.name, 'no' if not count else '%d (the limit is %d)' % (count, MESH_LIGHT_POLYGONS)))
        return None
    points = lx.object.Point(mesh.PointAccessor())
    vertices = []
    for index in range(mesh.PointCount()):
        points.SelectByIndex(index)
        vertices.append([float(v) for v in points.Pos()])
    polygons = lx.object.Polygon(mesh.PolygonAccessor())
    faces = []
    for index in range(count):
        polygons.SelectByIndex(index)
        if polygons.Type() not in (lx.symbol.iPTYP_FACE, lx.symbol.iPTYP_PSUB, lx.symbol.iPTYP_SUBD) or polygons.VertexCount() < 3:
            continue
        corners = []
        for corner in range(polygons.VertexCount()):
            points.Select(polygons.VertexByIndex(corner))
            corners.append(points.Index())
        faces.append(corners)
    if not faces:
        warnings.append('Mesh light %s gives no light: its Prototype %s has no surface polygons.' % (light.name, prototype.name))
        return None
    own = bool(channel(light, 'useSrcXfrm', 1))
    return {'vertices': vertices, 'faces': faces, 'matrix': world_matrix(prototype if own else light), 'prototype': prototype.id}


def world_area(shape):
    """The area of a shape's polygons where its matrix puts them (rows are the basis vectors, as in the snapshot)."""
    m = shape['matrix']
    world = [[v[0] * m[0 + a] + v[1] * m[4 + a] + v[2] * m[8 + a] + m[12 + a] for a in range(3)] for v in shape['vertices']]
    area = 0.0
    for face in shape['faces']:
        for i in range(1, len(face) - 1):
            a, b, c = world[face[0]], world[face[i]], world[face[i + 1]]
            e1, e2 = [b[k] - a[k] for k in range(3)], [c[k] - a[k] for k in range(3)]
            n = (e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0])
            area += .5 * math.sqrt(sum(v * v for v in n))
    return area


# Modo's Alembic loader's own items (alembicIO.lx): streamed meshes, curves and point clouds, read from the file at
# each time asked. Meshes loaded as Modo meshes with an Alembic streaming deformer are ordinary meshes, bent.
ALEMBIC_ITEMS = ('AlembicMesh', 'AlembicCurves', 'AlembicCloud')


def alembic_items(scene):
    """The scene's streamed Alembic items; none where Modo's Alembic loader is not there to name their types."""
    found = []
    for kind in ALEMBIC_ITEMS:
        try:found.extend(scene.items(kind, superType=False))
        except (LookupError, RuntimeError, TypeError, ValueError):pass
    return found


def snapshot(evaluated_geometry=False,reuse_geometry=None,refresh_materials=False,dirty_meshes=None,shading_kept=False):
    """The scene as MoonRay is to be given it. The Shader Tree's order and its layer masks are found once for the
    reading (layers.held_tree), not again for each material's stack."""
    from .layers import held_tree
    with held_tree():
        return _snapshot(evaluated_geometry,reuse_geometry,refresh_materials,dirty_meshes,shading_kept)


def _snapshot(evaluated_geometry=False,reuse_geometry=None,refresh_materials=False,dirty_meshes=None,shading_kept=False):
    SLOW_READS.clear()
    scene = modo.Scene()
    try:
        from . import modo_color
        modo_color.refresh()
    except Exception:pass
    if scene.items('replicator',superType=False):
        # Render Cache resolves generated replica transforms and source meshes.
        evaluated_geometry = True
    if any(properties.read(item).get('override') for item in scene.items('meshInst',superType=False)):
        evaluated_geometry = True
    if scene.items('proxy',superType=False):
        # Scene Proxies render what their scene files hold: their surfaces are Modo's render cache's, as Modo renders
        # them, with no mesh of this scene to read (evaluated.proxies).
        evaluated_geometry = True
    if alembic_items(scene):
        # Alembic streamed in as its own items (Alembic Mesh, Curves, Point Cloud): their surfaces are Modo's render
        # cache's, frame by frame from the file, with no mesh channel to read.
        evaluated_geometry = True
    from .mask_types import needs_cache
    for mask in scene.items('mask',superType=False):
        targets = mask.itemGraph('shadeLoc').forward()
        if needs_cache(channel(mask,'ptyp',''),channel(mask,'ptag',''),any(item.type in ('mesh','meshInst','replicator','groupLocator') for item in targets)) or channel(mask,'submask',False):
            evaluated_geometry = True
    camera = scene.renderCamera
    # The camera keyed for this frame in the Camera Sequence, where one is: one of Modo's renders in place of the
    # render camera, and one of MoonRay's camera items is the one rendered through (below, with the MoonRay items).
    from . import camera_sequence
    keyed = camera_sequence.keyed(scene, round(lx.service.Selection().GetTime() * float(scene.fps)))
    if keyed is not None and not keyed[1]:
        camera = keyed[0]
    if camera is None:
        raise ValueError('The scene needs a render camera.')
    projection = channel(camera,'projType','persp')
    if projection not in ('persp','ortho'):
        raise ValueError('Unsupported camera projection: '+projection)
    warnings = []
    smoothed_whole = []
    render = scene.renderItem
    width, height = picture_size(scene, camera)
    aperture_x = float(channel(camera, 'apertureX', .036))
    aperture_y = float(channel(camera, 'apertureY', .024))
    pixel_aspect = float(channel(render,'pAspect',1))
    if channel(camera,'resOverride',0):
        pixel_aspect = float(channel(camera,'pAspect',pixel_aspect))
    fit = channel(camera, 'filmFit', 'fill')
    from .camera import framing, offsets
    aperture_x, moonray_pixel_aspect = framing(width,height,aperture_x,aperture_y,pixel_aspect,fit)
    ortho_width=float(properties.read(camera).get('ortho_width',aperture_x*float(channel(camera,'target',1))/max(1e-9,float(channel(camera,'focalLen',.05)))))
    film_offset=offsets(float(channel(camera,'offsetX',0)),float(channel(camera,'offsetY',0)),projection,aperture_x,ortho_width,pixel_aspect)
    for name, default in [('filmRoll', 0), ('distort', 0), ('squeeze', 1)]:
        if channel(camera, name, default) != default:
            warnings.append('Camera %s is not translated.' % name)
    # Modo's Edge Weighting (0.5 is even) has nothing to go to: MoonRay's bokeh is even across the lens.
    if channel(camera, 'dof', 0) and abs(float(channel(camera, 'irisBias', .5)) - .5) > 1e-4:
        warnings.append('Camera %s: Edge Weighting is not followed: the bokeh is even across the lens.' % camera.name)
    result = {'camera': {'matrix': world_matrix(camera),
                         'identity':camera.id,
                         'film_offset':film_offset,
                         'pixel_aspect':moonray_pixel_aspect,
                         'projection':projection,
                         'ortho_width':ortho_width,
                         'shutter_length':float(channel(camera,'blurLen',.5)),
                         'shutter_offset':float(channel(camera,'blurOff',0)),
                         'focal_mm': float(channel(camera, 'focalLen', .05)) * 1000,
                         'film_mm': aperture_x * 1000,
                         'dof': bool(channel(camera, 'dof', 0)),
                         'f_stop': float(channel(camera, 'fStop', 4)),
                         'focus_distance': float(channel(camera, 'focusDist', 4)),
                         'iris_blades': int(channel(camera, 'irisBlades', 0)),
                         'iris_rotation': float(channel(camera, 'irisRot', 0))},
              'width': width, 'height': height, 'materials': {}, 'meshes': [], 'lights': []}
    # Modo's stereo: which eye or eyes, how far apart, where they converge, and the composite of the two.
    if channel(camera, 'stereo', 0):
        result['camera']['stereo'] = {'eye': str(channel(camera, 'stereoEye', 'both')),
                                      'interocular': float(channel(camera, 'ioDist', .065)),
                                      'convergence': float(channel(camera, 'convDist', 2.0)),
                                      'composite': str(channel(camera, 'stereoComp', 'stereoNone'))}
    # Modo's overscan: how much more than the frame is rendered, 1 for none.
    overscan = float(channel(camera, 'overscan', 1.0))
    if overscan > 1.0:
        result['camera']['overscan'] = overscan
    # Modo's Displacement Rate (pixels), which displaced meshes are tessellated to where the scene follows Modo.
    result['displacement_rate'] = float(channel(render, 'dispRate', 1.0))
    # Another camera for MoonRay's adaptive tessellation: the one chosen; with a fixed dicing camera, it (or the render
    # camera) held at the Dicing Frame, so that a moving camera does not move the triangles.
    stored = properties.scene_settings()
    chosen = stored.get('dicing_camera') or ''
    rendering = stored.get('render', {}) if isinstance(stored.get('render'), dict) else {}
    if int(rendering.get('displacement_tessellation', 1)) == 2:
        frame = float(rendering.get('dicing_frame', -1.0))
        if frame < 0:
            frame = float(channel(render, 'first', 0))
        fps = float(scene.fps) if getattr(scene, 'fps', 0) else 24.0
        view = dicing_view(scene, chosen or scene.renderCamera.id, width, height, pixel_aspect, warnings, time=frame / fps)
        if view:
            result['dicing_camera'] = view
    elif chosen:
        view = dicing_view(scene, chosen, width, height, pixel_aspect, warnings)
        if view:
            result['dicing_camera'] = view
    if channel(render,'region',False):
        bounds = [float(channel(render,k,v)) for k,v in [('regX0',0),('regY0',0),('regX1',1),('regY1',1)]]
        if not (0<=bounds[0]<bounds[2]<=1 and 0<=bounds[1]<bounds[3]<=1):
            raise ValueError('Modo render region is not a valid normalized rectangle')
        result['region'] = bounds
    if projection=='ortho':
        warnings.append('Orthographic width uses target distance and film/focal ratio; reference parity is unverified.')
    result['_full_capture']=reuse_geometry is None
    native_shape_materials = {}
    from .layers import ordered_items, material_tag
    if reuse_geometry is not None and not refresh_materials:
        result['materials']=reuse_geometry['materials'];result['native_materials']=reuse_geometry.get('native_materials',{})
        result['meshes']=[dict(mesh) for mesh in reuse_geometry['meshes']]
        if reuse_geometry.get('_evaluated_data') is not None:result['_evaluated_data']=reuse_geometry['_evaluated_data']
        warnings.extend(reuse_geometry.get('warnings',[]))
    else:
        material_candidates = {}
        # An edit of materials, the meshes kept: only the materials something rendered wears are read. A material on
        # hidden meshes alone had its Shader Tree stack and its images read at every edit of any other (Modo's
        # Shader Tree is slow to ask). A mesh shown or hidden, or tagged anew, is a reading of the whole scene.
        worn = worn_tags(reuse_geometry) if reuse_geometry is not None and refresh_materials and not evaluated_geometry else None
        from . import left_out
        warnings.extend(left_out.group_blends(scene.items('mask',superType=False),channel))
        from .layers import ordered
        for material in reversed(ordered(scene.renderItem)):
            from .materials import active as material_active
            unread = left_out.unread_material(material,channel)
            if unread:
                warnings.append(unread)
            if not properties.is_material(material) or not material_active(material) or not channel(material, 'enable', 1):
                continue
            try:
                tag = material_tag(material)
            except ValueError as exc:
                if not evaluated_geometry:
                    warnings.append('Material %s: %s' % (material.name, exc))
                continue
            if tag is None or (worn is not None and tag not in worn):
                continue
            material_candidates.setdefault(tag,[]).append(material)
            result['materials'][tag] = material_values(material, warnings)
            if material.type=='advancedMaterial' and not properties.read(material).get('native_shader'):
                # What of Modo's material MoonRay is not given as Modo renders it, as measured against Modo's renders.
                if float(channel(material,'reflAmt',0))>0 and not channel(material,'reflSpec',1):
                    warnings.append("%s: a reflection amount apart from the specular amount (Match Specular off) is not followed." % material.name)
                # Principled settings MoonRay's material has nothing for.
                if channel(material,'brdfType','')=='principled':
                    for name,label in (('specTint','Specular Tint'),('flatness','Flatness')):
                        if float(channel(material,name,0))>0:
                            warnings.append("%s: %s is not followed: MoonRay's material has nothing like it." % (material.name,label))
            if channel(material,'subsAmt',0) or result['materials'][tag].get('anisotropy',0) or result['materials'][tag].get('sheen',0):
                result['materials'][tag]['shader'] = 'DwaBaseMaterial'
            if result['materials'][tag].get('anisotropy',0) and result['materials'][tag]['shader'] != 'DwaBaseMaterial':
                warnings.append('Anisotropy requires MoonShine Material: ' + material.name)
            if channel(material, 'tranAmt', 0):
                if channel(material, 'disperse', 0):
                    warnings.append('Dispersion uses an Abbe approximation of Modo’s violet-to-red index span: ' + material.name)
                if channel(material, 'metallic', 0) or channel(material, 'coatAmt', 0):
                    result['materials'][tag]['shader']='DwaBaseMaterial'
        if not evaluated_geometry:
            image_layers(scene, result['materials'], warnings)
            from .layers import material_stack
            for tag,candidates in material_candidates.items():
                inherited = [m for m in material_candidates.get('',[]) if m not in candidates] if tag else []
                result['materials'][tag]['material_stack'] = material_stack(scene,candidates+inherited,warnings,tag)
        for tag, material in result['materials'].items():
            maps = material.get('textures', {})
            if material.get('shader') == 'DwaBaseMaterial':
                if 'specCol' in maps:
                    warnings.append('MoonShine uses dielectric IOR or metallic base color; specular-color maps are not translated: ' + (tag or 'base material'))
                continue
        from . import shader_library
        from .layers import material_stack
        library = {}
        for item in scene.items('advancedMaterial', superType=True):
            held=properties.read(item)
            if held.get('native_shader') or held.get('materialx_override'):
                try:
                    tag = material_tag(item)
                except ValueError:
                    tag = None
                library[item.id] = material_stack(scene,[item],warnings,tag)[0]
        names = {item.id: item.UniqueName() for item in scene.items('advancedMaterial', superType=True)}
        result['materials'], library = shader_library.mend(result['materials'], library, warnings, names)
        result['native_materials'] = library
        shader_library.attach_dependencies(result['materials'],library)
        if evaluated_geometry:
            from . import evaluated
            cached=reuse_geometry.get('_evaluated_data') if reuse_geometry else None
            if cached and dirty_meshes:
                # Edited meshes: their surfaces read again, the others' as they were (incremental.classify).
                data=evaluated.capture(lx.service.Selection().GetTime(),only=dirty_meshes,before=cached)
            else:
                data=dict(cached,surfaces=[dict(v) for v in cached['surfaces']]) if cached else evaluated.capture(lx.service.Selection().GetTime())
            result['_evaluated_data']=data
            # Scene Proxies' surfaces once each, shaded by their own scenes.
            evaluated.proxies(data, scene, lx.service.Selection().GetTime(), warnings)
            native_shape_materials = result['materials']
            # An edit of meshes alone: each Shader Tree stack's material as the last reading made it (shading_kept).
            result['materials'] = evaluated.assign_materials(data, scene, warnings, shading_kept=shading_kept)
            result['materials'], _ = shader_library.mend(result['materials'], library, warnings, names)
            shader_library.attach_dependencies(result['materials'],library)
            result['meshes'] = evaluated.meshes(data, result['materials'], warnings, scene)
            from . import reference_points
            if reference_points.wanted(result['materials']):
                # Modo's render cache gives each piece its points as rendered, not which of the mesh's points they are:
                # they serve as their own rest positions, so that glitter in reference space draws (as in object space,
                # its flakes moving with a deformer).
                for mesh in result['meshes']:
                    if reference_points.NAME not in (mesh.get('point_attributes') or {}):
                        mesh['point_attributes'] = dict(mesh.get('point_attributes') or {}, **{reference_points.NAME: {'kind': 'vec3', 'values': mesh['vertices']}})
            result['extra_geometry']=evaluated.extra_geometry(data,warnings)
            warnings.extend(left_out.vertex_maps_lost(result['materials']))
        if reuse_geometry is not None and refresh_materials and not evaluated_geometry:
            from . import reference_points
            # Rest positions come with the meshes: a material that now asks for them (glitter turned on) reads them again.
            if (coordinates.descriptors(result['materials']) != coordinates.descriptors(reuse_geometry['materials'])
                    or reference_points.wanted(result['materials']) != reference_points.wanted(reuse_geometry['materials'])):
                return snapshot(evaluated_geometry=False)
            result['meshes']=[dict(mesh) for mesh in reuse_geometry['meshes'] if not dirty_meshes or mesh['identity'].split('|')[0] not in dirty_meshes]
        # Resolve each visible instance to one mesh prototype, including hidden sources.
        instances = {}
        from . import primitive_attributes
        instance_attributes = {}
        for instance in ([] if evaluated_geometry or reuse_geometry is not None else scene.items('meshInst', superType=False)):
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
                instances.setdefault(source.id, []).append((instance.id,world_matrix(instance)))
                # What this instance alone carries for its material to read.
                instance_attributes[instance.id]=primitive_attributes.read(instance)
            except (ValueError, LookupError) as exc:
                warnings.append('Instance %s: %s.' % (instance.name, exc))
        # Rest positions, where a material reads its surface in reference space (glitter): reference_points.
        from . import reference_points
        rest_wanted = reference_points.wanted(result['materials'])
        # Fresh read-only evaluated meshes; never change selection, time or scene geometry.
        for item in ([] if evaluated_geometry or (reuse_geometry is not None and not dirty_meshes) else scene.items('mesh', superType=False)):
            if dirty_meshes and item.id not in dirty_meshes:continue
            if not render_visible(item) and item.id not in instances:
                continue
            mesh = modo.meshgeometry.MeshProvider.meshFromMeshChannel(item._item, 'deformed')
            if not mesh.PolygonCount():
                continue
            groups = {}
            # For each group, which of the mesh's surface polygons its faces are, in order: for maps with a value for
            # each face corner.
            ordinals = {}
            # Worked out once for each material, not for each polygon: a node graph's is found by following its nodes.
            tag_descriptors = {}
            transform = world_matrix(item)
            # The mesh's weight and colour maps, for its materials to read (vertex_maps).
            from . import vertex_maps
            painted = vertex_maps.read(mesh)
            # Colour maps that hold vectors, as a MoonRay scene brought in had them: given back as vectors.
            kept = properties.read(item)
            vertex_maps.as_vectors(painted, kept.get('vertex_map_kinds') or {})
            if kept.get('string_attributes'):
                # Words kept by point, face or corner, while the mesh still has the points and polygons they were for.
                polygons_of = lx.object.Polygon(mesh.PolygonAccessor())
                sizes = []
                for index in range(mesh.PolygonCount()):
                    polygons_of.SelectByIndex(index)
                    if polygons_of.VertexCount() >= 3:
                        sizes.append(polygons_of.VertexCount())
                for name in vertex_maps.strings(painted, kept['string_attributes'], sizes, mesh.PointCount()):
                    warnings.append('%s: the words of %s no longer match its points or polygons, and are left out' % (item.name, name))

            told_missing = set()

            def missing_uvs(name, tag, count):
                """A polygon without the UV map its material's textures ask for: given UVs of 0, so that the render
                goes on, with a notice once for each map and material of each mesh. A material whose texture names a UV
                map of another mesh (a tyre's sidewall map, on a mesh that has none) stopped the render here."""
                if (name, tag) not in told_missing:
                    told_missing.add((name, tag))
                    warnings.append('Mesh %s has no UV values in map %s on some polygons, which material %s reads: '
                                    'they are rendered with that map at 0. Give the mesh that UV map, or the '
                                    'texture a UV map the mesh has.' % (item.name, name, tag or '(base)'))
                return [[0.0, 0.0]] * count

            def polygon(face, tag, subdivision, uv_of, normals, ordinal):
                """Put one polygon with its like. uv_of(name) is its corners' values in a UV map, or nothing."""
                # Polygons no material is set on carry Modo's own tag, which names no material: they wear the
                # scene's base material, and take the UVs its layers ask for.
                maps = (result['materials'].get(tag) or result['materials'].get('', {})).get('textures', {})
                uv_name = (result['materials'].get(tag) or result['materials'].get('', {})).get('uv_map', '') or (next(iter(maps.values()))['uv_map'] if maps else '')
                face_uv = uv_of(uv_name)
                if uv_name and not face_uv:
                    face_uv = missing_uvs(uv_name, tag, len(face))
                # A UV map several images read, each moved or scaled its own way, is read from the polygon once.
                read = {uv_name: face_uv}
                extra_uvs = {}
                if tag not in tag_descriptors:
                    tag_descriptors[tag] = coordinates.descriptors({tag:(result['materials'].get(tag) or result['materials'].get('', {}))})
                for key, descriptor in tag_descriptors[tag].items():
                    source_name = descriptor.get('uv_map','')
                    source_uv = []
                    if descriptor.get('projection','uv') == 'uv':
                        if source_name not in read:
                            read[source_name] = uv_of(source_name) or missing_uvs(source_name, tag, len(face))
                        source_uv = read[source_name]
                    # The points as a list, made once for the mesh (rows.Rows keeps it): read through the row of numbers a
                    # point at a time, a car's moved and projected UVs took twice as long.
                    listed = vertices.rows() if hasattr(vertices, 'rows') else vertices
                    extra_uvs[key] = coordinates.face(descriptor, [listed[v] for v in face], source_uv, transform)
                groups.setdefault((subdivision, uv_name), []).append((face, tag, face_uv, normals, extra_uvs))
                ordinals.setdefault((subdivision, uv_name), []).append(ordinal)

            def uv_source(whole, name, tags=None):
                """A UV map's value at every corner of a mesh the adapter read whole, 0 at the corners of polygons
                without it, which polygon() gives the same way (missing_uvs), with its notice for each material of
                those polygons (of tags, by their places among the mesh's tags, where given). None where it cannot."""
                which = whole.uv_map(name)
                count = len(whole.counts)
                valid = whole.uv_valid[which] if which is not None else None
                if valid is not None and valid.count(1) == count:
                    return whole.uv_values[which]
                lacking = {whole.tag_indices[f] for f in range(count) if (valid is None or not valid[f])}
                for index in sorted(lacking if tags is None else lacking & set(tags)):
                    missing_uvs(name, whole.tags[index], 0)
                if valid is None:
                    corners = len(whole.indices)
                    return Rows(array('f', bytes(8 * corners)), 2, 'zeros:%d' % corners)
                return rows_mask(whole.uv_values[which], 2, whole.counts, bytes(valid))

            def whole_mesh_sets(whole, faces, tag_descriptors, transform):
                """Each texture's own UVs for a mesh the adapter read whole, {key: a UV for every corner}: those of the
                polygons whose material has the texture worked out as polygon() works them, 0 for the rest. None where
                a polygon lacks a UV map a texture reads, which the polygon-at-a-time reading says."""
                used = sorted(set(whole.tag_indices))
                keys = {}
                for index in used:
                    for key, descriptor in tag_descriptors.get(whole.tags[index], {}).items():
                        keys.setdefault(key, (descriptor, set()))[1].add(index)
                sets = {}
                for key, (descriptor, having) in sorted(keys.items()):
                    source = []
                    if descriptor.get('projection', 'uv') == 'uv':
                        source = uv_source(whole, descriptor.get('uv_map', ''), having)
                        if source is None:
                            return None
                    values = coordinates.mesh_corners(descriptor, whole.vertices, faces, source, transform)
                    if len(having) < len(used):
                        # Only some materials have the texture: the others' corners are 0, as polygon() leaves them.
                        table = bytes(1 if i in having else 0 for i in range(256))
                        if max(used) > 255:
                            return None
                        keep = bytes(array('B', whole.tag_indices)).translate(table)
                        masked = rows_mask(values if hasattr(values, 'data') else values, 2, whole.counts, keep)
                        if masked is None:
                            flat_keep = [k for k, n in zip(keep, whole.counts) for _ in range(n)]
                            masked = [v if k else [0.0, 0.0] for v, k in zip(values, flat_keep)]
                        values = masked
                    sets[key] = values
                return sets

            from . import mesh_reader
            from .rows import mask_corners as rows_mask, Rows
            from array import array
            whole = mesh_reader.read(mesh)
            if whole is not None:
                # A heavy mesh, read in one go by the native adapter.
                vertices = whole.vertices
                if whole.small:
                    warnings.append('Skipped curve/line polygon in ' + item.name)
                mesh_reader.SURFACES_ONLY[item.id] = (mesh.PolygonCount(), mesh.PointCount()) if not whole.lines and not whole.small else None
                # The usual mesh, all of one kind of polygon with one UV map for all its materials and nothing worked out
                # for each polygon, is put together whole. Any other is taken a polygon at a time below.
                plain = len(whole.counts) and whole.subdivided.count(whole.subdivided[0]) == len(whole.subdivided)
                # The UV map each material's polygons are drawn with, by its place among the mesh's tags.
                named = {}
                for which in set(whole.tag_indices) if plain else ():
                    tag = whole.tags[which]
                    maps = (result['materials'].get(tag) or result['materials'].get('', {})).get('textures', {})
                    named[which] = (result['materials'].get(tag) or result['materials'].get('', {})).get('uv_map', '') or (next(iter(maps.values()))['uv_map'] if maps else '')
                    if tag not in tag_descriptors:
                        tag_descriptors[tag] = coordinates.descriptors({tag:(result['materials'].get(tag) or result['materials'].get('', {}))})
                names = set(named.values())

                def whole_group(source, uv_name, ordinal):
                    """A group of polygons all drawn with one UV map, put together whole: (its faces, tags, UVs, normals,
                    textures' own UVs), or None where a polygon lacks a UV map it is drawn with or a texture reads."""
                    which = source.uv_map(uv_name)
                    complete = which is not None and source.uv_valid[which].count(1) == len(source.counts)
                    # A polygon without the UV map it is drawn with: 0 there, and the notice (uv_source).
                    drawn = (source.uv_values[which] if complete else uv_source(source, uv_name)) if uv_name else []
                    if drawn is None:
                        return None
                    faces_of = source.faces()
                    # Textures that lay their own UVs out (moved, or projected), worked out for the whole group at once
                    # (coordinates.mesh_corners), where they were worked out a polygon at a time below.
                    sets = whole_mesh_sets(source, faces_of, tag_descriptors, transform)
                    if sets is None or (sets and not WHOLE_MESH_SETS):
                        return None
                    normal = source.normal_values is not None and source.normal_valid.count(1) == len(source.counts)
                    ordinals[(bool(source.subdivided[0]), uv_name)] = ordinal
                    return (faces_of, [source.tags[i] for i in source.tag_indices], drawn if uv_name else (source.uv_values[which] if complete else []),
                            source.normal_values if normal else [], sets)
                made = {}
                if plain and len(names) == 1:
                    uv_name = next(iter(names))
                    group = whole_group(whole, uv_name, list(range(len(whole.counts))))
                    if group is not None:
                        made[(bool(whole.subdivided[0]), uv_name)] = group
                elif plain and len(names) > 1:
                    # Materials drawn with different UV maps (a tyre's tread and sidewall): the polygons of each map
                    # gathered out as a part of their own (mesh_reader.Part), and each part put together whole.
                    by_name = {}
                    for face, which in enumerate(whole.tag_indices):
                        by_name.setdefault(named[which], []).append(face)
                    for uv_name, faces_of in sorted(by_name.items()):
                        part = mesh_reader.Part(whole, faces_of)
                        group = whole_group(part, uv_name, list(faces_of))
                        if group is None:
                            made = {}
                            break
                        made[(bool(whole.subdivided[0]), uv_name)] = group
                if made:
                    groups.update(made)
                    whole = None
                else:
                    for key in [k for k in ordinals if k[0] == bool(whole.subdivided[0])] if plain else ():
                        ordinals.pop(key, None)
                    SLOW_READS[item.name] = ('mixed subdivision' if not plain else 'a polygon lacks a UV map it is drawn with, or a '
                                             'texture reads one it lacks: %s' % sorted(names))
            if whole is not None:
                chosen = {}
                offset = 0
                indices, uv_values, uv_valid = whole.indices, whole.uv_values, whole.uv_valid
                normal_values, normal_valid = whole.normal_values, whole.normal_valid
                for index, count in enumerate(whole.counts):
                    limit = offset + count

                    def uv_of(name, index=index, offset=offset, limit=limit):
                        if name not in chosen:
                            chosen[name] = whole.uv_map(name)
                        which = chosen[name]
                        return uv_values[which][offset:limit] if which is not None and uv_valid[which][index] else []
                    polygon(list(indices[offset:limit]), whole.tags[whole.tag_indices[index]], bool(whole.subdivided[index]), uv_of,
                            normal_values[offset:limit] if normal_values is not None and normal_valid[index] else [], index)
                    offset = limit
            elif not groups:
                points = lx.object.Point(mesh.PointAccessor())
                polygons = lx.object.Polygon(mesh.PolygonAccessor())
                vertices, point_indices = [], {}
                for index in range(mesh.PointCount()):
                    points.SelectByIndex(index)
                    point_indices[int(points.ID())] = index
                    vertices.append(list(points.Pos()))
                uv_maps = {}
                normal_map = first_map(mesh, lx.symbol.i_VMAP_NORMAL)
                tags = lx.object.StringTag(polygons)
                surfaces = 0
                for index in range(mesh.PolygonCount()):
                    polygons.SelectByIndex(index)
                    if lxu.utils.decodeID4(polygons.Type()) in ('CURV','BEZR','BSPL','LINE','OPNT'):continue
                    count = polygons.VertexCount()
                    if count < 3:
                        warnings.append('Skipped curve/line polygon in ' + item.name)
                        continue
                    try:
                        tag = tags.Get(lx.symbol.i_POLYTAG_MATERIAL) or ''
                    except LookupError:
                        tag = ''

                    def uv_of(name, count=count):
                        if name not in uv_maps:
                            uv_maps[name] = first_map(mesh, lx.symbol.i_VMAP_TEXTUREUV, name)
                        return corner_values(polygons, uv_maps[name], count, 2)
                    polygon([point_indices[int(polygons.VertexByIndex(v))] for v in range(count)], tag,
                            lxu.utils.decodeID4(polygons.Type()) in ('SUBD', 'PSUB'), uv_of, corner_values(polygons, normal_map, count, 3), surfaces)
                    surfaces += 1
            transform = world_matrix(item)
            rest = None
            if rest_wanted:
                try:
                    rest = reference_points.read(item, len(vertices))
                except (LookupError, RuntimeError, AttributeError, TypeError) as exc:
                    warnings.append('Rest positions of %s could not be read: %s.' % (item.name, exc))
                if rest is None:
                    # A deformer that adds or takes away points leaves no base point for each: the points as rendered
                    # serve, so that glitter in reference space draws (its flakes moving with the deformer, as in object
                    # space) rather than fail.
                    rest = vertices
            object_settings = options.object_values(properties.read(item))
            instance_records = sorted(instances.get(item.id, []),key=lambda pair:pair[0])
            if item.id in instances and render_visible(item):
                instance_records = [(item.id,transform)] + instance_records
            transforms = [value for identity,value in instance_records]
            from .rows import Faces, smoothing_available
            # Smoothed by the geometry adapter, a mesh of any size takes its material's Modo smoothing angle.
            native_smoothing = smoothing_available()
            for (subdivision, uv_name), tagged_faces in sorted(groups.items()):
                if isinstance(tagged_faces, tuple):
                    # Put together whole, above.
                    faces, face_materials, whole_uvs, whole_normals, whole_sets = tagged_faces
                    face_uvs = face_normals = extras = None
                else:
                    faces, face_materials, face_uvs, face_normals, extras = zip(*tagged_faces)
                    whole_uvs = [uv for values in face_uvs for uv in values] if all(face_uvs) else []
                    whole_normals = [n for values in face_normals for n in values] if all(face_normals) else []
                    whole_sets = {key:[uv for face,values in zip(faces,extras) for uv in values.get(key,[[0,0]]*len(face))]
                                  for key in sorted({k for values in extras for k in values})}
                result['meshes'].append({'name': item.name, 'identity':item.id+'|'+str(subdivision)+'|'+uv_name, 'vertices': vertices,
                                         'uv_sets': whole_sets,
                                         # Faces as the adapter handed them over stay the run they came in (rows.Faces).
                                         'faces': faces if isinstance(faces, Faces) else list(faces), 'matrix': transform, 'material': '',
                                         'face_materials': list(face_materials),
                                         'uvs': whole_uvs,
                                         'normals': whole_normals,
                                         'geometry_settings': object_settings, 'object_override': object_settings['override'],
                                         'smooth': object_settings['smooth'] if object_settings['override'] else True,
                                         'subdivision_level': object_settings['level'],
                                         'subdivision': object_settings['subdivision'] if object_settings['override'] else subdivision})
                if result['meshes'][-1]['subdivision']:
                    # Its creases: Modo's subdivision weights, as MoonRay's crease sharpness.
                    creases, corners = subdivision_creases(mesh, result['meshes'][-1]['faces'])
                    if creases:
                        result['meshes'][-1]['creases'] = creases
                    if corners:
                        result['meshes'][-1]['corners'] = corners
                declared = {}
                for face_tag in set(face_materials):
                    # Polygons no material is set on wear the scene's base material.
                    worn = result['materials'].get(face_tag) or result['materials'].get('', {})
                    said = next((layer.get('smoothing_angle') for layer in reversed(worn.get('material_stack', [worn])) if layer.get('smoothing_angle') is not None), None)
                    if said is None:
                        # Modo's own smoothing angle, as Modo draws the mesh. Working it out takes seconds on a heavy mesh,
                        # which is then smoothed all over, as MoonRay smooths, and named in a notice.
                        modo_said = next((layer.get('modo_smoothing_angle') for layer in reversed(worn.get('material_stack', [worn])) if layer.get('modo_smoothing_angle') is not None), None)
                        if modo_said is not None and modo_said < 179.0:
                            if len(faces) <= SMOOTHING_ANGLE_FACES or native_smoothing:
                                said = modo_said
                            elif item.name not in smoothed_whole:
                                smoothed_whole.append(item.name)
                    if said is not None:
                        declared[face_tag] = said
                if declared:
                    result['meshes'][-1]['material_smoothing'] = declared
                if painted:
                    point_maps, corner_maps = vertex_maps.for_faces(painted, ordinals.get((subdivision, uv_name), []))
                    if point_maps:
                        result['meshes'][-1]['point_attributes'] = point_maps
                    if corner_maps:
                        result['meshes'][-1]['corner_attributes'] = corner_maps
                if rest is not None:
                    result['meshes'][-1].setdefault('point_attributes', {})[reference_points.NAME] = {'kind': 'vec3', 'values': rest}
                own_attributes = primitive_attributes.read(item)
                if own_attributes:
                    result['meshes'][-1]['attributes'] = own_attributes
                if item.id in instances:
                    result['meshes'][-1]['instances'] = transforms
                    result['meshes'][-1]['instance_ids'] = [identity for identity,value in instance_records]
                    held = [own_attributes if identity == item.id else instance_attributes.get(identity, []) for identity,value in instance_records]
                    if any(held):
                        result['meshes'][-1]['instance_attributes'] = held
        # World/locator projections cannot share baked UVs across transforms.
        # Keep ordinary UV instances shared; expand only affected prototypes.
        expanded = []
        descriptors = coordinates.descriptors(result['materials'])
        for mesh in result['meshes']:
            projected = {k:d for k,d in descriptors.items() if d.get('projection','uv')!='uv' and k in mesh.get('uv_sets',{})}
            if not projected or 'instances' not in mesh:
                expanded.append(mesh)
                continue
            for index, transform in enumerate(mesh['instances']):
                instance = dict(mesh,name=mesh['name']+' / instance %d'%index,
                                identity=mesh['identity']+'|'+mesh['instance_ids'][index],matrix=transform,uv_sets=dict(mesh['uv_sets']))
                instance.pop('instances')
                instance.pop('instance_ids',None)
                for key,descriptor in projected.items():
                    instance['uv_sets'][key] = [uv for face in mesh['faces'] for uv in coordinates.face(
                        descriptor,[mesh['vertices'][v] for v in face],[],transform)]
                expanded.append(instance)
        result['meshes'] = expanded
    if dirty_meshes and reuse_geometry:
        ranks={m['identity']:i for i,m in enumerate(reuse_geometry['meshes'])}
        result['meshes'].sort(key=lambda m:(ranks.get(m['identity'],len(ranks)),m['identity']))
    for item in scene.items('light'):
        if not render_visible(item):
            continue
        types = {'sunLight': 'DistantLight', 'pointLight': 'SphereLight', 'areaLight': 'RectLight', 'spotLight': 'SpotLight',
                 # A Mesh Light shines from its Prototype mesh's shape (mesh_light_shape), as MoonRay's MeshLight.
                 'meshLight': 'MeshLight'}
        if item.type not in types:
            warnings.append('Skipped unsupported light: ' + item.name)
            continue
        try:
            material = item.material
        except AttributeError:
            # A light the modo module does not know as one (a Mesh Light): its light material is a child of it.
            material = next((child for child in item.children() if child.type == 'lightMaterial'), None)
        if material and not channel(material, 'enable', 1):
            # Its material's eye is off in the Shader Tree: in Modo's own renders such a light gives no light.
            warnings.append('Light %s gives no light: its light material is switched off in the Shader Tree.' % item.name)
            continue
        light = {'kind': types[item.type], 'identity':item.id, 'name':item.name, 'matrix': world_matrix(item),
                 'color': color(material, 'lightCol') if material else [1, 1, 1],
                 'intensity': float(channel(item, 'radiance', 1)),
                 'angle': max(.01, math.degrees(float(channel(item, 'spread', 0)))),
                 'radius': max(.001, float(channel(item, 'radius', .05))),
                 'cone': min(179.0, max(.01, math.degrees(float(channel(item, 'cone', math.pi / 4))))),
                 'soft_edge': max(0.0, math.degrees(float(channel(item, 'edge', 0)))),
                 'width': float(channel(item, 'width', 1)), 'height': float(channel(item, 'height', 1)),
                 # Visible to Camera: the light seen shining where it stands (MoonRay's visible_in_camera).
                 'camera_visible': bool(channel(item, 'visCam', 0))}
        if item.type == 'meshLight':
            shape = mesh_light_shape(item, warnings)
            if shape is None:
                continue
            light.update(matrix=shape['matrix'], shape=shape, area=world_area(shape))
            if not light['area'] > 0:
                warnings.append('Mesh light %s gives no light: its Prototype has no area.' % item.name)
                continue
        if item.type == 'sunLight' and channel(item,'sunPos',False):
            from .sun import matrix as sun_matrix, physical as physical_sun
            light['matrix']=sun_matrix(item)
            # Modo works out this sun's colour and strength from its height and the haze.
            light['color'],light['intensity']=physical_sun(item)
        # Modo's radiance and MoonRay's intensity are different measures for every kind of light.
        from .light_units import intensity as moonray_intensity
        light['intensity']=moonray_intensity(item.type,light['intensity'],light,str(channel(item,'shape','rectangle')))
        result['lights'].append(light)
    for kind in (('textureLayer',) if evaluated_geometry else ('replicator', 'textureLayer')):
        if scene.items(kind, superType=False):
            warnings.append('%s items are not translated in this version.' % kind)
    for volume in scene.items('volume',superType=False):
        if not properties.scene_settings().get('production',{}).get('objects',{}).get(volume.id,{}).get('geometry_file'):
            warnings.append('Volume '+volume.name+': attach a VDB file in MoonRay > Light Links, Emitters and Volumes (Objects / geometry).')
    from .environments import collect as collect_environments
    result['environments'] = collect_environments(scene, warnings)
    # With every light hidden the scene is still lit where an environment is: said, since Modo's own renderer
    # leaves such a scene dark unless Global Illumination is on.
    lit=[environment for environment in result['environments'] if environment.get('indirect',True)
         and not environment.get('dark') and not (environment.get('layers') and all(layer.get('dark') for layer in environment['layers']))]
    if not result['lights'] and lit and list(scene.items('light')):
        warnings.append('No lights are visible. The scene is lit by the environment (%s); turn its eye off, or set Environment lights the scene to Follow Modo in the MoonRay preferences, for no light at all.'
                        % ', '.join(environment['name'] for environment in lit))
    solar_discs(result)
    from .extra_geometry import collect as collect_extra,furs as furs_extra
    result['extra_geometry']=reuse_geometry.get('extra_geometry',[]) if reuse_geometry is not None and not dirty_meshes and not (evaluated_geometry and refresh_materials) else result.get('extra_geometry',[])+furs_extra(scene,warnings,result['meshes']) if evaluated_geometry else collect_extra(scene,warnings,properties.scene_settings().get('production',{}))
    from .extra_geometry import without_fur_bases
    # A Fur material that grows nothing is most often on a mesh that is hidden or set not to render: said, since
    # nothing else does.
    try:
        grown=any('|fur|' in str(entry.get('identity','')) for entry in result['extra_geometry'])
        if not grown and any(channel(layer,'enable',1) for layer in scene.items('furMaterial')):
            warnings.append('A Fur material is in the scene but no fur is grown: the mesh wearing it is hidden or set to Render: Off, or wears another material.')
    except (LookupError,RuntimeError,TypeError):pass
    result['meshes']=without_fur_bases(result['meshes'],result['extra_geometry'],warnings)
    # A Mesh Light's Prototype is the light, not a surface of the scene: it would hide the light and block its light.
    result['meshes']=without_mesh_light_prototypes(result['meshes'],mesh_light_prototypes(scene))
    from .scene_references import capture as capture_references
    result['scene_references']=capture_references(scene,result)
    result['time']=lx.service.Selection().GetTime();result['fps']=float(scene.fps);result['frame']=round(result['time']*result['fps'])
    result['asset_owners']={}
    for identity,settings in properties.scene_settings().get('production',{}).get('objects',{}).items():
        if settings.get('geometry_file'):
            try:result['asset_owners'][identity]={'matrix':world_matrix(scene.item(identity))}
            except LookupError:warnings.append('Geometry asset owner is missing: '+identity)
    result['motion_policies']={identity:v.get('motion_topology','auto') for identity,v in properties.scene_settings().get('production',{}).get('objects',{}).items()}
    result['source_assets']=[]
    for clip in scene.items('videoStill',superType=False):
        filename=channel(clip,'filename','')
        if filename:
            from .textures import resolve_scene_source
            try:path,_=resolve_scene_source(filename,getattr(scene,'filename',None))
            except ValueError as exc:
                warnings.append(str(exc));path=filename
            from pathlib import Path
            result['source_assets'].append(str(Path(path).resolve()))
    from .entities import collect as collect_entities
    result['entities']=collect_entities(scene,warnings)
    from .camera_choice import modo_render_moonray
    picked = any(entity.get('parameters', {}).get('modo_render_camera') for entity in result['entities'])
    chosen_in_modo = modo_render_moonray(scene) if keyed is None and not picked else None
    if chosen_in_modo is not None:
        # A MoonRay camera made Modo's render camera (it is a Modo camera too) is the one rendered through, where no
        # MoonRay camera is chosen to render through already.
        from .entities import catalog as entity_catalog
        for entity in result['entities']:
            if entity_catalog().get(entity.get('class'), {}).get('category') == 'camera':
                entity.setdefault('parameters', {})['modo_render_camera'] = entity.get('identity') == chosen_in_modo.id
    if keyed is not None:
        # A key decides which camera renders: a MoonRay camera item keyed is the one rendered through, and a Modo
        # camera keyed renders in place of every MoonRay one.
        from .entities import catalog as entity_catalog
        for entity in result['entities']:
            if entity_catalog().get(entity.get('class'), {}).get('category') == 'camera':
                entity.setdefault('parameters', {})['modo_render_camera'] = bool(keyed[1]) and entity.get('identity') == keyed[0].id
        result['camera_keyed'] = keyed[0].id
    # A MoonRay camera rendered through is a Modo camera too: its own Overscan holds, not the render camera's.
    through = next((entity for entity in result['entities'] if entity.get('parameters', {}).get('modo_render_camera')), None)
    if through is not None:
        try:
            through_item = scene.item(through['identity'])
            overscan = float(channel(through_item, 'overscan', 1.0))
            from .entities import uses_modo_lens
            if uses_modo_lens(through_item, through.get('class')):
                # Its own shutter too, as its Camera tab has it (Blur Length and Blur Offset), for the motion read.
                result['camera']['shutter_length'] = float(channel(through_item, 'blurLen', .5))
                result['camera']['shutter_offset'] = float(channel(through_item, 'blurOff', 0))
        except (LookupError, KeyError, TypeError, ValueError):
            overscan = float(result['camera'].get('overscan', 1.0))
        if overscan > 1.0:
            result['camera']['overscan'] = overscan
        else:
            result['camera'].pop('overscan', None)
    # Native shapes are absent from Modo's evaluated surface list but still use named materials.
    for entity in result['entities']:
        tag = entity.get('parameters', {}).get('modo_material')
        if tag in native_shape_materials:
            result['materials'].setdefault(tag, native_shape_materials[tag])
    from .native_light_links import capture as capture_light_links
    result['native_light_links']=capture_light_links(scene,result,warnings)
    # Modo's light volumetrics and environment fog, as meshes of MoonRay fog: made anew at every reading, meshes kept
    # from an earlier one included, where the lights and the camera now stand.
    from .volumetrics import capture as capture_volumetrics
    capture_volumetrics(scene,result,warnings)
    if smoothed_whole:
        warnings.append("Smoothed all over rather than within their material's smoothing angle, having more than %d polygons: %s. "
                        'Set a smoothing angle in the MoonRay material settings to hold it.'
                        % (SMOOTHING_ANGLE_FACES, ', '.join(smoothed_whole[:6]) + (' ...' if len(smoothed_whole) > 6 else '')))
    unworn(scene, result, warnings)
    # The materials nothing rendered wears are not handed on: their images were made ready for MoonRay (maketx) and
    # MoonLightIPR all the same, a hidden mesh's textures among them.
    if result.get('meshes'):
        worn = worn_tags(result)
        result['materials'] = {tag: material for tag, material in result['materials'].items() if tag in worn}
    result['cryptomatte_objects'] = cryptomatte_objects(scene)
    result['warnings'] = sorted(set(warnings))
    return result


def cryptomatte_objects(scene):
    """The Cryptomatte name and ID each object is given in its Cryptomatte tab, {item: {'name', 'id'}}, for those given one."""
    import json
    found = {}
    for item in scene.items('locator', superType=True):
        try:
            held = json.loads(item.readTag(properties.TAG))
        except (LookupError, RuntimeError, ValueError, TypeError):
            continue
        if isinstance(held, dict) and (held.get('crypto_name') or held.get('crypto_id')):
            found[item.id] = {'name': str(held.get('crypto_name') or '').strip(), 'id': int(held.get('crypto_id') or 0)}
    return found
