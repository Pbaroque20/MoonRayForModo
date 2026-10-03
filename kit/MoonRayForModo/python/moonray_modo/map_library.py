"""Native texture/normal sockets from the matching upstream shader declarations."""
import json
from functools import lru_cache
from pathlib import Path

@lru_cache(maxsize=1)
def catalog():
    return json.loads(Path(__file__).with_name('map_catalog.json').read_text(encoding='utf-8'))

def literal(value,kind):
    from .rdla import string,number
    if kind.endswith('Vector'):return '{'+', '.join(literal(v,kind[:-6]) for v in value)+'}'
    if kind=='Bool':return 'true' if value else 'false'
    if kind=='String':return string(value)
    if kind=='SceneObject*':
        if value is not None:raise ValueError('Connect scene-object inputs using a graph socket')
        return 'undef()'
    constructors={'Rgb':'Rgb','Rgba':'Rgba','Vec2f':'Vec2','Vec3f':'Vec3','Vec4f':'Vec4',
        'Vec2d':'Vec2','Vec3d':'Vec3','Vec4d':'Vec4','Mat3f':'Mat3','Mat4f':'Mat4','Mat3d':'Mat3','Mat4d':'Mat4'}
    if kind in constructors:return constructors[kind]+'('+', '.join(number(v) for v in value)+')'
    return number(value)

def binding(ref,kind):
    units={'Rgb':'Rgb(1,1,1)','Rgba':'Rgba(1,1,1,1)','Vec2f':'Vec2(1,1)',
        'Vec3f':'Vec3(1,1,1)','Vec4f':'Vec4(1,1,1,1)'}
    return 'bind(%s, %s)'%(ref,units.get(kind,'1'))

def emit(kind,path,parameters,inputs,definition):
    from .textures import prepare,color_rule,register
    schema=catalog()[kind]['attributes'];attributes={}
    for key,value in parameters.items():
        if key in inputs:continue
        spec=schema[key]
        if spec['type']=='SceneObject*' and isinstance(value,dict) and 'item' in value:
            from .scene_references import emit as emit_reference
            attributes[key]=emit_reference(value,definition,path+'/reference/'+key)
            if key=='projector' and 'projection_mode' in schema:attributes['projection_mode']='0'
            continue
        # Native gamma controls perform color decoding. Prepare/mipmap without
        # an additional sRGB transform; normal maps always remain data textures.
        if spec['type']=='String' and 'FLAGS_FILENAME' in spec.get('flags','') and value:
            if Path(value).suffix.lower() not in ('.vdb',):
                transformed=bool(color_rule(value));value=prepare(value,False)
                if transformed and 'gamma' in schema:attributes['gamma']='0'
            else:register(value)
        attributes[key]=literal(value,spec['type'])
    if 'projection_mode' in schema and not any(k in parameters or k in inputs for k in ('projection_mode','projector')):
        attributes['projection_mode']='2'  # Identity TRS works without a host projector object.
    if any(color_rule(v) for k,v in parameters.items() if isinstance(v,str) and 'FLAGS_FILENAME' in schema[k].get('flags','')) and 'gamma' in schema:attributes['gamma']='0'
    for key,ref in inputs.items():
        attributes[key]=ref if schema[key]['type']=='SceneObject*' else binding(ref,schema[key]['type'])
    return definition(kind,path,attributes)
