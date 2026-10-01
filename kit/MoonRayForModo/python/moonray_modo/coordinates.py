"""Deterministic per-layer UV coordinates, including baked locator projections."""
import hashlib
import json
import math


def key(layer):
    fields = {name: layer.get(name) for name in
              ('uv_map', 'projection', 'locator_matrix', 'axis', 'uv_matrix', 'rotation', 'scale')}
    return 'modo_uv_' + hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()[:24]


def descriptors(materials):
    result = {}
    for material in materials.values():
        for child in material.get('material_stack', [material]):
            for layer in child.get('layers', []):
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
        points = [transform(transform(p, world_matrix), inv) for p in positions]
        axis = layer.get('axis', 'z')
        points = [(p[1],p[2],p[0]) if axis in ('x',0) else
                  (p[0],p[2],p[1]) if axis in ('y',1) else p for p in points]
        values = []
        for x,y,z in points:
            if projection == 'planar':
                value = (x+.5, y+.5)
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
    a,b,c,d,e,f = layer.get('uv_matrix', [1,0,0,0,1,0])
    rotation = layer.get('rotation', 0)
    cosine, sine = math.cos(rotation), math.sin(rotation)
    sx,sy = layer.get('scale', [1,1])
    result = []
    for u,v in values:
        x,y = a*u+b*v+c-.5, d*u+e*v+f-.5
        result.append([(x*cosine-y*sine+.5)*sx, (x*sine+y*cosine+.5)*sy])
    return result
