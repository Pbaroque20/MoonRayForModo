"""Native material schemas, typed parameters and material-reference export."""
import json
import math
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def catalog():
    return json.loads(Path(__file__).with_name('material_catalog.json').read_text(encoding='utf-8'))


def compatible(shader, interface):
    return interface in ('','INTERFACE_GENERIC','INTERFACE_MATERIAL') or interface in [v.strip() for v in catalog()[shader]['interface'].split('|')]


def typed(value, attribute):
    kind=attribute['type']
    if kind=='SceneObject*':
        if value is None: return None
        if not isinstance(value,dict) or set(value)!={'material'} or not isinstance(value['material'],str):
            raise ValueError('Choose a material reference')
        return value
    if kind.endswith('Vector'):
        if not isinstance(value,list): raise ValueError('Expected a list')
        return [typed(v,dict(attribute,type=kind[:-6])) for v in value]
    if kind=='Bool':
        if type(value) is not bool: raise ValueError('Expected true or false')
        return value
    if kind=='String':
        if not isinstance(value,str): raise ValueError('Expected text')
        return value
    dimensions={'Rgb':3,'Rgba':4,'Vec2f':2,'Vec3f':3,'Vec4f':4,'Mat3f':9,'Mat4f':16}
    if kind in dimensions:
        if not isinstance(value,list) or len(value)!=dimensions[kind]: raise ValueError('Expected %d components'%dimensions[kind])
        return [typed(v,{'type':'Float'}) for v in value]
    if kind not in ('Float','Int') or type(value) not in (float,int) or not math.isfinite(value):
        raise ValueError('Expected a finite '+kind)
    if kind=='Int' and int(value)!=value: raise ValueError('Expected an integer')
    for bound,compare in [('min',lambda a,b:a<b),('max',lambda a,b:a>b)]:
        if bound in attribute:
            try: limit=float(str(attribute[bound]).rstrip('f'))
            except ValueError: continue
            if compare(value,limit): raise ValueError('Value violates '+bound+' '+str(limit))
    if 'enum' in attribute and str(int(value)) not in {str(v) for v in attribute['enum'].values()}:
        raise ValueError('Unknown enumerated value')
    return int(value) if kind=='Int' else float(value)


def validate(shader, parameters):
    if shader not in catalog(): raise ValueError('Unknown MoonRay material: '+str(shader))
    attributes=catalog()[shader]['attributes']
    if not isinstance(parameters,dict): raise ValueError('Material parameters must be an object')
    result={}
    for key,value in parameters.items():
        if key not in attributes: raise ValueError('Unknown '+shader+' parameter: '+key)
        result[key]=typed(value,attributes[key])
    return result


def references(material):
    values=list(material.get('native_parameters',{}).values())
    if material.get('node_graph'):
        from .nodes import validate
        for node in validate(material['node_graph'])['nodes'].values():
            values.extend(node.get('parameters',{}).values())
    for value in values:
        if isinstance(value,dict) and 'material' in value: yield value['material']


def attach_dependencies(materials, library):
    def walk(material, trail):
        result=[]
        for identity in references(material):
            if identity in trail: raise ValueError('Cyclic MoonRay material references')
            if identity not in library: raise ValueError('Missing referenced MoonRay material: '+identity)
            dependency=library[identity]
            result.append(dependency)
            result.extend(walk(dependency,trail+(identity,)))
        return result
    for material in materials.values():
        for child in material.get('material_stack',[material]):
            child['native_dependencies']=walk(child,())
            if not child.get('uv_map'):
                child['uv_map']=next((d['uv_map'] for d in child['native_dependencies'] if d.get('uv_map')),'')


def emit(material, name, index, lines, library, trail=(), authored_bindings=None):
    from .rdla import string,number
    from .graph import bindings
    shader=material['native_shader']
    parameters=validate(shader,material.get('native_parameters',{}))
    attributes=catalog()[shader]['attributes']
    def literal(value, spec):
        kind=spec['type']
        if kind=='SceneObject*':
            if value is None: return 'undef()'
            identity=value['material']
            if identity in trail: raise ValueError('Cyclic MoonRay material references')
            if identity not in library: raise ValueError('Missing referenced MoonRay material: '+identity)
            child=library[identity]
            if not child.get('native_shader'): raise ValueError('Referenced input must use a native MoonRay material')
            if not compatible(child['native_shader'],spec.get('interface','')):
                raise ValueError('Incompatible material input for '+shader+'.'+spec['name'])
            return emit(child,name+'/input/'+spec['name'],index,lines,library,trail+(identity,))
        if kind.endswith('Vector'):
            return '{'+', '.join(literal(v,dict(spec,type=kind[:-6])) for v in value)+'}'
        if kind=='Bool': return 'true' if value else 'false'
        if kind=='String': return string(value)
        constructors={'Rgb':'Rgb','Rgba':'Rgba','Vec2f':'Vec2','Vec3f':'Vec3','Vec4f':'Vec4','Mat3f':'Mat3','Mat4f':'Mat4'}
        if kind in constructors: return constructors[kind]+'('+', '.join(number(v) for v in value)+')'
        return number(value)
    authored={key:literal(value,attributes[key]) for key,value in parameters.items() if value is not None}
    # Common Modo channel layers remain available on native surface shaders.
    mapped=bindings(material,index[0],lines);index[0]+=1
    names={'diffuseColor':'albedo','specularColor':'metallic_color','emissiveColor':'emission',
           'transmissionColor':'transmission_color','refractionRoughness':'independent_transmission_roughness',
           'clearcoatRoughness':'clearcoat_roughness','subsurfaceColor':'scattering_color',
           'ior':'refractive_index','specularAmount':'specular'}
    for key,value in mapped.items():
        if key=='layerMask': continue
        if key=='normal' and 'input_normal' in attributes:
            normal=name+'/normal'
            lines.append('ModoNormalMap(%s) { ["input"] = %s }'%(string(normal),value))
            authored['input_normal']='ModoNormalMap(%s)'%string(normal)
            continue
        target=key if key in attributes else names.get(key,key)
        if key=='diffuseColor' and target not in attributes and 'metallic_color' in attributes:
            target='metallic_color'
        if target not in attributes:
            raise ValueError(shader+' cannot accept the mapped '+key+' effect; put this texture on a compatible input material')
        authored[target]=value
    authored.update(authored_bindings or {})
    lines.append('%s(%s) {'%(shader,string(name)))
    lines.extend('  [%s] = %s,'%(string(key),value) for key,value in authored.items())
    lines.append('}')
    return '%s(%s)'%(shader,string(name))
