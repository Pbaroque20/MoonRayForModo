"""Translate Modo Render Cache surfaces without modifying the current scene."""
from array import array
import ctypes
from hashlib import blake2b
import json
import tempfile
from pathlib import Path
from .rows import Rows, Faces

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
            from . import properties
            candidates=[by_id[identity] for identity in stack if identity in by_id
                        and properties.is_material(by_id[identity]) and material_active(by_id[identity]) and channel(by_id[identity],'enable',1)]
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

def _coordinates():
    """coordinates, imported once: under Modo every import statement runs through PySide's import hook."""
    global _coordinates
    from . import coordinates
    _coordinates = lambda: coordinates
    return coordinates


# The rows of geometry Modo hands over, kept by their bytes from one reading to the next: an unchanged mesh's lists are
# then the very ones the last reading made, so what was worked out from them, and what was written of them
# (serialization.array keeps that by the lists it came from), is used again. Kept for one reading back.
_ROWS_BEFORE, _ROWS_NOW = {}, {}
_DERIVED_BEFORE, _DERIVED_NOW = {}, {}


def _new_reading():
    global _ROWS_BEFORE, _ROWS_NOW, _DERIVED_BEFORE, _DERIVED_NOW
    _ROWS_BEFORE, _ROWS_NOW = _ROWS_NOW, {}
    _DERIVED_BEFORE, _DERIVED_NOW = _DERIVED_NOW, {}


def flat(rows):
    """The numbers of a list made from a row handed over (rows.Rows), flat, as an array, and a digest of them: what
    MoonLightIPR packs and how a list is known (scene_digest.flat) without walking its numbers again. None for others."""
    return (rows.data, rows.digest) if isinstance(rows, Rows) else None


from . import scene_digest as _scene_digest
# Once, though the module be loaded again.
_scene_digest.FLAT[:] = [each for each in _scene_digest.FLAT if getattr(each, '__module__', None) != __name__] + [flat]


def _derived(kind, sources, build):
    """What is worked out from a reading's lists, kept for the next while those stay the same lists."""
    key = (kind,) + tuple(id(source) for source in sources)
    held = _DERIVED_NOW.get(key) or _DERIVED_BEFORE.get(key)
    if held is not None and all(a is b for a, b in zip(held[0], sources)):
        _DERIVED_NOW[key] = held
        return held[1]
    value = build()
    _DERIVED_NOW[key] = (sources, value)
    return value


def _gather(values, faces, indices, face_varying):
    """A mesh's values at each corner: its own row where Modo gives one value a corner, else picked by the corners."""
    if face_varying:
        return _derived('corners', (values, faces),
                        lambda: values if len(values) == len(indices) else [values[i] for i in range(len(indices))])
    return _derived('points', (values, faces), lambda: [values[i] for i in indices])


def _merged_segments(segments):
    """A surface's segments joined, one for each kind there is (with or without normals, the number of UV sets, a
    value at each corner or at each point): Modo's render cache cuts a mesh into many (41,940 for the 16 surfaces of
    one test scene), and each was a MoonRay object of its own, with all that costs for every one. The same
    polygons, points, normals and UVs, in the same order; kept by its segments' lists, as they are by their bytes."""
    usable = [s for s in segments if s['faces'] and len(s['faces'][0]) >= 3]
    if len(usable) <= 1:
        return usable
    sources = tuple(held for s in usable for held in [s['vertices'], s['faces'], s['normals']] + list(s['uv_sets']))

    def merge():
        kinds = {}
        for segment in usable:
            kind = (bool(segment['normals']), len(segment['uv_sets']), bool(segment.get('face_varying')))
            kinds.setdefault(kind, []).append(segment)
        result = []
        for (normals_held, uv_count, face_varying), members in kinds.items():
            if len(members) == 1:
                result.append(members[0])
                continue
            vertices, faces, normals, uvs = [], [], [], [[] for _ in range(uv_count)]
            for segment in members:
                offset = len(vertices)
                vertices.extend(segment['vertices'])
                faces.extend([[i + offset for i in face] for face in segment['faces']] if offset else segment['faces'])
                if normals_held:
                    normals.extend(segment['normals'])
                for u in range(uv_count):
                    uvs[u].extend(segment['uv_sets'][u])
            result.append(dict(vertices=vertices, faces=faces, normals=normals, uv_sets=uvs, face_varying=face_varying))
        return result
    return _derived('merged', sources, merge)


def _row(entry,held):
    """One row of numbers out of the file they were handed over in: 32-bit floats or whole numbers, `count` entries
    of `width` each, read as the lists the rest of the plugin works with (rows.Rows: the numbers as they came, made
    into lists only where something walks them)."""
    count,width=int(entry['count']),int(entry['width'])
    whole=bool(entry.get('whole'))
    if not count*width:return []
    at=int(entry['at'])
    data=held[at:at+count*width*4]   # held is a memoryview: no copy of the bytes first
    key=(whole,width,blake2b(data,digest_size=16).digest())
    rows=_ROWS_NOW.get(key) or _ROWS_BEFORE.get(key)
    if rows is None:
        values=array('i' if whole else 'f')
        values.frombytes(data)
        rows=Rows(values,width,'row:%d:%d:%s'%(whole,width,key[2].hex()))
    _ROWS_NOW[key]=rows
    return rows


def _faces(corners,sizes,held):
    """A joined segment's faces: its row of corners cut by its row of corner counts. Kept by the bytes of both."""
    row,counts=_row(corners,held),_row(sizes,held)
    if not row or not counts:
        return []
    # The faces' corners flat are the row of corners as it came (rows.Faces).
    return _derived('faces',(row,counts),lambda:Faces(row.data,counts.data,'faces:%s:%s'%(row.digest,counts.digest)))


def _unpack(data,held):
    _new_reading()
    for prototype in data.get('prototypes',{}).values():
        for segment in prototype.get('segments',[]):
            segment.pop('skip',None)
            if isinstance(segment.get('sizes'),dict):
                segment['faces']=_faces(segment['faces'],segment.pop('sizes'),held)
            for key in ('vertices','faces','radii','velocities','normals'):
                if isinstance(segment.get(key),dict):segment[key]=_row(segment[key],held)
            segment['uv_sets']=[_row(entry,held) if isinstance(entry,dict) else entry for entry in segment.get('uv_sets',[])]


def capture(time, path=None, displaced=True, only=None, before=None):
    """Modo's render cache read: every surface, and each surface's segments. only (item identifiers) and before (the
    reading before): the segments of those items' surfaces alone, the others' taken from before by their item, material
    and part; read whole where any is not there to take, or the adapter cannot."""
    global _bridge
    if _bridge is None:
        path = Path(path) if path else Path(__file__).resolve().parents[2] / 'bin/MoonRayGeometry.lx'
        if not path.is_file():
            raise ValueError('Modo evaluated geometry requires MoonRayGeometry.lx. Build/install the geometry adapter and restart Modo.')
        bridge = ctypes.CDLL(str(path))
        bridge.MR_geometry_snapshot_file.argtypes = [ctypes.c_double,ctypes.c_int,ctypes.c_char_p]
        bridge.MR_geometry_snapshot_file.restype = ctypes.c_char_p
        _bridge = bridge
        from . import rows
        rows.adapter(bridge)
    with tempfile.TemporaryDirectory(prefix='MoonRay-geometry-') as folder:
        output=Path(folder)/'geometry.json'
        # Each surface's segments joined by the adapter where it can (MR_geometry_snapshot_merged), else one by one.
        try:rows=_bridge.MR_geometry_snapshot_merged
        except AttributeError:rows=None
        some=None
        if only and before and before.get('prototypes') and all('item' in held for held in before['prototypes'].values()):
            try:some=_bridge.MR_geometry_snapshot_some
            except AttributeError:some=None
        if some is not None:
            some.argtypes=[ctypes.c_double,ctypes.c_int,ctypes.c_char_p,ctypes.c_char_p,ctypes.c_char_p];some.restype=ctypes.c_char_p
            listed='\n'.join(sorted(only)).encode('utf-8')
            rows=lambda moment,flag,out,held:some(moment,flag,out,held,listed)
        if rows is None:
            try:rows=_bridge.MR_geometry_snapshot_binary
            except AttributeError:rows=None
        if rows is not None:
            # The meshes' long rows of numbers come as they are, in a file of their own: written out as text and
            # read back, they were most of what a reading took.
            rows.argtypes=[ctypes.c_double,ctypes.c_int,ctypes.c_char_p,ctypes.c_char_p];rows.restype=ctypes.c_char_p
            held=Path(folder)/'geometry.rows'
            error=rows(float(time),int(displaced),str(output).encode('utf-8'),str(held).encode('utf-8'))
        else:
            error=_bridge.MR_geometry_snapshot_file(float(time),int(displaced),str(output).encode('utf-8'))
        if error:
            raise ValueError('Modo evaluated geometry: '+error.decode('utf-8',errors='replace'))
        with output.open(encoding='utf-8') as stream:
            data=json.load(stream)
        if rows is not None:_unpack(data,memoryview(held.read_bytes()))
    if 'error' in data:
        raise ValueError('Modo evaluated geometry: ' + data['error'])
    if some is not None:
        earlier={(held.get('item'),held.get('material'),held.get('part')):held for held in before['prototypes'].values()}
        for key,held in list(data.get('prototypes',{}).items()):
            if held.get('kept'):
                taken=earlier.get((held.get('item'),held.get('material'),held.get('part')))
                if taken is None or taken.get('kept'):
                    return capture(time,path,displaced)
                data['prototypes'][key]=taken
    return data

def casts_shadow(scene, layers, known):
    """Whether the Shader over a surface has Cast Shadows on. Modo's own six switches for a surface have none for
    shadows (the last is for occlusion rays), so the Shader is asked: of those among the surface's layers, the one
    highest in the Shader Tree, which is the one Modo goes by."""
    if layers not in known:
        if 'order' not in known:
            order = known['order'] = {}

            def walk(item):
                for child in item.children():
                    walk(child)
                    order[child.id] = len(order)
            try:
                walk(scene.renderItem)
            except Exception:
                pass
        cast, best = True, -1
        for identity in layers:
            try:
                layer = scene.item(identity)
                if layer.type != 'defaultShader':
                    continue
                place = known['order'].get(layer.id, 0)
                if place > best:
                    best, cast = place, bool(layer.channel('shadCast').get())
            except Exception:
                continue
        known[layers] = cast
    return known[layers]


def meshes(data, materials, warnings, scene=None):
    """Group identical evaluated prototypes while retaining per-surface transforms."""
    if data.get('skipped'):
        warnings.append('Modo gave %d piece(s) of geometry the adapter could not read; they are left out.' % data['skipped'])
    groups = {}
    settings_cache = {}
    shadows = {}
    from . import options
    if scene is not None:
        from . import properties
    for surface in data['surfaces']:
        visibility = tuple(bool(v) for v in surface['visibility'])
        if scene is not None:
            # The sixth is what shadow rays go by; Modo's own sixth, for occlusion rays, is not that.
            visibility = visibility[:5] + (casts_shadow(scene, tuple(surface['layers']), shadows),)
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
        for segment_index,segment in enumerate(_merged_segments(prototype['segments'])):
            if not segment['faces'] or len(segment['faces'][0])<3: continue
            # The corners flat: the run they came in where they did (rows.Faces).
            indices = _derived('indices', (segment['faces'],), lambda: segment['faces'].data if isinstance(segment['faces'], Faces)
                               else [i for face in segment['faces'] for i in face])
            uv_sets = segment['uv_sets']
            if uv_name and uv_index >= len(uv_sets):
                raise ValueError('Modo did not supply UV values for ' + uv_name)
            vertices = segment['vertices']
            if not _derived('within', (indices, vertices), lambda: not len(indices) or (min(indices) >= 0 and max(indices) < len(vertices))):
                raise ValueError('Invalid evaluated geometry index')
            attribute_indices = range(len(indices)) if segment.get('face_varying') else indices
            mesh = dict(name=surfaces[0]['source_item'], identity=surfaces[0]['source_item']+'|'+tag+'|'+str(segment_index), vertices=vertices,
                        faces=segment['faces'], matrix=surfaces[0]['matrix'], material=tag,
                        normals=_gather(segment['normals'], segment['faces'], indices, segment.get('face_varying')) if segment['normals'] else [],
                        uvs=_gather(uv_sets[uv_index], segment['faces'], indices, segment.get('face_varying')) if uv_index < len(uv_sets) else [],
                        subdivision=False, subdivision_level=1, smooth=True,
                        object_override=True, evaluated_geometry=True, geometry_settings=dict(settings), visibility=list(visibility))
            coordinates = _coordinates()
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
                # A UV map's corners, moved as its layer moves them (the key names how): only the map and the faces
                # come into it, so it holds from one reading to the next while they are the same lists.
                named_values[key] = _derived('named:'+key, (uv_sets[source_index], segment['faces']),
                    lambda: coordinates.mesh_corners(descriptor,vertices,segment['faces'],
                        _gather(uv_sets[source_index], segment['faces'], indices, segment.get('face_varying')),mesh['matrix']))
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
                            # A projection's corners hold from one reading to the next while the mesh's points and
                            # faces are the same lists, the projection the same (its key names it) and, in the
                            # world's space, the mesh stands where it stood.
                            where = None if descriptor.get('object_space') else repr(list(value['matrix']))
                            value['uv_sets'][key] = _derived('projected:%s:%s' % (key, where), (vertices, segment['faces']),
                                lambda descriptor=descriptor, matrix=value['matrix']: coordinates.mesh_corners(descriptor,
                                    vertices,segment['faces'],[],matrix))
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
