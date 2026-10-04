"""Scene-owned node graphs compiled to the installed MoonRay shaders."""
import copy
import math
from . import shader_library,coordinates,map_library

MAPS={
 'constant':{'value':('Rgb',[.5,.5,.5])},
 'texcoord':{'index':('Int',0),'uv_map':('String','')},
 'swizzle':{'in':('Rgb',[0,0,0]),'channels':('String','rgb'),'index':('Int',0)},
 'combine':{'in1':('Float',0),'in2':('Float',0),'in3':('Float',0)},
 'clamp':{'in':('Rgb',[0,0,0]),'low':('Rgb',[0,0,0]),'high':('Rgb',[1,1,1])},
 'image':{'file':('String',''),'srgb':('Bool',True),'color_space':('String',''),'uv_map':('String',''),'scale':('Vec2f',[1,1]),'channel':('Int',0),'texcoord':('Vec3f',[0,0,0]),'uaddressmode':('String','periodic'),'vaddressmode':('String','periodic'),'default':('Rgb',[0,0,0]),'filtertype':('String','linear')},
 'multiply':{'in1':('Rgb',[1,1,1]),'in2':('Rgb',[1,1,1])},
 'add':{'in1':('Rgb',[0,0,0]),'in2':('Rgb',[0,0,0])},
 'subtract':{'in1':('Rgb',[0,0,0]),'in2':('Rgb',[0,0,0])},
 'divide':{'in1':('Rgb',[1,1,1]),'in2':('Rgb',[1,1,1])},
 'mix':{'bg':('Rgb',[0,0,0]),'fg':('Rgb',[1,1,1]),'mix':('Float',.5)},
 'checker':{'color1':('Rgb',[0,0,0]),'color2':('Rgb',[1,1,1]),'scale':('Vec2f',[8,8])},
 'normalmap':{'in':('Rgb',[.5,.5,1]),'scale':('Float',1),'basis_mode':('Int',0),'uv_map':('String',''),'basis_scale':('Vec2f',[1,1]),'basis_rotation':('Float',0),'basis_offset':('Vec2f',[0,0])},
}

from .math_nodes import SCHEMAS as MATH_SCHEMAS
MAPS.update(MATH_SCHEMAS)

def specs(kind):
    if kind in shader_library.catalog(): return shader_library.catalog()[kind]['attributes']
    if kind in map_library.catalog():return map_library.catalog()[kind]['attributes']
    if kind not in MAPS: raise ValueError('Unsupported node type: '+str(kind))
    result={key:{'name':key,'type':value[0],'default_value':value[1],
                  'flags':'FLAGS_BINDABLE' if key not in ('file','srgb','color_space','uv_map','scale','channel','channels','index','doclamp','uaddressmode','vaddressmode','default','filtertype','basis_mode','basis_scale','basis_rotation','basis_offset') else ''} for key,value in MAPS[kind].items()}
    if kind=='normalmap':
        result['basis_mode']['enum']={'Connected image UVs':0,'Explicit UV basis':1,'Primary shading basis':2}
        result['basis_rotation']['comment']='UV basis rotation in degrees; used only with Explicit UV basis.'
    return result


def category(kind):
    if kind in shader_library.catalog(): return 'material'
    if map_library.catalog().get(kind,{}).get('type')=='Displacement':return 'displacement'
    return 'normal' if kind=='normalmap' or map_library.catalog().get(kind,{}).get('type')=='NormalMap' else 'map'


def connectable(kind,key):
    spec=specs(kind)[key]
    return (spec['type']=='SceneObject*' and spec.get('interface','') in ('INTERFACE_MAP','INTERFACE_NORMALMAP','INTERFACE_MATERIAL','INTERFACE_DWABASELAYERABLE','INTERFACE_HAIRLAYERABLE','INTERFACE_DISPLACEMENT')) or 'FLAGS_BINDABLE' in spec.get('flags','')


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
    if g.get('displacement') and (g['displacement'] not in nodes or category(nodes[g['displacement']]['type'])!='displacement'):
        raise ValueError('Choose a Displacement node for the displacement output')
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
                elif output=='displacement':
                    if interface!='INTERFACE_DISPLACEMENT':raise ValueError('Displacement output requires a Displacement socket')
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
    value=dict(node.get('parameters',{}))
    if node['type']=='texcoord' and not value.get('uv_map'):
        index=int(value.get('index',0))
        if index<0:raise ValueError('UV set index cannot be negative')
        value['uv_map']='@index:'+str(index)
    layer={'projection':'uv','uv_map':value.get('uv_map',''),'scale':value.get('scale',[1,1])}
    layer['coordinate_key']=coordinates.key(layer)
    return layer


def descriptors(graph):
    g=validate(graph)
    result=[image_descriptor(node) for node in g['nodes'].values() if node['type'] in ('image','texcoord') and 'texcoord' not in node.get('inputs',{})]
    for node in g['nodes'].values():
        if node['type']=='normalmap':
            descriptor=normal_descriptor(node,g)
            if descriptor:result.append(descriptor)
    return result


def normal_descriptor(node,graph):
    """Per-node tangent bases; never replace another normal node's UV set."""
    import math
    p=node.get('parameters',{});mode=p.get('basis_mode',0)
    if mode not in (0,1,2):raise ValueError('Normal basis mode must be 0 (image), 1 (explicit UV), or 2 (primary)')
    if mode==2:return None
    if mode==1:
        offset=p.get('basis_offset',[0,0])
        layer={'projection':'uv','uv_map':p.get('uv_map',''),'scale':p.get('basis_scale',[1,1]),
               'rotation':math.radians(p.get('basis_rotation',0)),
               'uv_matrix':[1,0,offset[0],0,1,offset[1]]}
        layer['coordinate_key']=coordinates.key(layer)
        return layer
    source=graph['nodes'].get(node.get('inputs',{}).get('in'),{})
    if source.get('type')!='image':return None
    coord=source.get('inputs',{}).get('texcoord')
    if coord:
        uv=graph['nodes'][coord]
        return image_descriptor(uv) if uv['type']=='texcoord' else None
    if 'texcoord' in source.get('parameters',{}):return None
    return image_descriptor(source)


def emit(material,name,index,lines,library,output="root"):
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
        unit='Rgb(1,1,1)' if kind=='Rgb' else 'Vec3(1,1,1)' if kind=='Vec3f' else 'Vec2(1,1)' if kind=='Vec2f' else '1'
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
            if kind in MATH_SCHEMAS:
                from .math_nodes import emit as emit_math
                ref=emit_math(kind,path,params,refs,definition)
            elif kind=='image':
                descriptor=image_descriptor(item)
                uv=refs.get('texcoord')
                if uv is None and 'texcoord' in params:uv=definition('ConstantColorMap',path+'/authored_uv',{'color_value':vector(params['texcoord'],'Rgb')})
                if uv is None:uv=definition('AttributeMap',path+'/uv',{'primitive_attribute_name':string(descriptor['coordinate_key']),'primitive_attribute_type':'1','warn_when_unavailable':'true'})
                address={'periodic':0,'clamp':1,'mirror':2,'constant':3}
                u,v=params.get('uaddressmode','periodic'),params.get('vaddressmode','periodic')
                if u not in address or v not in address:raise ValueError('Unknown image address mode')
                if params.get('filtertype','linear')!='linear':raise ValueError('This image node supports linear filtering; choose a native ImageMap for other texture controls')
                filename=params.get('file','')
                if not filename:
                    ref=definition('ConstantColorMap',path,{'color_value':values['default']})
                    cache[identity]=ref
                    return ref
                coverage=None
                if (u,v)!=('periodic','periodic'):
                    if '<UDIM>' in filename:raise ValueError('UDIM images require periodic address modes')
                    wrap={'coordinates':binding(uv,'Rgb'),'use_coordinates':'true','tile_u':str(address[u]),'tile_v':str(address[v])}
                    if 'constant' in (u,v):coverage=definition('ModoTextureMap',path+'/coverage',dict(wrap,mode='6'))
                    uv=definition('ModoTextureMap',path+'/wrapped',dict(wrap,mode='5'))
                attributes={'texture':string(prepare(filename,params.get('srgb',True),color_space=params.get('color_space',''))),'gamma':'0','texture_coordinates':'2','input_texture_coordinates':binding(uv,'Vec3f'),'wrap_around':'true' if (u,v)==('periodic','periodic') else 'false'}
                rgb=definition('ImageMap',path+'/rgb',attributes)
                alpha=definition('ImageMap',path+'/alpha',dict(attributes,alpha_only='true'))
                ref=definition('ModoTextureMap',path,{'background':binding(rgb,'Rgb'),'foreground':binding(alpha,'Rgb'),'blend':'5'})
                channel=params.get('channel',0)
                if not 0<=channel<=4: raise ValueError('Image channel must be 0 (RGB), 1-3 (RGB components), or 4 (alpha)')
                if channel==4: ref=alpha
                elif channel: ref=definition('ModoTextureMap',path+'/component',{'mode':'7','foreground':binding(ref,'Rgb'),'component':str(channel-1)})
                if coverage:ref=definition('ModoTextureMap',path+'/default',{'background':values['default'],'foreground':binding(ref,'Rgb'),'mask':binding(coverage,'Float')})
            elif kind=='texcoord':
                ref=definition('AttributeMap',path,{'primitive_attribute_name':string(image_descriptor(item)['coordinate_key']),'primitive_attribute_type':'1','warn_when_unavailable':'true'})
            elif kind=='swizzle':
                channels=params.get('channels','rgb')
                if len(channels) not in (1,2,3) or any(c not in 'rgbxyz01' for c in channels):raise ValueError('Invalid component swizzle')
                if len(channels)==1:channels*=3
                elif len(channels)==2:channels+='0'
                components=[]
                for i,c in enumerate(channels):
                    component='Rgb(%s,%s,%s)'%(c,c,c) if c in '01' else binding(definition('ModoTextureMap',path+'/extract'+str(i),{'mode':'7','foreground':values['in'],'component':str('rgbxyz'.index(c)%3)}),'Rgb')
                    unit=[0,0,0];unit[i]=1
                    components.append(definition('ModoTextureMap',path+'/isolate'+str(i),{'background':component,'foreground':vector(unit,'Rgb'),'blend':'1'}))
                ref=definition('ModoTextureMap',path+'/sum01',{'background':binding(components[0],'Rgb'),'foreground':binding(components[1],'Rgb'),'blend':'2'})
                ref=definition('ModoTextureMap',path,{'background':binding(ref,'Rgb'),'foreground':binding(components[2],'Rgb'),'blend':'2'})
            elif kind=='combine':
                components=[]
                for i,key in enumerate(('in1','in2','in3')):
                    unit=[0,0,0];unit[i]=1
                    val=binding(refs[key],'Rgb') if key in refs else vector([params.get(key,0)]*3,'Rgb')
                    components.append(definition('ModoTextureMap',path+'/isolate'+str(i),{'background':val,'foreground':vector(unit,'Rgb'),'blend':'1'}))
                ref=definition('ModoTextureMap',path+'/sum01',{'background':binding(components[0],'Rgb'),'foreground':binding(components[1],'Rgb'),'blend':'2'})
                ref=definition('ModoTextureMap',path,{'background':binding(ref,'Rgb'),'foreground':binding(components[2],'Rgb'),'blend':'2'})
            elif kind=='clamp':
                low=definition('OpMap',path+'/low',{'operation':'4','op1':values['in'],'op2':values['low']})
                ref=definition('OpMap',path,{'operation':'5','op1':binding(low,'Rgb'),'op2':values['high']})
            elif kind=='constant': ref=definition('ModoTextureMap',path,{'foreground':values['value']})
            elif kind in ('multiply','add','subtract','divide'):
                ref=definition('ModoTextureMap',path,{'background':values['in1'],'foreground':values['in2'],'blend':str({'multiply':1,'add':2,'subtract':3,'divide':5}[kind])})
            elif kind=='mix': ref=definition('ModoTextureMap',path,{'background':values['bg'],'foreground':values['fg'],'opacity':values['mix']})
            elif kind=='checker': ref=definition('ModoTextureMap',path,{'mode':'2','background':values['color1'],'foreground':values['color2'],'scale':values['scale']})
            elif kind=='normalmap':
                normal=values['in']
                source=g['nodes'].get(item.get('inputs',{}).get('in'),{})
                descriptor=normal_descriptor(item,g)
                if descriptor:
                    p=source.get('parameters',{});address={'periodic':0,'clamp':1,'mirror':2,'constant':3}
                    corrected=definition('ModoTextureMap',path+'/uv_basis',{'mode':'13','foreground':normal,'uv_name':string(descriptor['coordinate_key']),'tile_u':str(address[p.get('uaddressmode','periodic')]),'tile_v':str(address[p.get('vaddressmode','periodic')])})
                    normal=binding(corrected,'Rgb')
                mapped=definition('ModoTextureMap',path+'/tangent',{'mode':'1','normal':normal,'normal_strength':values['scale']})
                ref=definition('ModoNormalMap',path,{'input':binding(mapped,'Vec3f')})
        cache[identity]=ref
        return ref
    return node(g[output])


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
