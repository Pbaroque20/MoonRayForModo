"""Validated, named MoonRay render outputs and display classification."""
import re
from . import options
KINDS={'lpe':'Light path expression','material':'Material AOV','cryptomatte':'Cryptomatte','motion':'Motion vectors',
       'depth':'Depth','normal':'Normal','position':'World position','alpha':'Alpha',
       # A value the shapes carry for their materials (a vertex map, a MoonRay scene's UserData), by its name, as a picture.
       'attribute':'Primitive attribute (number)','attribute_color':'Primitive attribute (colour)',
       # How much of the light reaches each point, from 0 in full shadow to 1: MoonRay's visibility AOV.
       'visibility':'Visibility (light reaching a point)'}
# MoonRay's own visibility expression: direct light, seen straight on or through mirrors and glass, on diffuse and glossy
# surfaces, from any light. A light group's own ends in <L.'label'> instead of [LO].
VISIBILITY_DEFAULT="C[<T.><RS>]*[<R[DG]><TD>][LO]"


def visibility_expression(label=''):
    """The visibility of every light, or of the lights of one group (their label)."""
    return VISIBILITY_DEFAULT if not label else "C[<T.><RS>]*[<R[DG]><TD>]<L.'%s'>"%label
ATTRIBUTE_TYPES={'attribute':0,'attribute_color':3}     # MoonRay's primitive_attribute_type: float, rgb

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
    result=[];names=set(options.AOVS)|{'beauty','denoised_beauty','denoise_albedo','denoise_normal','denoise_fine','R','G','B','A','object_id','modo_object_id'}
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
        if v['kind'] in ATTRIBUTE_TYPES and not v['expression'].strip():raise ValueError('%s: enter the name of the primitive attribute, such as a vertex map\'s'%name)
        if v['kind']=='lpe' and lpe_problem(v['expression']):raise ValueError('%s: %s'%(name,lpe_problem(v['expression'])))
        if v['kind']=='visibility':
            # Left empty, MoonRay's own: every light.
            v['expression']=v['expression'].strip() or VISIBILITY_DEFAULT
            if lpe_problem(v['expression']):raise ValueError('%s: %s'%(name,lpe_problem(v['expression'])))
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

def has_cryptomatte(entries,category):
    """Whether the outputs hold a Cryptomatte of a category (object, material, asset): what its tick in Render Settings'
    XPU and XPU2 Outputs (AOVs) shows."""
    return any(v.get('kind')=='cryptomatte' and v.get('category','object')==category for v in entries or ())


def with_cryptomatte(entries,category,on):
    """The outputs with a category's Cryptomatte added (crypto_<category>, six ranks deep, as the preview window's buffer
    list adds one) or taken away, checked as values() checks them. The Cryptomatte is one of the outputs as any other:
    MoonRay (Vector, XPU) and XPU2 write it beside the beauty, in the EXR and in the preview's buffers. Taking one away
    where two were puts the other back in the first part, where it was before the two needed parts of their own."""
    entries=[dict(v) for v in entries or ()]
    if on:
        if has_cryptomatte(entries,category):return values(entries)
        taken={v.get('name','').casefold() for v in entries}
        name='crypto_'+category;number=1
        while name.casefold() in taken:name='crypto_%s_%d'%(category,number);number+=1
        return values(entries+[{'name':name,'kind':'cryptomatte','category':category,'depth':6}])
    entries=[v for v in entries if not (v.get('kind')=='cryptomatte' and v.get('category','object')==category)]
    left=[v for v in entries if v.get('kind')=='cryptomatte']
    if len(left)==1 and left[0].get('part')=='crypto_'+left[0].get('category','object'):left[0]['part']=''
    return values(entries)


FIRST_PART='rgba'

def in_parts(render_outputs,cryptomattes=()):
    """(name, attributes, channel) of a final EXR's outputs, each in a part of its own (a multi-part EXR). The beauty, its alpha
    and any Cryptomatte stay together in the first part, where what reads the file looks for them. An output given a part by
    the user keeps it."""
    result=[]
    for name,attrs,channel in render_outputs:
        together=name in ('beauty','alpha','environment_background') or name in cryptomattes or attrs.get('result')==13
        result.append((name,dict(attrs,file_part=attrs.get('file_part') or (FIRST_PART if together else name)),channel))
    # MoonRay writes the parts in the order it meets them: the beauty's first.
    return sorted(result,key=lambda entry:entry[1]['file_part']!=FIRST_PART)


class Raw(str):
    """An output attribute written into the scene as it is, not as text: a reference to another scene object."""

def attributes(entry,multiple=False):
    kind=entry['kind']
    attrs={'channel_format':entry['precision'],'math_filter':entry['filter'],'file_part':entry['part'],'channel_name':entry['name']}
    if kind=='lpe':attrs.update(result=8,lpe=entry['expression'])
    elif kind=='material':attrs.update(result=7,material_aov=entry['expression'])
    elif kind=='cryptomatte':attrs.update(result=13,cryptomatte_depth=entry['depth'],cryptomatte_support_resume_render=True)
    elif kind=='motion':attrs.update(result=3,state_variable=12)
    elif kind in ATTRIBUTE_TYPES:attrs.update(result=4,primitive_attribute=entry['expression'].strip(),primitive_attribute_type=ATTRIBUTE_TYPES[kind])
    elif kind=='visibility':attrs.update(result=9,visibility_aov=entry['expression'].strip() or VISIBILITY_DEFAULT)
    else:attrs.update(options.AOVS[kind][1])
    if kind=='cryptomatte' and multiple:attrs['cryptomatte_id_channel']=('object','material','asset').index(entry['category'])
    return attrs

def rendered(scene):
    """The AOVs a MoonRay XPU or XPU2 preview renders: those ticked in Render Settings (XPU and XPU2 Outputs (AOVs);
    Alpha alone in a new scene). Besides them, what other things need: with Alpha, the Environment background, which a
    picture saved with straight alpha takes out first (image_formats.with_alpha); the buffers the compositor's graph is
    made from; PBR validity while the diagnostic is on; and the buffer looked at, where it is one."""
    held=scene.get('aovs')
    ticked=set(held if isinstance(held,(list,tuple)) else ['alpha'])
    result=set(ticked)
    if 'alpha' in ticked:result.add('environment_background')
    graph=scene.get('compositor')
    if graph:
        try:
            from .compositor import buffers
            result.update(buffers(graph))
        except Exception:pass
    try:
        from .native import pbr_validity
        if pbr_validity():result.add('pbr_validity')
    except Exception:pass
    result.add(scene.get('preview_buffer','beauty'))
    return result


def listed(scene):
    """The AOVs the preview window lists for MoonRay XPU and XPU2: those ticked, and PBR validity (its own rule)."""
    held=scene.get('aovs')
    return set(held if isinstance(held,(list,tuple)) else ['alpha'])|{'pbr_validity'}


def preview(scene):
    # A quick low-sample look (MoonRay LS) is the beauty alone: no other buffer is rendered for it.
    if scene.get('_ipr'):return {'beauty':{'result':0}}
    on=rendered(scene)
    result={key:dict(value[1]) for key,value in options.AOVS.items() if key in on};result['beauty']={'result':0}
    for entry in values(scene.get('custom_aovs',[])):
        attrs=attributes(entry,sum(v.get('kind')=='cryptomatte' for v in scene.get('custom_aovs',[]))>1);attrs.pop('file_part',None);attrs.pop('channel_name',None);attrs['channel_format']=0
        result[entry['name']]=attrs
    # Each display filter is a buffer of its own.
    from . import entities
    for entity in entities.display_filters(scene):result[entities.filter_key(entity)]=entities.filter_output(entity)
    # MoonRay's realtime (a preview following the scene, _geometry_detail): the beauty, and the buffer looked at where it
    # is another, not every buffer at every edit (each was rendered, and each edit renamed their files, so that none was
    # the camera's alone). The composite is made of the others, which it keeps.
    chosen=scene.get('preview_buffer','beauty')
    if scene.get('_geometry_detail') and chosen!='composite':
        return {key:value for key,value in result.items() if key in ('beauty',chosen)}
    return result

def display_kind(scene,key):
    from .entities import FILTER_PREFIX
    # MoonLightIPR's own light passes (moonlightipr_aovs.OWN) are colours, as the beauty is.
    if key in ('denoised_beauty','composite') or key.startswith(FILTER_PREFIX) or key.startswith('moonlightipr_'):return 'beauty'
    for entry in values(scene.get('custom_aovs',[])):
        # A number shown as it is, in grey, as alpha is; a colour as the beauty.
        if entry['name']==key and entry['kind'] in ('attribute','visibility'):return 'alpha'
        if entry['name']==key:return entry['kind'] if entry['kind'] in ('depth','normal','position','alpha','motion','cryptomatte') else 'beauty'
    return key
