"""Non-destructive per-object normals and bounded subdivision density estimate."""
import math
from . import options

def unit(v):
    length=math.sqrt(sum(x*x for x in v))
    return [x/length for x in v] if length>1e-20 else [0.,0.,0.]

def topology(vertices,faces):
    weighted=[];edges={}
    for fi,face in enumerate(faces):
        n=[0.,0.,0.]
        for a,b in zip(face,face[1:]+face[:1]):
            p,q=vertices[a],vertices[b]
            n[0]+=(p[1]-q[1])*(p[2]+q[2])
            n[1]+=(p[2]-q[2])*(p[0]+q[0])
            n[2]+=(p[0]-q[0])*(p[1]+q[1])
            edges.setdefault(tuple(sorted((a,b))),[]).append(fi)
        weighted.append(n)
    return weighted,[unit(n) for n in weighted],edges

def prepare(mesh):
    settings=options.object_values(mesh.get('geometry_settings',{}))
    if not settings['override']: return mesh
    result=dict(mesh);result['smooth']=settings['smooth']
    smooth=settings['normal_override'] and settings['smooth'] and not mesh.get('subdivision')
    angular=settings['angular_tessellation'] and mesh.get('subdivision') and not mesh.get('evaluated_geometry')
    if mesh.get('subdivision') and not mesh.get('evaluated_geometry'):
        result['adaptive_error']=(settings['adaptive_error'] or 2.0) if settings['dynamic_tessellation'] else settings['adaptive_error']
        if 'instances' in mesh: result['adaptive_error']=0.0
    if not (smooth or angular): return result
    faces=[list(f) for f in mesh['faces']]
    weighted,normals,edges=topology(mesh['vertices'],faces)
    adjacency={};bend=0.;threshold=math.cos(math.radians(settings['smoothing_angle']))
    for (a,b),neighbours in edges.items():
        # Boundary/nonmanifold edges are always sharp.
        if len(neighbours)!=2: continue
        i,j=neighbours
        dot=max(-1.,min(1.,sum(x*y for x,y in zip(normals[i],normals[j]))))
        bend=max(bend,math.degrees(math.acos(dot)))
        if dot>=threshold-1e-10:
            for vertex in (a,b):
                adjacency.setdefault((vertex,i),[]).append(j)
                adjacency.setdefault((vertex,j),[]).append(i)
    if angular:
        # Control-cage bending predicts density, not limit-surface convergence.
        estimate=max(1,math.ceil(bend/settings['tessellation_angle']))
        result['mesh_resolution']=min(2**settings['level'],estimate)
    if smooth:
        cache={};corners=[]
        for fi,face in enumerate(faces):
            for vertex in face:
                key=(vertex,fi)
                if key not in cache:
                    connected={fi};pending=[fi]
                    while pending:
                        for other in adjacency.get((vertex,pending.pop()),[]):
                            if other not in connected: connected.add(other);pending.append(other)
                    normal=unit([sum(weighted[f][axis] for f in connected) for axis in range(3)])
                    for f in connected: cache[(vertex,f)]=normal
                corners.append(cache[key])
        result['normals']=corners
    return result


def render_meshes(meshes, expand_instances=False):
    """Expand only explicit opt-outs and camera-adaptive subdivision instances."""
    for mesh in meshes:
        settings=options.object_values(mesh.get('geometry_settings',{}))
        dynamic=settings['override'] and settings['dynamic_tessellation'] and mesh.get('subdivision') and not mesh.get('evaluated_geometry')
        affected=bool(set(map(str,mesh.get('instance_ids',[]))) & expand_instances) if isinstance(expand_instances,set) else expand_instances
        split=affected or (settings['override'] and (not settings['share_instances'] or dynamic))
        if split and 'instances' in mesh:
            transforms=mesh['instances'];ids=mesh.get('instance_ids',list(range(len(transforms))))
            if len(ids)!=len(transforms): raise ValueError('Instance IDs must match transform count')
            for identity,transform in zip(ids,transforms):
                value=dict(mesh,source_item=str(identity),matrix=transform,name=mesh['name']+' / '+str(identity),identity=str(mesh.get('identity',mesh['name']))+'|'+str(identity))
                value.pop('instances');value.pop('instance_ids',None)
                yield prepare(value)
        else:
            yield prepare(mesh)
