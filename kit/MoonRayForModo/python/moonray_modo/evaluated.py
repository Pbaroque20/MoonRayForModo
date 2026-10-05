"""Translate Modo Render Cache surfaces without modifying the current scene."""
import ctypes
import json
import tempfile
from pathlib import Path

_bridge = None

def assign_materials(data, scene, warnings):
    """Use host-resolved Shader Tree membership for each evaluated surface."""
    from .host import material_values, channel
    from .materials import active as material_active
    from .layers import ordered_items, collect
    from .mask_types import tag_kind
    items=list(ordered_items(scene.renderItem))
    order={item.id:index for index,item in enumerate(items)}
    by_id={item.id:item for item in items}
    materials={}
    tags={}
    for surface in data['surfaces']:
        surface.setdefault('source_material',surface['material'])
        surface['material']=surface['source_material']
        surface.setdefault('source_layers',list(surface['layers']))
        surface['layers']=list(surface['source_layers'])
        source_ids={surface['source_item']}
        source=scene.item(surface['source_item'])
        while source.type=='meshInst':
            links=source.itemGraph('source').forward()
            if len(links)!=1 or links[0].id in source_ids: break
            source=links[0];source_ids.add(source.id)
        def matches(item):
            parent=item if item.type=='mask' else item.parent
            while parent and parent.type!='polyRender':
                if not channel(parent,'enable',1) or not channel(parent,'render',1): return False
                if parent.type=='mask':
                    kind,value=tag_kind(channel(parent,'ptyp','')),channel(parent,'ptag','')
                    if kind=='material' and value and value!=surface['material']:
                        return False
                    if kind=='part' and value and value != surface.get('part',''):
                        return False
                    # Other tag/selection mask types are resolved by the native
                    # Render Cache. Only candidates in this surface's host stack
                    # reach this function; never widen membership to all layers.
                    targets=parent.itemGraph('shadeLoc').forward()
                    targets=[i for i in targets if i.type in ('mesh','meshInst','replicator','groupLocator')]
                    applicable_ids=source_ids if channel(parent,'instApply',False) else {surface['source_item']}
                    def contains(target):
                        return target.id in applicable_ids or (target.type=='groupLocator' and any(contains(child) for child in target.children()))
                    if targets and not any(contains(i) for i in targets): return False
                parent=parent.parent
            return True
        # In 16.1 the returned stack may include item masks that still need to
        # be evaluated against the particular instance (not just its prototype).
        stack=tuple(identity for identity in surface['layers'] if identity in by_id and matches(by_id[identity]))
        surface['layers']=list(stack)
        if stack not in tags:
            candidates=[by_id[identity] for identity in stack if identity in by_id
                        and by_id[identity].type in ('advancedMaterial','material.moonrayMoonShine','material.moonrayMaterialX') and material_active(by_id[identity]) and channel(by_id[identity],'enable',1)]
            if not candidates:
                tags[stack]=''
                warnings.append('Evaluated surface has no supported material: '+surface['source_item'])
                continue
            base=min(candidates,key=lambda item:order[item.id])
            tag='evaluated_material_%d' % len(tags)
            tags[stack]=tag
            materials[tag]=material_values(base)
            if channel(base,'subsAmt',0) or channel(base,'aniso',0):
                materials[tag]['shader']='DwaBaseMaterial'
            collect(scene,{tag:materials[tag]},warnings,baked_effects=('displace',),
                    layer_filter=set(stack),material_key=tag)
            if candidates:
                from .layers import material_stack
                materials[tag]['material_stack']=material_stack(scene,candidates,warnings,tag,set(stack))
        surface['material']=tags[stack]
    return materials

def capture(time, path=None, displaced=True):
    global _bridge
    if _bridge is None:
        path = Path(path) if path else Path(__file__).resolve().parents[2] / 'bin/MoonRayGeometry.lx'
        if not path.is_file():
            raise ValueError('Modo evaluated geometry requires MoonRayGeometry.lx. Build/install the geometry adapter and restart Modo.')
        bridge = ctypes.CDLL(str(path))
        bridge.MR_geometry_snapshot_file.argtypes = [ctypes.c_double,ctypes.c_int,ctypes.c_char_p]
        bridge.MR_geometry_snapshot_file.restype = ctypes.c_char_p
        _bridge = bridge
    with tempfile.TemporaryDirectory(prefix='MoonRay-geometry-') as folder:
        output=Path(folder)/'geometry.json'
        error=_bridge.MR_geometry_snapshot_file(float(time),int(displaced),str(output).encode('utf-8'))
        if error:
            raise ValueError('Modo evaluated geometry: '+error.decode('utf-8',errors='replace'))
        with output.open(encoding='utf-8') as stream:
            data=json.load(stream)
    if 'error' in data:
        raise ValueError('Modo evaluated geometry: ' + data['error'])
    return data

def meshes(data, materials, warnings, scene=None):
    """Group identical evaluated prototypes while retaining per-surface transforms."""
    groups = {}
    settings_cache = {}
    from . import options
    if scene is not None:
        from . import properties
    for surface in data['surfaces']:
        visibility = tuple(bool(v) for v in surface['visibility'])
        if not any(visibility):
            continue
        tag = surface['material']
        material = materials.get(tag, materials.get('', {}))
        base = material.get('base_layer_id')
        if base and base not in surface['layers']:
            warnings.append('Evaluated surface %s has a Shader Tree override that is not yet translated.' % surface['source_item'])
        identity=surface['source_item']
        if identity not in settings_cache:
            settings=options.object_values(properties.read(scene.item(identity))) if scene else options.object_values({})
            settings_cache[identity]=settings if settings['override'] else options.object_values({})
        settings=settings_cache[identity]
        if settings['override'] and (settings['angular_tessellation'] or settings['adaptive_error'] or settings['dynamic_tessellation']):
            warning='Evaluated geometry keeps Modo tessellation; MoonRay angular/screen tolerances are bypassed: '+surface['source_item']
            if warning not in warnings: warnings.append(warning)
        key = (surface['source_id'], tag, visibility, tuple(surface['layers']), tuple(sorted(settings.items())))
        groups.setdefault(key, []).append(surface)
    result = []
    for (source, tag, visibility, layers, settings), surfaces in groups.items():
        prototype = data['prototypes'][str(source)]
        if not prototype['segments']:
            warnings.append('Modo returned no mesh segments for evaluated surface ' + surfaces[0]['source_item'])
        if not any(segment['faces'] and len(segment['faces'][0])>=3 for segment in prototype['segments']):continue
        material = materials.get(tag, materials.get('', {}))
        uv_name = material.get('uv_map', '')
        uv_names = [f['name'] for f in prototype['features'] if f['type'] == 0x54585556]
        if uv_name and uv_name not in uv_names:
            raise ValueError('Evaluated mesh is missing UV map ' + uv_name)
        uv_index = uv_names.index(uv_name) if uv_name else 0
        surfaces.sort(key=lambda s:(s['source_item'],s.get('instance_index',0)))
        for segment_index,segment in enumerate(prototype['segments']):
            if not segment['faces'] or len(segment['faces'][0])<3: continue
            indices = [i for face in segment['faces'] for i in face]
            uv_sets = segment['uv_sets']
            if uv_name and uv_index >= len(uv_sets):
                raise ValueError('Modo did not supply UV values for ' + uv_name)
            vertices = segment['vertices']
            if any(i < 0 or i >= len(vertices) for i in indices):
                raise ValueError('Invalid evaluated geometry index')
            attribute_indices = range(len(indices)) if segment.get('face_varying') else indices
            mesh = dict(name=surfaces[0]['source_item'], identity=surfaces[0]['source_item']+'|'+tag+'|'+str(segment_index), vertices=vertices,
                        faces=segment['faces'], matrix=surfaces[0]['matrix'], material=tag,
                        normals=[segment['normals'][i] for i in attribute_indices] if segment['normals'] else [],
                        uvs=[uv_sets[uv_index][i] for i in attribute_indices] if uv_index < len(uv_sets) else [],
                        subdivision=False, subdivision_level=1, smooth=True,
                        object_override=True, evaluated_geometry=True, geometry_settings=dict(settings), visibility=list(visibility))
            from . import coordinates
            descriptors = coordinates.descriptors({tag:material})
            projected = any(d.get('projection','uv')!='uv' for d in descriptors.values())
            named_values = {}
            for key, descriptor in descriptors.items():
                if descriptor.get('projection','uv') != 'uv':
                    continue
                source_name = descriptor.get('uv_map','')
                if source_name.startswith('@index:'):
                    names=sorted(uv_names);uv_index=int(source_name.split(':',1)[1])
                    if uv_index>=len(names):raise ValueError('Evaluated mesh has no UV set '+str(uv_index))
                    source_name=names[uv_index]
                elif not source_name and uv_names:source_name=sorted(uv_names)[0]
                if source_name not in uv_names:
                    raise ValueError('Evaluated mesh is missing UV map '+source_name)
                source_index = uv_names.index(source_name)
                if source_index >= len(uv_sets):
                    raise ValueError('Missing evaluated UV values: '+source_name)
                named_values[key] = coordinates.mesh_corners(descriptor,vertices,segment['faces'],
                    [uv_sets[source_index][i] for i in attribute_indices],mesh['matrix'])
            # World/locator projections differ for every transformed replica.
            # Share vertex arrays in the snapshot, but emit separate assignments.
            separate=projected or not dict(settings)['share_instances']
            for surface in (surfaces if separate else surfaces[:1]):
                value = dict(mesh,uv_sets=dict(named_values),matrix=surface['matrix'])
                if separate:
                    value['name'] = surface['source_item']
                    value['identity'] = surface['source_item']+'|'+str(surface.get('instance_index',0))+'|'+tag+'|'+str(segment_index)
                    for key,descriptor in descriptors.items():
                        if descriptor.get('projection','uv') != 'uv':
                            value['uv_sets'][key] = coordinates.mesh_corners(descriptor,
                                vertices,segment['faces'],[],value['matrix'])
                elif len(surfaces) > 1 or any(s.get('instanced') for s in surfaces):
                    value['instances'] = [s['matrix'] for s in surfaces]
                    value['instance_ids'] = [s['source_item']+'|'+str(s.get('instance_index',0)) for s in surfaces]
                result.append(value)
    return result


def extra_geometry(data,warnings):
    """SDK segments explicitly use 2 vertices for hair/curves, 1 for particles."""
    result=[]
    for surface in data['surfaces']:
        if not any(surface['visibility']):continue
        prototype=data['prototypes'][str(surface['source_id'])]
        for index,segment in enumerate(prototype['segments']):
            faces=segment['faces'];per_face=len(faces[0]) if faces else 0
            if per_face>=3 or not segment['vertices']:continue
            indices=[v for face in faces for v in face] if faces else list(range(len(segment['vertices'])))
            if any(v<0 or v>=len(segment['vertices']) for v in indices):raise ValueError('Invalid curve/particle vertex index')
            kind='curves' if per_face==2 else 'points'
            item=dict(kind=kind,identity=surface['source_item']+'|'+str(surface.get('instance_index',-1))+'|'+surface['material']+'|extra|'+str(index),source_item=surface['source_item'],name=surface['source_item'],material=surface['material'],matrix=surface['matrix'],visibility=list(surface['visibility']),vertices=[segment['vertices'][i] for i in indices])
            radii=segment.get('radii',[])
            item['radii']=[radii[i] for i in indices] if radii else [.001]*len(indices)
            if not radii:warnings.append('Modo did not provide curve/particle radii; using 1 mm: '+surface['source_item'])
            if segment.get('velocities'):item['velocities']=[segment['velocities'][i] for i in indices]
            if kind=='curves':
                item.update(counts=[2]*len(faces),curve_type=0)
                if segment.get('uv_sets'):
                    uvs=segment['uv_sets'][0]
                    item['uvs']=[uvs[2*i if segment.get('face_varying') else face[0]] for i,face in enumerate(faces)]
            result.append(item)
    return result
