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
            affected=set(center)^set(first) | set(center)^set(last)
            if category!='meshes' or any(scene.get('motion_policies',{}).get(str(i).split('|')[0],'strict')=='strict' for i in affected):
                raise ValueError('Motion blur cannot export changing '+category+' identities')
            warnings.append('Changing mesh membership uses frame-time visibility; births/deaths inside the shutter are not integrated.')
        outputs=[]
        for identity,original in center.items():
            a,b=first.get(identity,original),last.get(identity,original)
            policy=scene.get('motion_policies',{}).get(str(identity).split('|')[0],'strict')
            if category=='meshes' and policy=='freeze' and any(v['faces']!=original['faces'] or len(v['vertices'])!=len(original['vertices']) for v in (a,b)):
                outputs.append(dict(original));warnings.append('Frame-time topology used without deformation blur: '+str(identity));continue
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
                # MoonRay supports per-instance linear velocity. Keep the shared
                # prototype when scale/rotation/shear are constant over the shutter.
                stable=all(all(math.isclose(am[key][i],bm[key][i],rel_tol=1e-8,abs_tol=1e-10) for i in range(16) if i not in (12,13,14)) for key in cm)
                if stable:
                    fps=float(scene.get('fps',24));span=endpoints[1]-endpoints[0]
                    if not math.isfinite(fps) or fps<=0:raise ValueError('Motion requires positive finite FPS')
                    node.update(instances=[am[key] for key in cm],instances_close=[bm[key] for key in cm],
                        instance_ids=list(cm),instance_velocities=[[(bm[key][i]-am[key][i])*fps/span for i in (12,13,14)] for key in cm],
                        instance_evaluation_frame=endpoints[0],matrix=list(IDENTITY))
                    node.pop('matrix_close',None);outputs.append(node);continue
                for key in cm:
                    value=dict(node,source_item=str(key).split('|')[0],identity=str(identity)+'|'+str(key),name=node['name']+' / '+str(key),matrix=am[key],matrix_close=bm[key])
                    value.pop('instances');value.pop('instance_ids',None)
                    outputs.append(value)
            else:
                outputs.append(node)
        if category=='meshes': expanded=outputs
        else: lights=outputs
    extras=[]
    center=indexed(scene.get('extra_geometry',[]),'curves/points');first=indexed(start.get('extra_geometry',[]),'curves/points');last=indexed(end.get('extra_geometry',[]),'curves/points')
    affected=set(center)^set(first) | set(center)^set(last)
    if any(scene.get('motion_policies',{}).get(str(i).split('|')[0],'strict')=='strict' for i in affected):raise ValueError('Motion blur requires stable curve/particle identities')
    if affected:warnings.append('Particle/strand membership uses frame-time visibility; births/deaths inside the shutter are not integrated.')
    for identity,original in center.items():
        a,b=first.get(identity,original),last.get(identity,original)
        policy=scene.get('motion_policies',{}).get(str(identity).split('|')[0],'strict')
        if policy=='velocity':
            velocity=original.get('velocities',[])
            if len(velocity)!=len(original['vertices']):raise ValueError('Velocity topology mode requires one velocity per point/strand vertex: '+str(identity))
            fps=float(scene.get('fps',24))
            if fps<=0:raise ValueError('Motion requires positive FPS')
            points=lambda t:[[p[k]+v[k]*t/fps for k in range(3)] for p,v in zip(original['vertices'],velocity)]
            value=dict(original,vertices=points(endpoints[0]),vertices_close=points(endpoints[1]));value.pop('velocities',None);extras.append(value);continue
        if policy=='freeze':extras.append(dict(original));continue
        if len(a['vertices'])!=len(original['vertices']) or len(b['vertices'])!=len(original['vertices']) or a.get('counts')!=b.get('counts'):raise ValueError('Motion blur requires stable curve/point topology')
        node=dict(original,matrix=a.get('matrix',IDENTITY),matrix_close=b.get('matrix',IDENTITY),vertices=a['vertices'],vertices_close=b['vertices'])
        extras.append(node)
    owners={}
    for identity,owner in scene.get('asset_owners',{}).items():
        if identity not in start.get('asset_owners',{}) or identity not in end.get('asset_owners',{}):raise ValueError('Volume/asset owner changed during the shutter')
        owners[identity]=dict(owner,matrix=start['asset_owners'][identity]['matrix'],matrix_close=end['asset_owners'][identity]['matrix'])
    scene.update(extra_geometry=extras,asset_owners=owners)
    frozen('Materials and environments',scene,start,end,('materials','environments'))
    scene.update(camera=camera,meshes=expanded,lights=lights,motion_steps=list(endpoints),warnings=warnings)
