"""Match shutter samples by identity before publishing a motion snapshot."""
import math

IDENTITY=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]


def indexed(nodes, label):
    result={}
    for node in nodes:
        key=node.get('identity',node.get('name'))
        if key is None or key in result:
            raise ValueError('Motion blur requires unique '+label+' identities')
        result[key]=node
    return result


def instances(mesh):
    identities=mesh.get('instance_ids',[])
    transforms=mesh.get('instances',[])
    if len(identities)!=len(transforms) or len(set(identities))!=len(identities):
        raise ValueError('Motion blur requires one unique identity per instance transform')
    return dict(zip(identities,transforms))


def apply_motion(scene, start, end, endpoints):
    if len(endpoints)!=2 or not all(math.isfinite(float(value)) for value in endpoints) or endpoints[0]>=endpoints[1]:
        raise ValueError('Motion blur requires two finite, increasing shutter endpoints')
    # Work on copies so an incompatible sample cannot leave half-mutated state.
    camera=dict(scene['camera'])
    for sample in (start,end):
        if sample['camera'].get('identity')!=camera.get('identity') or sample['camera'].get('projection','persp')!=camera.get('projection','persp'):
            raise ValueError('Motion blur cannot switch cameras or projection types during the shutter')
    camera.update(matrix=start['camera']['matrix'],matrix_close=end['camera']['matrix'])
    if camera.get('projection','persp')=='persp':
        camera.update(focal_mm=start['camera']['focal_mm'],focal_mm_close=end['camera']['focal_mm'])
    warnings=list(scene.get('warnings',[]))
    def frozen(label, center, a, b, keys):
        if any(a.get(key)!=center.get(key) or b.get(key)!=center.get(key) for key in keys):
            warning=label+' changes during the shutter; these controls use the frame-time value.'
            if warning not in warnings: warnings.append(warning)
    frozen('Camera settings',scene['camera'],start['camera'],end['camera'],
           ('film_offset','film_mm','pixel_aspect','ortho_width','f_stop','focus_distance','iris_blades','iris_rotation'))
    expanded=[]
    for category in ('meshes','lights'):
        center=indexed(scene.get(category,[]),category)
        first=indexed(start.get(category,[]),category)
        last=indexed(end.get(category,[]),category)
        if set(center)!=set(first) or set(center)!=set(last):
            raise ValueError('Motion blur cannot export changing '+category+' identities')
        outputs=[]
        for identity,original in center.items():
            a,b=first[identity],last[identity]
            node=dict(original)
            node.update(matrix=a.get('matrix',IDENTITY),matrix_close=b.get('matrix',IDENTITY))
            if category=='lights':
                if a['kind']!=node['kind'] or b['kind']!=node['kind']:
                    raise ValueError('Motion blur cannot change a light type')
                frozen('Light '+str(identity),original,a,b,('color','intensity','angle','radius','width','height','cone','soft_edge'))
                outputs.append(node)
                continue
            for sample in (a,b):
                if sample['faces']!=node['faces'] or len(sample['vertices'])!=len(node['vertices']):
                    raise ValueError('Motion blur requires stable topology: '+str(identity))
                for key in ('material','face_materials','visibility','subdivision','subdivision_level'):
                    if sample.get(key)!=node.get(key):
                        raise ValueError('Motion blur cannot change '+key+': '+str(identity))
                if ('instances' in sample)!=('instances' in node):
                    raise ValueError('Motion blur cannot change instance structure')
            frozen('Mesh attributes '+str(identity),original,a,b,('uvs','uv_sets','normals','creases'))
            node.update(vertices=a['vertices'],vertices_close=b['vertices'])
            if 'instances' in node:
                cm,am,bm=instances(original),instances(a),instances(b)
                if set(cm)!=set(am) or set(cm)!=set(bm):
                    raise ValueError('Motion blur cannot change instance identities')
                for key in cm:
                    value=dict(node,identity=str(identity)+'|'+str(key),name=node['name']+' / '+str(key),matrix=am[key],matrix_close=bm[key])
                    value.pop('instances');value.pop('instance_ids',None)
                    outputs.append(value)
            else:
                outputs.append(node)
        if category=='meshes': expanded=outputs
        else: lights=outputs
    frozen('Materials and environments',scene,start,end,('materials','environments'))
    scene.update(camera=camera,meshes=expanded,lights=lights,motion_steps=list(endpoints),warnings=warnings)
