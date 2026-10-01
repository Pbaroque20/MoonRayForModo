"""Translate Modo Render Cache surfaces without modifying the current scene."""
import ctypes
import json
from pathlib import Path

_bridge = None

def assign_materials(data, scene, warnings):
    """Use host-resolved Shader Tree membership for each evaluated surface."""
    from .host import material_values, channel
    from .layers import ordered_items, collect
    items=list(ordered_items(scene.renderItem))
    order={item.id:index for index,item in enumerate(items)}
    by_id={item.id:item for item in items}
    materials={}
    tags={}
    for surface in data['surfaces']:
        source_ids={surface['source_item']}
        source=scene.item(surface['source_item'])
        while source.type=='meshInst':
            links=source.itemGraph('source').forward()
            if len(links)!=1 or links[0].id in source_ids: break
            source=links[0];source_ids.add(source.id)
        def matches(item):
            parent=item if item.type=='mask' else item.parent
            while parent and parent.type!='polyRender':
                if not channel(parent,'enable',1): return False
                if parent.type=='mask':
                    kind,value=channel(parent,'ptyp',''),channel(parent,'ptag','')
                    if kind in ('Material','material','MATR') and value and value!=surface['material']:
                        return False
                    if kind not in ('','Material','material','MATR'):
                        warnings.append('Evaluated material mask type is not translated: '+str(kind))
                        return False
                    targets=parent.itemGraph('shadeLoc').forward()
                    targets=[i for i in targets if i.type in ('mesh','meshInst')]
                    if targets and not any(i.id in source_ids for i in targets): return False
                    if channel(parent,'opacity',1)!=1 or channel(parent,'blend','normal')!='normal':
                        warnings.append('Group opacity and blending are not translated: '+parent.name)
                        return False
                parent=parent.parent
            return True
        # In 16.1 the returned stack may include item masks that still need to
        # be evaluated against the particular instance (not just its prototype).
        stack=tuple(identity for identity in surface['layers'] if identity in by_id and matches(by_id[identity]))
        surface['layers']=list(stack)
        if stack not in tags:
            candidates=[by_id[identity] for identity in stack if identity in by_id
                        and by_id[identity].type=='advancedMaterial' and channel(by_id[identity],'enable',1)]
            if not candidates:
                tags[stack]=''
                warnings.append('Evaluated surface has no supported material: '+surface['source_item'])
                continue
            base=min(candidates,key=lambda item:order[item.id])
            tag='evaluated_material_%d' % len(tags)
            tags[stack]=tag
            materials[tag]=material_values(base)
            if channel(base,'subsAmt',0): warnings.append('Subsurface is not translated: '+base.name)
            if channel(base,'aniso',0) and materials[tag]['shader']!='DwaBaseMaterial':
                warnings.append('Anisotropy requires MoonShine Material: '+base.name)
            if channel(base,'tranAmt',0) and (channel(base,'tranDist',0) or channel(base,'disperse',0)):
                warnings.append('Absorption distance and dispersion are not translated: '+base.name)
            collect(scene,{tag:materials[tag]},warnings,baked_effects=('displace',),
                    layer_filter=set(stack),material_key=tag)
        surface['material']=tags[stack]
    return materials

def capture(time, path=None, displaced=True):
    global _bridge
    if _bridge is None:
        path = Path(path) if path else Path(__file__).resolve().parents[2] / 'bin/MoonRayPreview.lx'
        if not path.is_file():
            raise ValueError('Modo evaluated geometry requires the native adapter. Install the kit and restart Modo.')
        bridge = ctypes.CDLL(str(path))
        bridge.MR_geometry_snapshot.argtypes = [ctypes.c_double, ctypes.c_int]
        bridge.MR_geometry_snapshot.restype = ctypes.c_char_p
        _bridge = bridge
    data = json.loads(_bridge.MR_geometry_snapshot(float(time), int(displaced)).decode('utf-8'))
    if 'error' in data:
        raise ValueError('Modo evaluated geometry: ' + data['error'])
    return data

def meshes(data, materials, warnings):
    """Group identical evaluated prototypes while retaining per-surface transforms."""
    groups = {}
    for surface in data['surfaces']:
        visibility = tuple(bool(v) for v in surface['visibility'])
        if not any(visibility):
            continue
        tag = surface['material']
        material = materials.get(tag, materials.get('', {}))
        base = material.get('base_layer_id')
        if base and base not in surface['layers']:
            warnings.append('Evaluated surface %s has a Shader Tree override that is not yet translated.' % surface['source_item'])
        key = (surface['source_id'], tag, visibility, tuple(surface['layers']))
        groups.setdefault(key, []).append(surface)
    result = []
    for (source, tag, visibility, layers), surfaces in groups.items():
        prototype = data['prototypes'][str(source)]
        if not prototype['segments']:
            warnings.append('Modo returned no mesh segments for evaluated surface ' + surfaces[0]['source_item'])
        material = materials.get(tag, materials.get('', {}))
        uv_name = material.get('uv_map', '')
        uv_names = [f['name'] for f in prototype['features'] if f['type'] == 0x54585556]
        if uv_name and uv_name not in uv_names:
            raise ValueError('Evaluated mesh is missing UV map ' + uv_name)
        uv_index = uv_names.index(uv_name) if uv_name else 0
        for segment in prototype['segments']:
            if not segment['faces']: continue
            indices = [i for face in segment['faces'] for i in face]
            uv_sets = segment['uv_sets']
            if uv_name and uv_index >= len(uv_sets):
                raise ValueError('Modo did not supply UV values for ' + uv_name)
            vertices = segment['vertices']
            if any(i < 0 or i >= len(vertices) for i in indices):
                raise ValueError('Invalid evaluated geometry index')
            attribute_indices = range(len(indices)) if segment.get('face_varying') else indices
            mesh = dict(name=surfaces[0]['source_item'], vertices=vertices,
                        faces=segment['faces'], matrix=surfaces[0]['matrix'], material=tag,
                        normals=[segment['normals'][i] for i in attribute_indices] if segment['normals'] else [],
                        uvs=[uv_sets[uv_index][i] for i in attribute_indices] if uv_index < len(uv_sets) else [],
                        subdivision=False, subdivision_level=1, smooth=True,
                        object_override=True, evaluated_geometry=True, visibility=list(visibility))
            if len(surfaces) > 1:
                mesh['instances'] = [s['matrix'] for s in surfaces]
            result.append(mesh)
    return result
