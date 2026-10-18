"""Display transforms only; rendering, texture inputs and saved EXRs stay linear."""
import math
from pathlib import Path

# The view a scene starts with is Modo's own colour management: the scene's OCIO configuration and the colour space
# its Final Color Output is viewed in, so that a preview reads as Modo's own render view does. ACES for an sRGB
# monitor, plain sRGB and a chosen OCIO display and view are the other choices.
DEFAULTS={'working_space':'rec709','view':'modo','exposure':0.0,'lut':'','lut_space':'display',
          'config':'','source':'Linear Rec.709 (sRGB)','display':'sRGB','ocio_view':'ACES 1.0 - SDR Video'}


# The ACES view needs no file: OpenColorIO carries the ACES configuration this names.
ACES_CONFIG='ocio://cg-config-v1.0.0_aces-v1.3_ocio-v2.1'
ACES={'config':ACES_CONFIG,'source':'Linear Rec.709 (sRGB)','display':'sRGB - Display','ocio_view':'ACES 1.0 - SDR Video'}
# ACES 2.0's output transform, from the ACES 2.0 configuration OpenColorIO 2.5 carries.
ACES2_CONFIG='ocio://cg-config-v4.0.0_aces-v2.0_ocio-v2.5'
ACES2={'config':ACES2_CONFIG,'source':'Linear Rec.709 (sRGB)','display':'sRGB - Display','ocio_view':'ACES 2.0 - SDR 100 nits (Rec.709)'}


def built_in(config):
    """Whether an OCIO configuration is one OpenColorIO carries itself, named and not a file."""
    return str(config).startswith('ocio://')


def values(settings):
    result={key:settings.get(key,value) for key,value in DEFAULTS.items()}
    if result['working_space'] not in ('rec709','acescg'):raise ValueError('Unknown render working space')
    if result['view'] not in ('modo','srgb','aces','aces2','reinhard','raw','ocio'): raise ValueError('Unknown display transform')
    if result['view']=='modo':
        # As Modo shows it: what modo_color last read of the scene. Where the scene has no colour management, or
        # nothing has been read yet, plain sRGB.
        from . import modo_color
        held=modo_color.RESOLVED
        if held:result.update(view='ocio',config=held['config'],source=held['source'],display=held['display'],ocio_view=held['view'])
        else:result['view']='srgb'
    if result['view']=='aces':
        # ACES for an sRGB monitor is an OCIO view with everything already chosen.
        result.update(ACES,view='ocio')
    elif result['view']=='aces2':
        result.update(ACES2,view='ocio')
    if result['lut_space'] not in ('linear','display'): raise ValueError('Unknown LUT placement')
    result['exposure']=float(result['exposure'])
    if not math.isfinite(result['exposure']) or not -20<=result['exposure']<=20: raise ValueError('Exposure must be between -20 and 20 stops')
    for key in ('lut','config','source','display','ocio_view'):
        if not isinstance(result[key],str): raise ValueError('Invalid display setting: '+key)
    return result


def from_ap1(v):
    """Whether ACEScg pixels are to be taken to Rec.709 before they are shown: for every view but raw, and for an OCIO
    view only where its source is not ACEScg itself (Modo's own configuration, whose linear is Rec.709)."""
    if v['working_space']!='acescg' or v['view']=='raw':return False
    if v['view']!='ocio':return True
    named=str(v.get('source','')).lower().replace(' ','').replace('-','').replace('_','')
    return not ('acescg' in named or 'ap1' in named)


def arguments(settings):
    v=values(settings)
    for key in ('lut','config'):
        if v[key] and not built_in(v[key]) and not Path(v[key]).is_file(): raise ValueError('Missing '+key+' file: '+v[key])
    args=[]
    if from_ap1(v):
        from .working_space import TO_REC709,matrix_argument
        args += ['--ccmatrix',matrix_argument(TO_REC709)]
    args += ['--mulc',str(2.0**v['exposure'])]
    if v['view']=='ocio' and v['config']: args += ['--colorconfig',v['config']]
    if v['lut'] and v['lut_space']=='linear': args += ['--ociofiletransform',v['lut']]
    if v['view']=='reinhard':
        args += ['--maxc','0','--dup','--addc','1','--div','--colorconvert','linear','sRGB']
    elif v['view']=='srgb': args += ['--colorconvert','linear','sRGB']
    elif v['view']=='ocio':
        if not all(v[key] for key in ('source','display','ocio_view')): raise ValueError('OCIO source, display and view are required')
        args += ['--ociodisplay:from='+v['source'],v['display'],v['ocio_view']]
    if v['lut'] and v['lut_space']=='display': args += ['--ociofiletransform',v['lut']]
    return args
