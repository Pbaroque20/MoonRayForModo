"""Scene-owned node graphs compiled to the installed MoonRay shaders."""
import copy
import math
from . import shader_library,coordinates,map_library

MAPS={
 'constant':{'value':('Rgb',[.5,.5,.5])},
 'image':{'file':('String',''),'srgb':('Bool',True),'uv_map':('String',''),'scale':('Vec2f',[1,1]),'channel':('Int',0),'texcoord':('Vec3f',[0,0,0])},
 'multiply':{'in1':('Rgb',[1,1,1]),'in2':('Rgb',[1,1,1])},
 'add':{'in1':('Rgb',[0,0,0]),'in2':('Rgb',[0,0,0])},
 'subtract':{'in1':('Rgb',[0,0,0]),'in2':('Rgb',[0,0,0])},
 'divide':{'in1':('Rgb',[1,1,1]),'in2':('Rgb',[1,1,1])},
 'mix':{'bg':('Rgb',[0,0,0]),'fg':('Rgb',[1,1,1]),'mix':('Float',.5)},
 'checker':{'color1':('Rgb',[0,0,0]),'color2':('Rgb',[1,1,1]),'scale':('Vec2f',[8,8])},
 'normalmap':{'in':('Rgb',[.5,.5,1]),'scale':('Float',1)},
}


def specs(kind):
    if kind in shader_library.catalog(): return shader_library.catalog()[kind]['attributes']
    if kind in map_library.catalog():return map_library.catalog()[kind]['attributes']
    if kind not in MAPS: raise ValueError('Unsupported node type: '+str(kind))
    return {key:{'name':key,'type':value[0],'default_value':value[1],
                  'flags':'FLAGS_BINDABLE' if key not in ('file','srgb','uv_map','scale','channel') else ''} for key,value in MAPS[kind].items()}


def category(kind):
    if kind in shader_library.catalog(): return 'material'
    return 'normal' if kind=='normalmap' or map_library.catalog().get(kind,{}).get('type')=='NormalMap' else 'map'


def connectable(kind,key):
    spec=specs(kind)[key]
    return (spec['type']=='SceneObject*' and spec.get('interface','') in ('INTERFACE_MAP','INTERFACE_NORMALMAP','INTERFACE_MATERIAL','INTERFACE_DWABASELAYERABLE','INTERFACE_HAIRLAYERABLE')) or 'FLAGS_BINDABLE' in spec.get('flags','')


def effective(graph):
    if not isinstance(graph,dict) or graph.get('version')!=1: raise ValueError('Unsupported node graph version')
    result=copy.deepcopy(graph)
    if not isinstance(result.get('nodes'),dict) or len(result['nodes'])>1000: raise ValueError('Node graph requires at most 1000 nodes')
    for override in result.get('overrides',[]):
        if not override.get('enabled',True): continue
        node=result['nodes'].get(override.get('node'))
        if node is None: raise ValueError('Override target is missing')
        for key,value in override.get('parameters',{}).items():
            node.setdefault('parameters',{})[key]=value
            node.setdefault('inputs',{}).pop(key,None)
        for key,value in override.get('inputs',{}).items():
            if value is None: node.setdefault('inputs',{}).pop(key,None)
            else: node.setdefault('inputs',{})[key]=value
    return result


def validate(graph):
    g=effective(graph);nodes=g['nodes']
    root=g.get('root')
    if root not in nodes or category(nodes[root]['type'])!='material': raise ValueError('Choose a surface material as graph output')
    for identity,node in nodes.items():
        if not isinstance(identity,str) or not identity: raise ValueError('Invalid node identity')
        schema=specs(node['type'])
        for key,value in node.get('parameters',{}).items():
            if key not in schema: raise ValueError(node['type']+' has no input '+key)
            shader_library.typed(value,schema[key])
        for key,source in node.get('inputs',{}).items():
            if key not in schema or not connectable(node['type'],key): raise ValueError('Input is not connectable: '+key)
            if source not in nodes: raise ValueError('Missing connected node: '+str(source))
            source_kind=nodes[source]['type'];output=category(source_kind);spec=schema[key]
            if spec['type']=='SceneObject*':
                interface=spec.get('interface','')
                if output=='material':
                    if not shader_library.compatible(source_kind,interface): raise ValueError('Incompatible material input: '+key)
                elif output=='normal':
                    if interface!='INTERFACE_NORMALMAP': raise ValueError('Normal output requires a NormalMap input')
                elif interface!='INTERFACE_MAP': raise ValueError('Map must connect to a Map or bindable numeric/color input')
            elif output!='map': raise ValueError('Expected a texture/value node at '+key)
    complete=set()
    def visit(identity,trail):
        if identity in trail: raise ValueError('Node graph contains a cycle')
        if len(trail)>100: raise ValueError('Node graph exceeds 100 connection levels')
        if identity in complete: return
        for source in nodes[identity].get('inputs',{}).values(): visit(source,trail+(identity,))
        complete.add(identity)
    for identity in nodes: visit(identity,())
    return g


def kinds():
    return list(MAPS)+sorted(map_library.catalog())+sorted(shader_library.catalog())


def new(shader='DwaBaseMaterial',parameters=None):
    return {'version':1,'root':'surface','nodes':{'surface':{'type':shader,'parameters':parameters or {},'inputs':{},'position':[300,50]}},'overrides':[]}


def image_descriptor(node):
    value=node.get('parameters',{})
    layer={'projection':'uv','uv_map':value.get('uv_map',''),'scale':value.get('scale',[1,1])}
    layer['coordinate_key']=coordinates.key(layer)
    return layer


def descriptors(graph):
    g=validate(graph)
    return [image_descriptor(node) for node in g['nodes'].values() if node['type']=='image' and 'texcoord' not in node.get('inputs',{})]


def emit(material,name,index,lines,library):
    from .rdla import string,number,vector
    from .textures import prepare
    g=validate(material['node_graph']);cache={}
    def definition(kind,path,attributes):
        lines.append('%s(%s) {'%(kind,string(path)))
        lines.extend('  [%s] = %s,'%(string(key),value) for key,value in attributes.items())
        lines.append('}')
        return '%s(%s)'%(kind,string(path))
    def literal(value,kind):
        if kind=='Bool': return 'true' if value else 'false'
        if kind=='String': return string(value)
        if isinstance(value,list): return vector(value,{'Rgb':'Rgb','Vec2f':'Vec2','Vec3f':'Vec3'}.get(kind,'Rgb'))
        return number(value)
    def binding(ref,kind):
        unit='Rgb(1,1,1)' if kind=='Rgb' else 'Vec3(1,1,1)' if kind=='Vec3f' else '1'
        return 'bind(%s, %s)'%(ref,unit)
    def node(identity):
        if identity in cache: return cache[identity]
        item=g['nodes'][identity];kind=item['type'];params=item.get('parameters',{});inputs=item.get('inputs',{})
        path=name+'/node/'+str(len(cache))+'_'+identity
        schema=specs(kind)
        refs={key:node(source) for key,source in inputs.items()}
        if kind in shader_library.catalog():
            overrides={key:ref if schema[key]['type']=='SceneObject*' else binding(ref,schema[key]['type']) for key,ref in refs.items()}
            settings=dict(material if identity==g['root'] else {'color':[.5]*3},native_shader=kind,native_parameters=params)
            ref=shader_library.emit(settings,path,index,lines,library,authored_bindings=overrides)
        elif kind in map_library.catalog():
            ref=map_library.emit(kind,path,params,refs,definition)
        else:
            values={key:binding(refs[key],spec['type']) if key in refs else literal(params.get(key,spec['default_value']),spec['type']) for key,spec in schema.items()}
            if kind=='image':
                descriptor=image_descriptor(item)
                uv=refs.get('texcoord')
                if uv is None and 'texcoord' in params:uv=definition('ConstantColorMap',path+'/authored_uv',{'color_value':vector(params['texcoord'],'Rgb')})
                if uv is None:uv=definition('AttributeMap',path+'/uv',{'primitive_attribute_name':string(descriptor['coordinate_key']),'primitive_attribute_type':'1','warn_when_unavailable':'true'})
                attributes={'texture':string(prepare(params.get('file',''),params.get('srgb',True))),'gamma':'0','texture_coordinates':'2','input_texture_coordinates':binding(uv,'Vec3f')}
                rgb=definition('ImageMap',path+'/rgb',attributes)
                alpha=definition('ImageMap',path+'/alpha',dict(attributes,alpha_only='true'))
                ref=definition('ModoTextureMap',path,{'background':binding(rgb,'Rgb'),'foreground':binding(alpha,'Rgb'),'blend':'5'})
                channel=params.get('channel',0)
                if not 0<=channel<=4: raise ValueError('Image channel must be 0 (RGB), 1-3 (RGB components), or 4 (alpha)')
                if channel==4: ref=alpha
                elif channel: ref=definition('ModoTextureMap',path+'/component',{'mode':'7','foreground':binding(ref,'Rgb'),'component':str(channel-1)})
            elif kind=='constant': ref=definition('ModoTextureMap',path,{'foreground':values['value']})
            elif kind in ('multiply','add','subtract','divide'):
                ref=definition('ModoTextureMap',path,{'background':values['in1'],'foreground':values['in2'],'blend':str({'multiply':1,'add':2,'subtract':3,'divide':5}[kind])})
            elif kind=='mix': ref=definition('ModoTextureMap',path,{'background':values['bg'],'foreground':values['fg'],'opacity':values['mix']})
            elif kind=='checker': ref=definition('ModoTextureMap',path,{'mode':'2','background':values['color1'],'foreground':values['color2'],'scale':values['scale']})
            elif kind=='normalmap':
                mapped=definition('ModoTextureMap',path+'/tangent',{'mode':'1','normal':values['in'],'normal_strength':values['scale']})
                ref=definition('ModoNormalMap',path,{'input':binding(mapped,'Vec3f')})
        cache[identity]=ref
        return ref
    return node(g['root'])


def from_material(item):
    from . import properties
    from .host import material_values
    settings=properties.read(item)
    if settings.get('native_shader'): return new(settings['native_shader'],settings.get('native_parameters',{}))
    value=material_values(item)
    # Use the same supported constants as the existing DwaBase translation.
    parameters={'albedo':value['color'],'roughness':value['roughness'],'metallic':value['metallic'],
                'metallic_color':value['color'],'refractive_index':value['ior'],'transmission':value['transmission'],
                'transmission_color':value['transmission_color'],'presence':value['presence'],
                'show_emission':True,'emission':value['emission'],'show_clearcoat':True,
                'clearcoat':value['clearcoat'],'clearcoat_roughness':value['clearcoat_roughness'],
                'thin_geometry':value['thin_geometry']}
    shader_library.validate('DwaBaseMaterial',parameters)
    return new('DwaBaseMaterial',parameters)
