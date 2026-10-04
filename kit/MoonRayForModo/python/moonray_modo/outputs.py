"""Validated, named MoonRay render outputs and display classification."""
import re
from . import options
KINDS={'lpe':'Light path expression','material':'Material AOV','cryptomatte':'Cryptomatte','motion':'Motion vectors',
       'depth':'Depth','normal':'Normal','position':'World position','alpha':'Alpha'}

def values(entries):
    if not isinstance(entries,list) or len(entries)>128:raise ValueError('Use at most 128 custom outputs')
    result=[];names=set(options.AOVS)|{'beauty','denoised_beauty','denoise_albedo','denoise_normal','R','G','B','A','object_id','modo_object_id'}
    for entry in entries:
        v=dict(entry);name=v.get('name','')
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',name) or name.casefold() in {n.casefold() for n in names}:raise ValueError('Output names must be unique: '+name)
        names.add(name)
        if v.get('kind') not in KINDS:raise ValueError('Unknown output type')
        v.setdefault('precision',0);v.setdefault('filter',0);v.setdefault('part','');v.setdefault('expression','');v.setdefault('depth',6);v.setdefault('category','object')
        if v['precision'] not in (0,1) or v['filter'] not in range(6):raise ValueError('Invalid output precision/filter')
        if not isinstance(v['part'],str) or not re.fullmatch(r'[A-Za-z0-9_]*',v['part']):raise ValueError('EXR part name must use letters, numbers and underscores')
        if not isinstance(v['expression'],str) or len(v['expression'])>4096:raise ValueError('Invalid AOV expression')
        if v['kind'] in ('lpe','material') and not v['expression'].strip():raise ValueError('Enter a light path or material AOV expression')
        if type(v['depth']) is not int or not 1<=v['depth']<=16:raise ValueError('Cryptomatte depth must be between 1 and 16')
        if v['category'] not in ('object','material','asset'):raise ValueError('Unknown Cryptomatte category')
        if v['kind']=='cryptomatte':v.update(precision=0,filter=0)
        result.append(v)
    crypto=[v for v in result if v['kind']=='cryptomatte']
    if len({v['category'] for v in crypto})!=len(crypto):raise ValueError('Use one Cryptomatte output per category')
    if len(crypto)>1:
        # Native Cryptomatte channel names are fixed; isolate category rank
        # channels and their manifests in distinct EXR parts.
        for v in crypto:v['part']=v['part'] or 'crypto_'+v['category']
        for v in crypto:
            if any(other is not v and other['part']==v['part'] for other in result):
                raise ValueError('Each Cryptomatte category needs its own EXR part')
    return result

def attributes(entry,multiple=False):
    kind=entry['kind']
    attrs={'channel_format':entry['precision'],'math_filter':entry['filter'],'file_part':entry['part'],'channel_name':entry['name']}
    if kind=='lpe':attrs.update(result=8,lpe=entry['expression'])
    elif kind=='material':attrs.update(result=7,material_aov=entry['expression'])
    elif kind=='cryptomatte':attrs.update(result=13,cryptomatte_depth=entry['depth'],cryptomatte_support_resume_render=True)
    elif kind=='motion':attrs.update(result=3,state_variable=12)
    else:attrs.update(options.AOVS[kind][1])
    if kind=='cryptomatte' and multiple:attrs['cryptomatte_id_channel']=('object','material','asset').index(entry['category'])
    return attrs

def preview(scene):
    result={key:dict(value[1]) for key,value in options.AOVS.items()};result['beauty']={'result':0}
    for entry in values(scene.get('custom_aovs',[])):
        attrs=attributes(entry,sum(v.get('kind')=='cryptomatte' for v in scene.get('custom_aovs',[]))>1);attrs.pop('file_part',None);attrs.pop('channel_name',None);attrs['channel_format']=0
        result[entry['name']]=attrs
    return result

def display_kind(scene,key):
    if key=='denoised_beauty':return 'beauty'
    for entry in values(scene.get('custom_aovs',[])):
        if entry['name']==key:return entry['kind'] if entry['kind'] in ('depth','normal','position','alpha','motion','cryptomatte') else 'beauty'
    return key
