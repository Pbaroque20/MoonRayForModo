"""Explicit MaterialX subset translation; no external code or shader execution."""
import copy
from pathlib import Path
import xml.etree.ElementTree as ET
from . import nodes,shader_library,map_library

STANDARD={'base_color':'albedo','metalness':'metallic','diffuse_roughness':'diffuse_roughness',
          'specular':'specular','specular_roughness':'roughness','specular_IOR':'refractive_index',
          'specular_anisotropy':'anisotropy','transmission':'transmission','transmission_color':'transmission_color',
          'coat':'clearcoat','coat_roughness':'clearcoat_roughness','coat_IOR':'clearcoat_refractive_index',
          'emission_color':'emission','normal':'input_normal','thin_walled':'thin_geometry'}
TYPES={'float':'Float','integer':'Int','boolean':'Bool','color3':'Rgb','vector2':'Vec2f','vector3':'Vec3f','filename':'String','string':'String'}


def parse_value(element):
    kind=element.get('type');text=element.get('value','')
    if kind in ('string','filename'): return text
    if kind=='boolean':
        if text not in ('true','false','0','1'): raise ValueError('Invalid MaterialX boolean')
        return text in ('true','1')
    if kind=='integer': return int(text)
    if kind=='float': return float(text)
    if kind in ('color3','vector2','vector3'): return [float(v.strip()) for v in text.split(',')]
    raise ValueError('Unsupported MaterialX value type: '+str(kind))


def read(path, material_name=None):
    path=Path(path).resolve();raw=path.read_bytes()
    if len(raw)>4*1024*1024: raise ValueError('MaterialX file exceeds 4 MiB')
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper(): raise ValueError('MaterialX document entities are not supported')
    document=ET.fromstring(raw)
    if document.tag!='materialx': raise ValueError('Expected a MaterialX document')
    from .materialx_expand import expand
    document=expand(document)
    definitions={e.get('name'):e for e in document.findall('nodedef')}
    elements={};graphs={}
    for element in document:
        if element.tag=='nodegraph':
            prefix=element.get('name','');graphs[prefix]=element
            for child in element:
                if child.get('name'): elements[prefix+'/'+child.get('name')]=child
        elif element.get('name'): elements[element.get('name')]=element
    materials=[e for e in document if e.tag=='surfacematerial']
    if material_name:
        materials=[e for e in materials if e.get('name')==material_name]
    if len(materials)!=1: raise ValueError('Choose a document with exactly one surface material (or specify its name)')
    graph={'version':1,'nodes':{},'overrides':[],'materialx_source':str(path),'materialx_version':document.get('version','')}
    visiting=set();cache={}
    def interface(port,scope,trail=()):
        name=port.get('interfacename')
        if not name:return port
        if name in trail:raise ValueError('MaterialX interface cycle')
        group=graphs.get(scope)
        source=next((p for p in group.findall('input') if p.get('name')==name),None) if group is not None else None
        if source is None:raise ValueError('Missing MaterialX interface input '+name)
        value=copy.deepcopy(interface(source,scope,trail+(name,)));value.set('name',port.get('name',''));return value
    def resolve(port,scope,trail=()):
        port=interface(port,scope)
        if port.get('channels'):raise ValueError('MaterialX channel swizzles require explicit channel nodes')
        if port.get('nodegraph'):
            signature=(port.get('nodegraph'),port.get('output'))
            if signature in trail or len(trail)>100:raise ValueError('MaterialX graph output cycle')
            name=port.get('nodegraph');group=graphs.get(name)
            if group is None: raise ValueError('Missing MaterialX nodegraph '+name)
            outputs=group.findall('output')
            output=outputs[0] if len(outputs)==1 and not port.get('output') else next((child for child in outputs if child.get('name')==port.get('output','out')),None)
            if output is None: raise ValueError('Missing MaterialX graph output')
            return resolve(output,name,trail+(signature,))
        name=port.get('nodename')
        if not name: raise ValueError('Expected a MaterialX node connection')
        key=scope+'/'+name if scope and scope+'/'+name in elements else name
        if key not in elements: raise ValueError('Missing MaterialX node '+key)
        return translate(key)
    def translate(key):
        if key in visiting: raise ValueError('MaterialX connection cycle')
        if key in cache:return cache[key]
        if len(visiting)>100: raise ValueError('MaterialX graph exceeds 100 connection levels')
        visiting.add(key);element=elements[key];category=element.tag;scope=key.rsplit('/',1)[0] if '/' in key else ''
        if category=='output':
            result=resolve(element,scope);visiting.remove(key);cache[key]=result;return result
        definition=definitions.get(element.get('nodedef'))
        if definition is not None: category=definition.get('node',category)
        extra={}
        operations={'power':6,'min':5,'max':4,'absval':15,'ceil':16,'floor':17,'modulo':18,'fract':19,'magnitude':20,'sin':21,'cos':22,'normalize':10,'dotproduct':8,'crossproduct':7}
        if category in operations:
            kind='OpMap';mapping={'in':'op1','in1':'op1','in2':'op2'};extra={'operation':operations[category]}
        elif category=='invert':kind='OpMap';mapping={'in':'op2','amount':'op1'};extra={'operation':1,'op1':[1,1,1]}
        elif category=='remap':
            kind='RemapMap';mapping={'in':'input','inlow':'input_min_RGB','inhigh':'input_max_RGB','outlow':'output_min_RGB','outhigh':'output_max_RGB'};extra={'remap_method':1,'clamp_RGB':False}
        elif category=='standard_surface': kind='DwaBaseMaterial';mapping=STANDARD
        elif category.startswith('moonray_') and category[8:] in set(nodes.kinds()): kind=category[8:];mapping={k:k for k in nodes.specs(kind)}
        elif category=='texcoord':
            kind='UVTransformMap';mapping={'index':'_uv_index'};extra={'space':6}
        elif category in nodes.MAPS: kind=category;mapping={k:k for k in nodes.specs(kind)}
        elif category=='constant': kind='constant';mapping={'value':'value'}
        else: raise ValueError('Unsupported MaterialX node: '+category+' ('+key+')')
        identity='n'+str(len(graph['nodes']));cache[key]=identity
        item={'type':kind,'parameters':dict(extra),'inputs':{},'position':[len(graph['nodes'])*240,0]};graph['nodes'][identity]=item
        ports={p.get('name'):p for p in definition.findall('input')} if definition is not None else {}
        ports.update({p.get('name'):p for p in element.findall('input')})
        if category=='standard_surface':
            item['parameters'].update(show_emission=True,show_clearcoat=True,
                albedo=[.8,.8,.8],metallic_color=[.8,.8,.8],roughness=.2,specular=1,
                refractive_index=1.5,clearcoat=0,clearcoat_roughness=.1,
                clearcoat_refractive_index=1.5,transmission=0,emission=[1,1,1])
        ports={name:interface(port,scope) for name,port in ports.items()}
        for name,port in ports.items():
            if port.get('channels'):raise ValueError('MaterialX channel swizzles require explicit channel nodes')
            if name in ('base','emission') and category=='standard_surface': continue
            if not any(attr in port.attrib for attr in ('value','nodename','nodegraph','interfacename')): continue
            if name not in mapping: raise ValueError('Unsupported MaterialX input '+category+'.'+str(name))
            target=mapping[name]
            if target=='_uv_index':
                if port.get('value','0')!='0' or any(port.get(a) for a in ('nodename','nodegraph')):raise ValueError('Nonzero MaterialX UV indices require named UV assignment')
                continue
            if port.get('nodename') or port.get('nodegraph') or port.get('interfacename'):
                item['inputs'][target]=resolve(port,scope)
            elif 'value' in port.attrib:
                value=parse_value(port)
                if kind=='constant' and isinstance(value,(int,float)): value=[value]*3
                if (kind=='image' and name=='file') or 'FLAGS_FILENAME' in nodes.specs(kind)[target].get('flags',''):
                    prefix=element.get('fileprefix',document.get('fileprefix',''))
                    value=str((path.parent/prefix/value).resolve())
                if nodes.specs(kind)[target]['type'] in ('Rgb','Vec3f') and isinstance(value,(int,float)): value=[value]*3
                if target=='texcoord' and isinstance(value,list) and len(value)==2:value=value+[0]
                item['parameters'][target]=value
        if kind=='image' and not category.startswith('moonray_'):
            space=element.get('colorspace',document.get('colorspace',''))
            file_port=ports.get('file')
            if file_port is not None: space=file_port.get('colorspace',space)
            item['parameters']['color_space']=space
            item['parameters']['srgb']=space in ('srgb_texture','sRGB')
            if element.get('type','color3')=='float': item['parameters']['channel']=1
            elif element.get('type','color3') not in ('color3','vector3'): raise ValueError('Only float/color3/vector3 images are supported')
        if category=='standard_surface':
            # Metal tint follows unweighted base_color; diffuse base weight is separate.
            item['parameters']['metallic_color']=copy.deepcopy(item['parameters'].get('albedo',[.8,.8,.8]))
            if 'albedo' in item['inputs']: item['inputs']['metallic_color']=item['inputs']['albedo']
            for weight,color,target,default in [('base','base_color','albedo',1),('emission','emission_color','emission',0)]:
                port=ports.get(weight)
                if port is None or not any(a in port.attrib for a in ('value','nodename','nodegraph','interfacename')):
                    if weight=='emission': item['inputs'].pop(target,None);item['parameters'][target]=[0,0,0]
                    continue
                if port.get('interfacename'): raise ValueError('MaterialX interface inputs require expansion before import')
                connected=bool(port.get('nodename') or port.get('nodegraph'))
                amount=None if connected else parse_value(port)
                if amount==1: continue
                multiply='n'+str(len(graph['nodes']))
                mult={'type':'multiply','parameters':{'in1':item['parameters'].pop(target,[1,1,1]),'in2':[amount]*3 if amount is not None else [1]*3},'inputs':{},'position':[0,200]}
                if target in item['inputs']: mult['inputs']['in1']=item['inputs'].pop(target)
                graph['nodes'][multiply]=mult
                if connected: mult['inputs']['in2']=resolve(port,scope)
                item['inputs'][target]=multiply
        visiting.remove(key)
        return identity
    surface=materials[0].find("input[@name='surfaceshader']")
    if surface is None: raise ValueError('MaterialX surface material has no surfaceshader input')
    graph['root']=resolve(surface,'')
    displacement=materials[0].find("input[@name='displacementshader']")
    if displacement is not None:graph['displacement']=resolve(displacement,'')
    nodes.validate(graph)
    return graph


def write(graph,path):
    """Export explicit native NodeDefs; these require MoonRayForModo to render."""
    graph=nodes.validate(graph)
    document=ET.Element('materialx',version='1.38')
    kinds=sorted({node['type'] for node in graph['nodes'].values()})
    reverse={'Float':'float','Int':'integer','Bool':'boolean','Rgb':'color3','Vec2f':'vector2','Vec3f':'vector3','String':'string','SceneObject*':'surfaceshader'}
    def output_type(kind):
        return 'surfaceshader' if nodes.category(kind)=='material' else 'displacementshader' if nodes.category(kind)=='displacement' else 'vector3' if nodes.category(kind)=='normal' else 'color3'
    def input_type(kind,key,spec):
        if kind=='image' and key=='file' or 'FLAGS_FILENAME' in spec.get('flags',''): return 'filename'
        if spec['type']=='SceneObject*':
            if spec.get('interface')=='INTERFACE_NORMALMAP':return 'vector3'
            if spec.get('interface')=='INTERFACE_MAP':return 'color3'
            if spec.get('interface')=='INTERFACE_DISPLACEMENT':return 'displacementshader'
        return reverse.get(spec['type'])
    for kind in kinds:
        definition=ET.SubElement(document,'nodedef',name='ND_moonray_'+kind,node='moonray_'+kind)
        ET.SubElement(definition,'output',name='out',type=output_type(kind))
        for key,spec in nodes.specs(kind).items():
            xtype=input_type(kind,key,spec)
            if xtype: ET.SubElement(definition,'input',name=key,type=xtype)
    for identity,node in graph['nodes'].items():
        native=node['type'] in shader_library.catalog();kind=node['type']
        element=ET.SubElement(document,'moonray_'+kind,name=identity,type=output_type(kind))
        element.set('nodedef','ND_moonray_'+kind)
        schema=nodes.specs(kind)
        for key in sorted(set(node.get('parameters',{}))|set(node.get('inputs',{}))):
            spec=schema[key];xtype=input_type(kind,key,spec)
            if xtype is None: raise ValueError('MaterialX export does not support '+spec['type'])
            port=ET.SubElement(element,'input',name=key,type=xtype)
            if key in node.get('inputs',{}):
                source=node['inputs'][key]
                if output_type(graph['nodes'][source]['type'])!=xtype:
                    raise ValueError('MaterialX export requires matching socket types: '+kind+'.'+key+'. This graph can still be saved and rendered in Modo.')
                port.set('nodename',source)
            else:
                value=node['parameters'][key]
                if isinstance(value,dict): raise ValueError('External scene-material references must be replaced with graph nodes before MaterialX export')
                port.set('value',str(value).lower() if isinstance(value,bool) else ', '.join(str(v) for v in value) if isinstance(value,list) else str(value))
    output=ET.SubElement(document,'surfacematerial',name='MoonRayMaterial',type='material')
    ET.SubElement(output,'input',name='surfaceshader',type='surfaceshader',nodename=graph['root'])
    if graph.get('displacement'):ET.SubElement(output,'input',name='displacementshader',type='displacementshader',nodename=graph['displacement'])
    ET.indent(document)
    ET.ElementTree(document).write(str(path),encoding='utf-8',xml_declaration=True)
