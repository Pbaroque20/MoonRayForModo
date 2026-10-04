"""Recover exact affine UV derivatives from supported coordinate graph operations."""
import math
from . import coordinates

def descriptor(identity,graph):
    cache={};visiting=set()
    def constant(value):
        values=value if isinstance(value,list) else [value]*3
        return None,[[0,0,float(v)] for v in (values+[0]*3)[:3]]
    def visit(key):
        if key in cache:return cache[key]
        if key in visiting:raise ValueError('Coordinate graph cycle')
        visiting.add(key)
        node=graph['nodes'][key];kind=node['type'];p=node.get('parameters',{});links=node.get('inputs',{})
        def arg(name,default):return visit(links[name]) if name in links else constant(p.get(name,default))
        def scalar(v):
            if v[0] is not None or any(row[:2]!=[0,0] for row in v[1]):raise ValueError('Varying affine control')
            return v[1][0][2]
        def combine(a,b,operation):
            if a[0] is not None and b[0] is not None and a[0]!=b[0]:raise ValueError('Multiple UV sets in one coordinate expression')
            rows=[]
            for x,y in zip(a[1],b[1]):
                if operation in ('add','subtract'):
                    sign=1 if operation=='add' else -1;rows.append([u+sign*v for u,v in zip(x,y)])
                elif operation=='multiply':
                    if x[:2]==[0,0]:rows.append([v*x[2] for v in y])
                    elif y[:2]==[0,0]:rows.append([v*y[2] for v in x])
                    else:raise ValueError('Nonlinear UV multiplication')
                elif operation=='divide':
                    if y[:2]!=[0,0] or abs(y[2])<1e-12:raise ValueError('Varying or zero UV divisor')
                    rows.append([v/y[2] for v in x])
            return a[0] if a[0] is not None else b[0],rows
        if kind=='texcoord':
            uv=p.get('uv_map') or '@index:'+str(p.get('index',0))
            result=uv,[[1,0,0],[0,1,0],[0,0,0]]
        elif kind=='constant':result=constant(p.get('value',[.5]*3))
        elif kind in ('add','subtract','multiply','divide'):
            default=1 if kind in ('multiply','divide') else 0
            result=combine(arg('in1',default),arg('in2',default),kind)
        elif kind=='convert':result=arg('in',0)
        elif kind=='rotate2d':
            basis,rows=arg('in',0);angle=math.radians(scalar(arg('amount',0)));co,si=math.cos(angle),math.sin(angle)
            result=basis,[[co*x-si*y for x,y in zip(rows[0],rows[1])],
                          [si*x+co*y for x,y in zip(rows[0],rows[1])],[0,0,0]]
        elif kind=='swizzle':
            basis,rows=arg('in',0);channels=p.get('channels','rgb')
            if len(channels)==1:channels*=3
            if len(channels)==2:channels+='0'
            result=basis,[[0,0,float(c)] if c in '01' else rows['rgbxyz'.index(c)%3] for c in channels]
        elif kind=='combine':
            args=[arg(name,0) for name in ('in1','in2','in3')];bases={v[0] for v in args if v[0] is not None}
            if len(bases)>1:raise ValueError('Mixed UV coordinate bases')
            result=next(iter(bases),None),[v[1][0] for v in args]
        else:raise ValueError('Non-affine coordinate operation: '+kind)
        visiting.remove(key);cache[key]=result;return result
    try:
        basis,rows=visit(identity)
        if basis is None:return None
        layer={'projection':'uv','uv_map':basis,'uv_matrix':rows[0]+rows[1]}
        coordinates.affine(layer) # Reject degenerate tangent frames.
        layer['coordinate_key']=coordinates.key(layer)
        return layer
    except (ValueError,KeyError,TypeError,IndexError):return None
