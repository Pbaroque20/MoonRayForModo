"""Native material schemas, typed parameters and material-reference export."""
import json
import math
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def catalog():
    result=json.loads(Path(__file__).with_name('material_catalog.json').read_text(encoding='utf-8'))
    # Reflectance is bounded; emission and generic data/map colors remain HDR.
    for material in result.values():
        for name in ('metallic_color','metallic_edge_color'):
            spec=material['attributes'].get(name)
            if spec and spec['type']=='Rgb':spec.update(min=0,max=1)
        spec=material['attributes'].get('metallic')
        if spec and spec['type']=='Float':spec.update(min=0,max=1)
    return result


def compatible(shader, interface):
    return interface in ('','INTERFACE_GENERIC','INTERFACE_MATERIAL') or interface in [v.strip() for v in catalog()[shader]['interface'].split('|')]


def typed(value, attribute):
    kind=attribute['type']
    if kind=='SceneObject*':
        if value is None: return None
        if isinstance(value,dict) and set(value)=={'item'} and isinstance(value['item'],str) and attribute.get('interface') in ('INTERFACE_CAMERA','INTERFACE_NODE'):
            return value
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
    dimensions={'Rgb':3,'Rgba':4,'Vec2f':2,'Vec3f':3,'Vec4f':4,'Mat3f':9,'Mat4f':16,'Vec2d':2,'Vec3d':3,'Vec4d':4,'Mat3d':9,'Mat4d':16}
    if kind in dimensions:
        if not isinstance(value,list) or len(value)!=dimensions[kind]: raise ValueError('Expected %d components'%dimensions[kind])
        component={'type':'Float'}
        component.update({key:attribute[key] for key in ('min','max') if key in attribute})
        return [typed(v,component) for v in value]
    if kind not in ('Float','Double','Int','Long') or type(value) not in (float,int) or not math.isfinite(value):
        raise ValueError('Expected a finite '+kind)
    if kind in ('Int','Long') and int(value)!=value: raise ValueError('Expected an integer')
    for bound,compare in [('min',lambda a,b:a<b),('max',lambda a,b:a>b)]:
        if bound in attribute:
            try: limit=float(str(attribute[bound]).rstrip('f'))
            except ValueError: continue
            # A number past its limit is brought back to the limit rather than refused: nobody should meet an
            # error for dragging a slider too far.
            if compare(value,limit): value=int(limit) if kind in ('Int','Long') else limit
    if 'enum' in attribute and str(int(value)) not in {str(v) for v in attribute['enum'].values()}:
        raise ValueError('Unknown enumerated value')
    return int(value) if kind in ('Int','Long') else float(value)


def numbered(attributes, held):
    """Values kept under the unnumbered name of an attribute MoonRay numbers (material, ramp_color_multiplier), as the
    plugin once kept them, under MoonRay's own names: a material link as the first (material0), a number for each of
    the numbered ones, as it was meant for all of them."""
    import re
    result=dict(held)
    for key in [k for k in held if k not in attributes and k+'0' in attributes]:
        value=result.pop(key)
        names=[k for k in attributes if re.fullmatch(re.escape(key)+r'\d+',k)]
        if attributes[key+'0']['type']=='SceneObject*':names=[key+'0']
        for name in names:result.setdefault(name,value)
    return result


def validate(shader, parameters):
    if shader not in catalog(): raise ValueError('Unknown MoonRay material: '+str(shader))
    attributes=catalog()[shader]['attributes']
    if not isinstance(parameters,dict): raise ValueError('Material parameters must be an object')
    parameters=numbered(attributes,parameters)
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
    # Glitter turned off is left out, not written as false: a running MoonRay keeps asking for the rest positions glitter
    # in reference space asked for, and a material without them stays pink, until the setting is gone.
    if parameters.get('show_glitter') is False:parameters={key:value for key,value in parameters.items() if key!='show_glitter'}
    from .node_defaults import with_flakes
    parameters=with_flakes(shader,parameters)
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
    from .working_space import enabled as working_enabled,color as working_color
    if working_enabled():
        import re
        for key,spec in attributes.items():
            if key in authored or spec['type']!='Rgb' or key=='TMI':continue
            text=str(spec.get('default',''));match=re.fullmatch(r'(?:Rgb|Color)\(([^()]*)\)',text.strip())
            if not match:continue
            try:
                values=[float(v.strip().rstrip('f')) for v in match.group(1).split(',')]
                if len(values)==1:values*=3
                if len(values)==3:authored[key]=literal(values,spec)
            except ValueError:continue
        for key,spec in attributes.items():
            if spec['type']=='RgbVector' and key in parameters:authored[key]=literal([working_color(v) for v in parameters[key]],spec)
    from .working_space import surface as working_surface
    authored=working_surface(authored,name,lines,{key for key,spec in attributes.items() if spec['type']=='Rgb' and key!='TMI'})
    # A connected texture can exceed the authored field limits. Bound Fresnel
    # colors after working-space conversion, before they reach the material.
    for key in ('metallic','metallic_color','metallic_edge_color'):
        if key not in authored:continue
        if key=='metallic' and not authored[key].startswith('bind('):
            authored[key]='Rgb('+', '.join([authored[key]]*3)+')'
        low=name+'/limits/'+key+'/low';high=name+'/limits/'+key+'/high'
        lines.append('OpMap(%s) { ["operation"] = 4, ["op1"] = %s, ["op2"] = Rgb(0,0,0) }'%(string(low),authored[key]))
        lines.append('OpMap(%s) { ["operation"] = 5, ["op1"] = bind(OpMap(%s), Rgb(1,1,1)), ["op2"] = Rgb(1,1,1) }'%(string(high),string(low)))
        # MoonRay multiplies what a map gives by the attribute's own value, so that value must be 1: left at
        # its default, which for metallic is 0, the material is no metal at all whatever the map says.
        authored[key]='bind(OpMap(%s), %s)'%(string(high),'1' if key=='metallic' else 'Rgb(1,1,1)')
    lines.append('%s(%s) {'%(shader,string(name)))
    lines.extend('  [%s] = %s,'%(string(key),value) for key,value in authored.items())
    lines.append('}')
    return '%s(%s)'%(shader,string(name))


# Materials made of others, and the inputs they take them through. MoonRay crashes on some of them left without
# inputs: a layer without its B, a two-sided or hair layer material without either, and any of them with nothing
# plugged in at all where it is itself another's input. Measured with tools/soak_materials.py's runtime.
_CHOSEN=tuple('material%d'%i for i in range(64))
INPUTS={'DwaAdjustMaterial':('input_material',),'DwaColorCorrectMaterial':('input_material',),
        'HairColorCorrectMaterial':('input_hair_material',),'DwaLayerMaterial':('material_A','material_B'),
        'DwaTwoSidedMaterial':('front_material','back_material'),'HairLayerMaterial':('hair_material_A','hair_material_B'),
        'DwaMixMaterial':_CHOSEN,'DwaSwitchMaterial':_CHOSEN,'SwitchMaterial':_CHOSEN,
        'RaySwitchMaterial':('camera_ray_material','default_material','indirect_diffuse_ray_material',
                             'indirect_glossy_ray_material','indirect_mirror_ray_material')}
# The inputs MoonRay cannot do without, each with the one whose material it is given in its place.
NEEDED={'DwaLayerMaterial':{'material_B':'material_A'},
        'DwaTwoSidedMaterial':{'front_material':'back_material','back_material':'front_material'},
        'HairLayerMaterial':{'hair_material_A':'hair_material_B','hair_material_B':'hair_material_A'}}


def mend(materials, library, warnings, names=None):
    """Copies of a scene's materials and its library of native ones, with what would crash MoonRay mended and each
    change named in warnings: an input given a material with nothing plugged in is left empty, an input MoonRay
    cannot do without is given the material of its pair, and a material assigned with nothing plugged in is plain grey.
    names maps a library identity to the name shown for it."""
    names=names or {}
    held={}

    def label(identity):
        return names.get(identity) or str(identity)

    def hollow(identity, trail):
        material=library.get(identity)
        # A missing or cyclic reference is reported when the scene is written.
        if identity in trail or not material or not material.get('native_shader') or material.get('node_graph'):
            return False
        if identity not in held:
            held[identity]=empty(material['native_shader'],material.get('native_parameters',{}),(),trail+(identity,))
        return held[identity]

    def filled(value, trail):
        return isinstance(value,dict) and isinstance(value.get('material'),str) and not hollow(value['material'],trail)

    def empty(shader, parameters, wired, trail):
        slots=INPUTS.get(shader,())
        if shader not in catalog(): return False
        parameters=numbered(catalog()[shader]['attributes'],parameters)
        return bool(slots) and not any(slot in wired or filled(parameters.get(slot),trail) for slot in slots)

    def mended(shader, parameters, wired, owner):
        if shader not in INPUTS or shader not in catalog(): return parameters
        result=numbered(catalog()[shader]['attributes'],parameters)
        for slot in INPUTS[shader]:
            value=result.get(slot)
            if isinstance(value,dict) and isinstance(value.get('material'),str) and hollow(value['material'],()):
                result[slot]=None
                warnings.append('%s: %s has nothing plugged in, and MoonRay cannot render it as an input; %s is left empty.'
                                %(owner,label(value['material']),slot))
        for slot,other in NEEDED.get(shader,{}).items():
            if slot not in wired and result.get(slot) is None and result.get(other) is not None:
                result[slot]=result[other]
                warnings.append('%s: MoonRay cannot render a %s without %s; the material in %s is used for it.'%(owner,shader,slot,other))
        return result

    def surface(material, owner, assigned):
        if not material.get('native_shader'): return material
        material=dict(material)
        if material.get('node_graph'):
            graph=dict(material['node_graph']);graph['nodes']={k:dict(v) for k,v in graph.get('nodes',{}).items()}
            for node in graph['nodes'].values():
                if node.get('type') in INPUTS:
                    node['parameters']=mended(node['type'],node.get('parameters',{}),set(node.get('inputs',{})),owner)
                    node['inputs']=inputs=dict(node.get('inputs',{}))
                    for slot,other in NEEDED.get(node['type'],{}).items():
                        if slot not in inputs and node['parameters'].get(slot) is None and other in inputs:
                            inputs[slot]=inputs[other]
                            warnings.append('%s: MoonRay cannot render a %s without %s; the node wired to %s is used for it.'%(owner,node['type'],slot,other))
            material['node_graph']=graph
            return material
        shader=material['native_shader']
        material['native_parameters']=mended(shader,material.get('native_parameters',{}),(),owner)
        if assigned and empty(shader,material['native_parameters'],(),()):
            warnings.append('%s: its %s has nothing plugged in, which MoonRay cannot render; plain grey is used.'%(owner,shader))
            material.update(native_shader='DwaBaseMaterial',native_parameters={})
        return material

    mended_library={identity:surface(material,label(identity),False) for identity,material in library.items()}
    mended_materials={}
    for tag,material in materials.items():
        owner=tag or 'The base material'
        material=surface(material,owner,True)
        if material.get('material_stack'):
            material=dict(material,material_stack=[surface(child,owner,True) for child in material['material_stack']])
        mended_materials[tag]=material
    return mended_materials,mended_library
