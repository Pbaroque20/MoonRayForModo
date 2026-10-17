"""Modo 16.1 scene sampling. Call only from Modo's main/UI thread."""
import math
import lx
import lxu.utils
import lxifc
import modo
from . import properties, options, coordinates


def channel(item, name, default=None):
    value = item.channel(name)
    return value.get() if value is not None else default


def color(item, prefix, default=(1, 1, 1)):
    return [float(channel(item, prefix + '.' + axis, default[i])) for i, axis in enumerate('RGB')]


def world_matrix(item):
    rows = lx.object.Matrix(item.channel('worldMatrix').get()).Get4()
    return [float(value) for row in rows for value in row]


def subdivision_creases(mesh, faces):
    """Modo's subdivision weights on a subdivided mesh's edges and points, as MoonRay's creases: (a, b, sharpness) for
    each weighted edge of faces, and (point, sharpness) for each weighted point, by point index. A weight of 1 (100%)
    is a sharpness of 10, as sharp as MoonRay's creases go; the importer reads them back the same way (rdl_import). None
    of either for a mesh without a Subdivision weight map."""
    map_id = first_map(mesh, lx.symbol.i_VMAP_SUBDIV)
    if map_id is None:
        return [], []
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


def dicing_view(scene, identity, width, height, pixel_aspect, warnings):
    """The camera chosen to work adaptive tessellation out for: {'entity': id} for a MoonRay camera item, a Modo
    camera's view framed as the render camera's is, or None for the render camera itself or one that is gone."""
    try:
        item = scene.item(identity)
    except LookupError:
        warnings.append('The dicing camera chosen is no longer in the scene; the render camera is used.')
        return None
    if item.type != 'camera':
        return {'entity': item.id}
    if item.id == scene.renderCamera.id:
        return None
    projection = channel(item, 'projType', 'persp')
    if projection not in ('persp', 'ortho'):
        warnings.append('The dicing camera %s has a projection MoonRay does not dice for; the render camera is used.' % item.name)
        return None
    from .camera import framing, offsets
    aperture_x, moonray_pixel_aspect = framing(width, height, float(channel(item, 'apertureX', .036)), float(channel(item, 'apertureY', .024)),
                                               pixel_aspect, channel(item, 'filmFit', 'fill'))
    ortho_width = float(properties.read(item).get('ortho_width', aperture_x * float(channel(item, 'target', 1)) / max(1e-9, float(channel(item, 'focalLen', .05)))))
    return {'matrix': world_matrix(item), 'identity': item.id, 'projection': projection, 'ortho_width': ortho_width,
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
            carried.update(mesh.get('face_materials') or [mesh.get('material', '')])
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


def material_values(material):
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
    value = {'name':material.name,'color': [c * diffuse_amount for c in diffuse],
                                **controls,
                                'node_graph': arranged(settings.get('node_graph')),
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
                                'anisotropy': float(channel(material, 'aniso', 0)),
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
                                'clearcoat_roughness': float(channel(material, 'coatRough', .01))}
    from .group_scale import material as scale_material
    return scale_material(material,value,channel)


# The sun's width in the sky, in degrees, at a solar disc size of 100%.
SUN_DEGREES = 0.53
# The most polygons a mesh may have for its material's Modo smoothing angle to be worked out for it: about three
# seconds' work for 75,000 polygons and ten for 250,000, done once for a mesh and kept until the mesh changes.
SMOOTHING_ANGLE_FACES = 300000


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


def snapshot(evaluated_geometry=False,reuse_geometry=None,refresh_materials=False,dirty_meshes=None):
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
    from .mask_types import needs_cache
    for mask in scene.items('mask',superType=False):
        targets = mask.itemGraph('shadeLoc').forward()
        if needs_cache(channel(mask,'ptyp',''),channel(mask,'ptag',''),any(item.type in ('mesh','meshInst','replicator','groupLocator') for item in targets)) or channel(mask,'submask',False):
            evaluated_geometry = True
    camera = scene.renderCamera
    if camera is None:
        raise ValueError('The scene needs a render camera.')
    projection = channel(camera,'projType','persp')
    if projection not in ('persp','ortho'):
        raise ValueError('Unsupported camera projection: '+projection)
    warnings = []
    smoothed_whole = []
    render = scene.renderItem
    width, height = int(channel(render, 'resX', 1280)), int(channel(render, 'resY', 720))
    if channel(camera, 'resOverride', 0):
        width, height = int(channel(camera, 'resX', width)), int(channel(camera, 'resY', height))
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
    # Another camera for MoonRay's adaptive tessellation, where one is chosen.
    chosen = properties.scene_settings().get('dicing_camera') or ''
    if chosen:
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
        for material in reversed(list(ordered_items(scene.renderItem))):
            from .materials import active as material_active
            if not properties.is_material(material) or not material_active(material) or not channel(material, 'enable', 1):
                continue
            try:
                tag = material_tag(material)
            except ValueError as exc:
                if not evaluated_geometry:
                    warnings.append('Material %s: %s' % (material.name, exc))
                continue
            if tag is None:
                continue
            material_candidates.setdefault(tag,[]).append(material)
            result['materials'][tag] = material_values(material)
            if material.type=='advancedMaterial' and not properties.read(material).get('native_shader'):
                # What of Modo's material MoonRay is not given as Modo renders it, as measured against Modo's renders.
                if float(channel(material,'reflAmt',0))>0 and not channel(material,'reflSpec',1):
                    warnings.append("%s: a reflection amount apart from the specular amount (Match Specular off) is not followed." % material.name)
            if channel(material,'subsAmt',0) or channel(material,'aniso',0):
                result['materials'][tag]['shader'] = 'DwaBaseMaterial'
            if channel(material, 'aniso', 0) and result['materials'][tag]['shader'] != 'DwaBaseMaterial':
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
        result['native_materials'] = library
        shader_library.attach_dependencies(result['materials'],library)
        if evaluated_geometry:
            from . import evaluated
            cached=reuse_geometry.get('_evaluated_data') if reuse_geometry else None
            data=dict(cached,surfaces=[dict(v) for v in cached['surfaces']]) if cached else evaluated.capture(lx.service.Selection().GetTime())
            result['_evaluated_data']=data
            native_shape_materials = result['materials']
            result['materials'] = evaluated.assign_materials(data, scene, warnings)
            shader_library.attach_dependencies(result['materials'],library)
            result['meshes'] = evaluated.meshes(data, result['materials'], warnings, scene)
            result['extra_geometry']=evaluated.extra_geometry(data,warnings)
        if reuse_geometry is not None and refresh_materials and not evaluated_geometry:
            if coordinates.descriptors(result['materials']) != coordinates.descriptors(reuse_geometry['materials']):
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
            vertex_maps.as_vectors(painted, properties.read(item).get('vertex_map_kinds') or {})

            def polygon(face, tag, subdivision, uv_of, normals, ordinal):
                """Put one polygon with its like. uv_of(name) is its corners' values in a UV map, or nothing."""
                # Polygons no material is set on carry Modo's own tag, which names no material: they wear the
                # scene's base material, and take the UVs its layers ask for.
                maps = (result['materials'].get(tag) or result['materials'].get('', {})).get('textures', {})
                uv_name = (result['materials'].get(tag) or result['materials'].get('', {})).get('uv_map', '') or (next(iter(maps.values()))['uv_map'] if maps else '')
                face_uv = uv_of(uv_name)
                # A UV map several images read, each moved or scaled its own way, is read from the polygon once.
                read = {uv_name: face_uv}
                if uv_name and not face_uv:
                    raise ValueError('Mesh %s is missing UV values in map %s.' % (item.name, uv_name))
                extra_uvs = {}
                if tag not in tag_descriptors:
                    tag_descriptors[tag] = coordinates.descriptors({tag:(result['materials'].get(tag) or result['materials'].get('', {}))})
                for key, descriptor in tag_descriptors[tag].items():
                    source_name = descriptor.get('uv_map','')
                    source_uv = []
                    if descriptor.get('projection','uv') == 'uv':
                        if source_name not in read:
                            read[source_name] = uv_of(source_name)
                        source_uv = read[source_name]
                    extra_uvs[key] = coordinates.face(descriptor, [vertices[v] for v in face], source_uv, transform)
                groups.setdefault((subdivision, uv_name), []).append((face, tag, face_uv, normals, extra_uvs))
                ordinals.setdefault((subdivision, uv_name), []).append(ordinal)

            from . import mesh_reader
            whole = mesh_reader.read(mesh)
            if whole is not None:
                # A heavy mesh, read in one go by the native adapter.
                vertices = whole.vertices
                if whole.small:
                    warnings.append('Skipped curve/line polygon in ' + item.name)
                mesh_reader.SURFACES_ONLY[item.id] = (mesh.PolygonCount(), mesh.PointCount()) if not whole.lines and not whole.small else None
                # The usual mesh, all of one kind of polygon with one UV map for all its materials and nothing worked out
                # for each polygon, is put together whole. Any other is taken a polygon at a time below.
                names = set()
                plain = len(whole.counts) and whole.subdivided.count(whole.subdivided[0]) == len(whole.subdivided)
                for which in set(whole.tag_indices) if plain else ():
                    tag = whole.tags[which]
                    maps = (result['materials'].get(tag) or result['materials'].get('', {})).get('textures', {})
                    names.add((result['materials'].get(tag) or result['materials'].get('', {})).get('uv_map', '') or (next(iter(maps.values()))['uv_map'] if maps else ''))
                    if tag not in tag_descriptors:
                        tag_descriptors[tag] = coordinates.descriptors({tag:(result['materials'].get(tag) or result['materials'].get('', {}))})
                    plain = plain and not tag_descriptors[tag]
                if plain and len(names) == 1:
                    uv_name = next(iter(names))
                    which = whole.uv_map(uv_name)
                    complete = which is not None and whole.uv_valid[which].count(1) == len(whole.counts)
                    if complete or not uv_name:
                        normal = whole.normal_values is not None and whole.normal_valid.count(1) == len(whole.counts)
                        tags_of = whole.tags
                        ordinals[(bool(whole.subdivided[0]), uv_name)] = list(range(len(whole.counts)))
                        groups[(bool(whole.subdivided[0]), uv_name)] = (whole.faces(), [tags_of[i] for i in whole.tag_indices],
                            whole.uv_values[which] if complete else [], whole.normal_values if normal else [], {})
                        whole = None
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
            object_settings = options.object_values(properties.read(item))
            instance_records = sorted(instances.get(item.id, []),key=lambda pair:pair[0])
            if item.id in instances and render_visible(item):
                instance_records = [(item.id,transform)] + instance_records
            transforms = [value for identity,value in instance_records]
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
                                         'faces': list(faces), 'matrix': transform, 'material': '',
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
                            if len(faces) <= SMOOTHING_ANGLE_FACES:
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
        types = {'sunLight': 'DistantLight', 'pointLight': 'SphereLight', 'areaLight': 'RectLight', 'spotLight': 'SpotLight'}
        if item.type not in types:
            warnings.append('Skipped unsupported light: ' + item.name)
            continue
        material = item.material
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
                 'width': float(channel(item, 'width', 1)), 'height': float(channel(item, 'height', 1))}
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
            warnings.append('Volume '+volume.name+': attach a VDB file in MoonRay scene controls.')
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
    from .scene_references import capture as capture_references
    result['scene_references']=capture_references(scene,result)
    result['time']=lx.service.Selection().GetTime();result['fps']=float(scene.fps);result['frame']=round(result['time']*result['fps'])
    result['asset_owners']={}
    for identity,settings in properties.scene_settings().get('production',{}).get('objects',{}).items():
        if settings.get('geometry_file'):
            try:result['asset_owners'][identity]={'matrix':world_matrix(scene.item(identity))}
            except LookupError:warnings.append('Geometry asset owner is missing: '+identity)
    result['motion_policies']={identity:v.get('motion_topology','strict') for identity,v in properties.scene_settings().get('production',{}).get('objects',{}).items()}
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
    # Native shapes are absent from Modo's evaluated surface list but still use named materials.
    for entity in result['entities']:
        tag = entity.get('parameters', {}).get('modo_material')
        if tag in native_shape_materials:
            result['materials'].setdefault(tag, native_shape_materials[tag])
    from .native_light_links import capture as capture_light_links
    result['native_light_links']=capture_light_links(scene,result,warnings)
    if smoothed_whole:
        warnings.append("Smoothed all over rather than within their material's smoothing angle, having more than %d polygons: %s. "
                        'Set a smoothing angle in the MoonRay material settings to hold it.'
                        % (SMOOTHING_ANGLE_FACES, ', '.join(smoothed_whole[:6]) + (' ...' if len(smoothed_whole) > 6 else '')))
    unworn(scene, result, warnings)
    result['warnings'] = sorted(set(warnings))
    return result
