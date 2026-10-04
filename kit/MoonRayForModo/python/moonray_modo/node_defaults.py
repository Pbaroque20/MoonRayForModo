"""Typed defaults from the bundled MoonRay declarations; never evaluate C++ text."""
import copy
import json
import re

DIMENSIONS={'Rgb':3,'Rgba':4,'Vec2f':2,'Vec3f':3,'Vec4f':4,
            'Vec2d':2,'Vec3d':3,'Vec4d':4,'Mat3f':9,'Mat3d':9,'Mat4f':16,'Mat4d':16}
NUMBER=re.compile(r'[-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?[fF]?\Z')


def split(text):
    result=[];start=0;depth=0;quoted=False;escape=False
    for i,char in enumerate(text):
        if quoted:
            if escape:escape=False
            elif char=='\\':escape=True
            elif char=='"':quoted=False
        elif char=='"':quoted=True
        elif char in '({[':depth+=1
        elif char in ')}]':depth-=1
        elif char==',' and depth==0:result.append(text[start:i].strip());start=i+1
    if text[start:].strip():result.append(text[start:].strip())
    return result


def value(spec):
    if 'default_value' in spec:return copy.deepcopy(spec['default_value'])
    kind=spec['type'];kind='Float' if kind=='float' else kind
    raw=str(spec.get('default','')).strip()
    if kind.startswith('SceneObject'):return [] if kind.endswith('Vector') else None
    if kind.endswith('Vector'):
        if not raw:return []
        if not (raw.startswith('{') and raw.endswith('}')):raise ValueError('Unsupported array default: '+raw)
        return [value({'type':kind[:-6],'default':part}) for part in split(raw[1:-1])]
    if kind=='String':return json.loads(raw) if raw else ''
    if kind=='Bool':
        if raw not in ('','true','false'):raise ValueError('Unsupported boolean default: '+raw)
        return raw=='true'
    if kind in DIMENSIONS:
        count=DIMENSIONS[kind]
        body=raw[raw.find('(')+1:-1] if '(' in raw and raw.endswith(')') else raw
        values=[value({'type':'Float','default':part}) for part in split(body)]
        if len(values)==1:
            values=[values[0] if i%(int(count**.5)+1)==0 else 0.0 for i in range(count)] if kind.startswith('Mat') else values*count
        if len(values)!=count:raise ValueError('Invalid '+kind+' default: '+raw)
        return values
    if kind in ('Float','Double','Int','Long'):
        if not raw:return 0 if kind in ('Int','Long') else 0.0
        if not NUMBER.fullmatch(raw):raise ValueError('Unsupported numeric default: '+raw)
        number=float(raw.rstrip('fF'))
        if kind in ('Int','Long'):
            if number!=int(number):raise ValueError('Non-integer default')
            return int(number)
        return number
    raise ValueError('Unsupported default type: '+kind)


def parameters(kind):
    from . import nodes,shader_library
    result={}
    for key,spec in nodes.specs(kind).items():
        # Connections remain explicitly unconnected, not authored null references.
        if spec['type'].startswith('SceneObject'):continue
        result[key]=shader_library.typed(value(spec),spec)
    # Keep the plugin's projector-free preview default for native projection maps.
    if 'projection_mode' in result and 'projector' in nodes.specs(kind):result['projection_mode']=2
    return result
