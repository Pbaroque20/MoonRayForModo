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


# What the plugin starts a material with where that is not MoonRay's own default. MoonRay's toon material comes
# with its toon look switched off (an ordinary diffuse and highlight); here it starts as a toon material: its
# diffuse model the ramp, its specular model Toon. Its diffuse ramp is read from the side facing the light (0) to
# where the surface turns away (1), and MoonRay's own runs from black to white, so that a surface was darkest facing
# the light; it starts the other way round, brightest facing the light, as Modo's toon is (issue 127).
STARTS={'DwaToonMaterial':{'diffuse_model':1,'specular_model':2,
                           'colors':[[1.0,1.0,1.0],[0.75,0.75,0.75],[0.25,0.25,0.25],[0.0,0.0,0.0]]}}
# Glitter starts in object space (4), not MoonRay's reference space (5): reference space places the flakes by each
# point's rest position (the ref_P primitive attribute, so that they stay put on a deforming surface), which Modo's
# meshes do not carry, and without it MoonRay renders the whole surface black.
GLITTER_SPACE_OBJECT=4
for _shader in ('DwaBaseMaterial','DwaFabricMaterial','DwaMetalMaterial','DwaSkinMaterial','DwaSolidDielectricMaterial',
                'DwaToonMaterial','DwaVelvetMaterial_v2'):
    STARTS.setdefault(_shader,{})['glitter_space']=GLITTER_SPACE_OBJECT


def keep_moonray_defaults(graph):
    """A graph from a MoonRay scene, its nodes given MoonRay's own default wherever the scene left one the plugin
    starts otherwise: the material is the scene's, not a new one, and renders as the scene had it."""
    from . import nodes
    for node in (graph or {}).get('nodes', {}).values():
        held = STARTS.get(node.get('type'))
        if not held:continue
        parameters = node.setdefault('parameters', {})
        specs = nodes.specs(node['type'])
        for key in held:
            if key not in parameters and key in specs:parameters[key] = value(specs[key])
    return graph


def start(shader,key,spec):
    """What a setting of a shader is before it has been set: the plugin's own start, else MoonRay's default."""
    held=STARTS.get(shader,{})
    return copy.deepcopy(held[key]) if key in held else value(spec)


def started(shader,parameters):
    """A material's settings with the plugin's starts filled in where nothing has been set."""
    held=STARTS.get(shader)
    if not held:return parameters
    return dict(held,**(parameters or {}))


def parameters(kind):
    from . import nodes,shader_library
    result={}
    for key,spec in nodes.specs(kind).items():
        # Connections remain explicitly unconnected, not authored null references.
        if spec['type'].startswith('SceneObject'):continue
        result[key]=shader_library.typed(value(spec),spec)
    # Keep the plugin's projector-free preview default for native projection maps.
    if 'projection_mode' in result and 'projector' in nodes.specs(kind):result['projection_mode']=2
    result.update(STARTS.get(kind,{}))
    return result
