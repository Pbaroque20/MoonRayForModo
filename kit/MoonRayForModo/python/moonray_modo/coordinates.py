"""Deterministic per-layer UV coordinates, including baked locator projections."""
import hashlib
import json
import math
from . import rows


def key(layer):
    fields = {name: layer.get(name) for name in
              ('uv_map', 'projection', 'locator_matrix', 'axis', 'uv_matrix', 'rotation', 'scale')}
    if layer.get('object_space'):
        # Laid out in each mesh's own space rather than the world's.
        fields['object_space'] = True
    return 'modo_uv_' + hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()[:24]


def descriptors(materials):
    result = {}
    for material in materials.values():
        for child in material.get('material_stack', [material]):
            for source in [child] + child.get('native_dependencies', []):
                graph_layers=[]
                if source.get('node_graph'):
                    from . import nodes   # nodes imports this module: imported here, once it is loaded
                    graph_layers=nodes.descriptors(source['node_graph'])
                for layer in source.get('layers', [])+graph_layers:
                    if layer.get('coordinate_key'):
                        result[layer['coordinate_key']] = layer
    return result


def transform(point, matrix):
    return [sum(point[j] * matrix[j*4+i] for j in range(3)) + matrix[12+i] for i in range(3)]


def inverse(matrix):
    rows = [[float(matrix[r*4+c]) for c in range(4)] + [float(r == c) for c in range(4)] for r in range(4)]
    for col in range(4):
        pivot = max(range(col, 4), key=lambda r: abs(rows[r][col]))
        if abs(rows[pivot][col]) < 1e-12:
            raise ValueError('Texture locator has a singular transform')
        rows[col], rows[pivot] = rows[pivot], rows[col]
        divisor = rows[col][col]
        rows[col] = [x/divisor for x in rows[col]]
        for r in range(4):
            if r != col:
                factor = rows[r][col]
                rows[r] = [a-factor*b for a,b in zip(rows[r], rows[col])]
    return [v for row in rows for v in row[4:]]


def face(layer, positions, uv, world_matrix):
    projection = layer.get('projection', 'uv')
    if projection == 'uv':
        if len(uv) != len(positions):
            raise ValueError('Missing UV values for ' + layer.get('uv_map', ''))
        values = uv
    else:
        inv = inverse(layer['locator_matrix'])
        if layer.get('object_space'):
            # The mesh's own space: where it stands in the world does not come into it.
            points = [transform(p, inv) for p in positions]
        else:
            points = [transform(transform(p, world_matrix), inv) for p in positions]
        axis = layer.get('axis', 'z')
        points = [(p[1],p[2],p[0]) if axis in ('x',0) else
                  (p[0],p[2],p[1]) if axis in ('y',1) else p for p in points]
        dominant = None
        if projection == 'cubic':
            if len(points)<3:
                raise ValueError('Cubic projection requires a polygon')
            normal=[0.,0.,0.]
            for p,q in zip(points,points[1:]+points[:1]):
                normal[0]+=(p[1]-q[1])*(p[2]+q[2])
                normal[1]+=(p[2]-q[2])*(p[0]+q[0])
                normal[2]+=(p[0]-q[0])*(p[1]+q[1])
            dominant=max(range(3),key=lambda i:abs(normal[i]))
            if abs(normal[dominant])<1e-12:
                raise ValueError('Cubic projection cannot map a degenerate polygon')
            sign=1 if normal[dominant]>=0 else -1
        values = []
        for x,y,z in points:
            if projection == 'planar':
                value = (x+.5, y+.5)
            elif projection == 'cubic':
                if dominant==0: value=(-sign*z+.5,y+.5)
                elif dominant==1: value=(x+.5,-sign*z+.5)
                else: value=(sign*x+.5,y+.5)
            elif projection == 'cylindrical':
                value = (.5+math.atan2(x,z)/(2*math.pi), y+.5)
            elif projection == 'spherical':
                length = max(1e-12, math.sqrt(x*x+y*y+z*z))
                value = (.5+math.atan2(x,z)/(2*math.pi), .5+math.asin(max(-1,min(1,y/length)))/math.pi)
            else:
                raise ValueError('Unsupported texture projection: ' + projection)
            values.append(value)
        if projection in ('spherical','cylindrical') and max(v[0] for v in values)-min(v[0] for v in values) > .5:
            values = [(u+1 if u < .5 else u,v) for u,v in values]
    return transform_uv(layer,values)


def transform_uv(layer, values):
    a,b,c,d,e,f = layer.get('uv_matrix', [1,0,0,0,1,0])
    rotation = layer.get('rotation', 0)
    cosine, sine = math.cos(rotation), math.sin(rotation)
    sx,sy = layer.get('scale', [1,1])
    # UVs as Modo handed them over, all at once by the geometry adapter: the same arithmetic.
    moved = rows.uv_transform(values, (a, b, c, d, e, f, cosine, sine, sx, sy))
    if moved is not None:
        return moved
    return [[((x := a*u+b*v+c)*cosine-(y := d*u+e*v+f)*sine)*sx, (x*sine+y*cosine)*sy] for u,v in values]


def mesh_corners(layer, vertices, faces, uv, world_matrix):
    """Bake independently per polygon, keeping seam correction local to a face."""
    count = rows.corner_count(faces)
    if layer.get('projection','uv') == 'uv' and len(uv) != count:
        raise ValueError('Named UV count does not match mesh corners')
    if layer.get('projection','uv') == 'uv':
        # Each corner's own UV, moved as face() moves it: the same numbers, without a step for each polygon. Where
        # the layer moves them not at all, the very list, by which what was worked out from it (and written of it) is
        # kept.
        if list(layer.get('uv_matrix', [1,0,0,0,1,0])) == [1,0,0,0,1,0] and not layer.get('rotation', 0) and list(layer.get('scale', [1,1])) == [1,1]:
            return uv
        return transform_uv(layer, uv)
    # As face() for each polygon, with the locator's inverse found once and each point put into the locator's space
    # once, not at every corner: the same numbers, in a small part of the time (a 324,706-face mesh took 53 s).
    projection = layer['projection']
    if projection not in ('planar','cubic','cylindrical','spherical'):
        raise ValueError('Unsupported texture projection: ' + projection)
    inv = inverse(layer['locator_matrix'])
    axis = layer.get('axis', 'z')
    def placed(p):
        p = transform(p, inv) if layer.get('object_space') else transform(transform(p, world_matrix), inv)
        return (p[1],p[2],p[0]) if axis in ('x',0) else (p[0],p[2],p[1]) if axis in ('y',1) else p
    points = [placed(p) for p in vertices]
    atan2, asin, sqrt, tau, pi = math.atan2, math.asin, math.sqrt, 2*math.pi, math.pi
    values = []
    for polygon in faces:
        if not polygon:
            continue
        corners = [points[i] for i in polygon]
        if projection == 'planar':
            values.extend((x+.5, y+.5) for x,y,z in corners)
            continue
        if projection == 'cubic':
            if len(corners)<3:
                raise ValueError('Cubic projection requires a polygon')
            normal=[0.,0.,0.]
            for p,q in zip(corners,corners[1:]+corners[:1]):
                normal[0]+=(p[1]-q[1])*(p[2]+q[2])
                normal[1]+=(p[2]-q[2])*(p[0]+q[0])
                normal[2]+=(p[0]-q[0])*(p[1]+q[1])
            dominant=max(range(3),key=lambda i:abs(normal[i]))
            if abs(normal[dominant])<1e-12:
                raise ValueError('Cubic projection cannot map a degenerate polygon')
            sign=1 if normal[dominant]>=0 else -1
            if dominant==0: values.extend((-sign*z+.5,y+.5) for x,y,z in corners)
            elif dominant==1: values.extend((x+.5,-sign*z+.5) for x,y,z in corners)
            else: values.extend((sign*x+.5,y+.5) for x,y,z in corners)
            continue
        if projection == 'cylindrical':
            own = [(.5+atan2(x,z)/tau, y+.5) for x,y,z in corners]
        else:
            own = [(.5+atan2(x,z)/tau, .5+asin(max(-1,min(1,y/max(1e-12, sqrt(x*x+y*y+z*z)))))/pi) for x,y,z in corners]
        if max(v[0] for v in own)-min(v[0] for v in own) > .5:
            own = [(u+1 if u < .5 else u,v) for u,v in own]
        values.extend(own)
    return transform_uv(layer, values)


def affine(layer):
    a,b,c,d,e,f=layer.get('uv_matrix',[1,0,0,0,1,0])
    angle=layer.get('rotation',0);co,si=math.cos(angle),math.sin(angle)
    sx,sy=layer.get('scale',[1,1])
    matrix=[sx*(co*a-si*d),sx*(co*b-si*e),sy*(si*a+co*d),sy*(si*b+co*e)]
    offset=[sx*(co*c-si*f),sy*(si*c+co*f)]
    if any(not math.isfinite(v) for v in matrix+offset):raise ValueError('UV transform must be finite')
    if abs(matrix[0]*matrix[3]-matrix[1]*matrix[2])<1e-12:raise ValueError('Normal/bump UV transform is singular')
    return matrix,offset


def fallback_uvs(faces):
    """A nondegenerate local surface basis for locator-projected meshes without UVs."""
    result=[]
    for face in faces:
        n=len(face)
        if n==3:result.extend([[0,0],[1,0],[0,1]])
        elif n==4:result.extend([[0,0],[1,0],[1,1],[0,1]])
        else:result.extend([[.5+.5*math.cos(2*math.pi*i/n),.5+.5*math.sin(2*math.pi*i/n)] for i in range(n)])
    return result
