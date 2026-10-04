"""Editable approximations of MoonShine analytic geometry; never execute RDLA."""
import math

KINDS = ('SphereGeometry', 'BoxGeometry')

def mesh_record(record, segments=64, rings=32):
    a = dict(record.get('attributes', {}))
    vertices, faces, uv = [], [], []
    if record['type'] == 'BoxGeometry':
        size = a.get('size', [1, 1, 1])
        if len(size) != 3 or any(not math.isfinite(v) or v <= 0 for v in size):
            raise ValueError('Box dimensions must be finite and positive')
        vertices = [[x*size[0]/2, y*size[1]/2, z*size[2]/2]
                    for x,y,z in [(-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),
                                  (-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)]]
        faces = [[0,3,2,1],[4,5,6,7],[0,1,5,4],[3,7,6,2],[0,4,7,3],[1,2,6,5]]
        # Keep UVs absent until the native box face chart can be reproduced.
    elif record['type'] == 'SphereGeometry':
        r = float(a.get('radius', 1))
        lo, hi, phi = (float(a.get(k,d)) for k,d in [('zmin',-1),('zmax',1),('phi_max',360)])
        if not all(math.isfinite(v) for v in (r,lo,hi,phi)) or r <= 0:
            raise ValueError('Invalid sphere dimensions')
        lo, hi, phi = max(-r,min(r,lo)), max(-r,min(r,hi)), max(0,min(360,phi))
        if lo >= hi or phi <= 0:raise ValueError('Sphere clipping removes the entire surface')
        t0,t1 = math.acos(lo/r),math.acos(hi/r)
        rows=[]
        closed=phi==360
        for row in range(rings+1):
            t=t0+(t1-t0)*row/rings
            z=r*math.cos(t);rad=r*math.sin(t)
            if abs(rad)<r*1e-12:
                rows.append([len(vertices)]*(segments+1));vertices.append([0,0,z]);continue
            ids=[]
            for col in range(segments+(not closed)):
                angle=math.radians(phi)*col/segments
                ids.append(len(vertices));vertices.append([rad*math.cos(angle),rad*math.sin(angle),z])
            if closed:ids.append(ids[0])
            rows.append(ids)
        for row in range(rings):
            for col in range(segments):
                corners=[(rows[row][col],col,row),(rows[row][col+1],col+1,row),
                         (rows[row+1][col+1],col+1,row+1),(rows[row+1][col],col,row+1)]
                unique=[]
                for entry in corners:
                    if entry[0] not in [v[0] for v in unique]:unique.append(entry)
                if len(unique)<3:continue
                faces.append([v[0] for v in unique])
                uv.extend([[c/segments,j/rings] for _,c,j in unique])
    else:raise ValueError('Unsupported analytic primitive: '+record['type'])
    if a.get('reverse_normals',False):
        faces=[list(reversed(face)) for face in faces]
        if uv:
            offset=0;flipped=[]
            for face in faces:
                flipped.extend(reversed(uv[offset:offset+len(face)]));offset+=len(face)
            uv=flipped
    a.update(vertex_list_0=vertices,face_vertex_count=[len(f) for f in faces],
             vertices_by_index=[i for f in faces for i in f],uv_list=uv,is_subd=False)
    return dict(record, type='RdlMeshGeometry', attributes=a)
