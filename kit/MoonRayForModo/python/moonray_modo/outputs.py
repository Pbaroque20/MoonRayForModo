"""Validated, named MoonRay render outputs and display classification."""
import re
from . import options
KINDS={'lpe':'Light path expression','material':'Material AOV','cryptomatte':'Cryptomatte','motion':'Motion vectors',
       'depth':'Depth','normal':'Normal','position':'World position','alpha':'Alpha'}

# Light path expressions that are often wanted, as (what it is called, a name for the output, the expression). The
# single words are MoonRay's own shorthand for an expression.
PRESETS=(('Direct diffuse','diffuse_direct_light','C<RD>[<L.>O]'),
         ('Indirect diffuse','diffuse_indirect','C<RD>[DSG]+[<L.>O]'),
         ('Direct glossy','glossy_direct_light','C<RG>[<L.>O]'),
         ('Indirect glossy','glossy_indirect','C<RG>[DSG]+[<L.>O]'),
         ('Mirror reflections','reflections','reflection'),
         ('Refractions','refractions','transmission'),
         ('Subsurface and translucency','translucency','translucent'),
         ('Caustics','caustics','caustic'),
         ('Emission','emitted','emission'),
         ('Diffuse without shadows','diffuse_unshadowed','unoccluded;CD[<L.>O]'))
LPE_WORDS=('caustic','diffuse','emission','glossy','mirror','reflection','translucent','transmission')

def lpe_problem(expression):
    """What is wrong with a light path expression, in plain words, or None if nothing is seen to be. It looks at how
    the expression is written, not at whether MoonRay will find any light on such a path."""
    text=expression.strip()
    if not text:return 'Enter a light path expression'
    if ';' in text:
        prefix,text=(part.strip() for part in text.split(';',1))
        if prefix!='unoccluded':return 'The only word allowed before a semicolon is unoccluded'
        if not text:return 'Enter an expression after the semicolon'
    if text in LPE_WORDS:return None
    if re.fullmatch(r'[a-z]+',text):return 'Unknown word "%s". MoonRay knows: %s'%(text,', '.join(LPE_WORDS))
    if text.count("'")%2:return 'A label in quotes is not closed'
    bare=re.sub(r"'[^']*'",'',text)
    odd=sorted(set(re.findall(r"[^A-Za-z.*+?^|()\[\]<>{},0-9 ]",bare)))
    if odd:return 'These characters do not belong in an expression: '+' '.join(odd)
    letters=sorted(set(re.findall(r'[A-Za-z]',bare))-set('CRTVLOBDGSsUM'))
    if letters:return ('Unknown event %s. Events are C camera, R reflection, T transmission, V volume, L light, O emission, B background; '
                       'D diffuse, G glossy, S mirror, s straight')%', '.join(letters)
    for opening,closing,name in (('[',']','square brackets'),('<','>','angle brackets'),('(',')','parentheses')):
        depth=0
        for character in bare:
            depth+=character==opening;depth-=character==closing
            if depth<0:break
        if depth:return 'The %s do not match'%name
    if re.search(r'\[\s*\]|<\s*>|\(\s*\)',bare):return 'Empty brackets'
    if re.match(r'[*+?|]',bare) or re.search(r'[|(\[<][*+?]',bare):return 'A *, + or ? has nothing before it to repeat'
    if not bare.lstrip('( ').startswith('C'):return 'An expression starts at the camera, with C'
    return None

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
        if v['kind']=='lpe' and lpe_problem(v['expression']):raise ValueError('%s: %s'%(name,lpe_problem(v['expression'])))
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
