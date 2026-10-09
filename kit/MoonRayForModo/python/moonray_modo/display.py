"""Display transforms only; rendering, texture inputs and saved EXRs stay linear."""
import math
from pathlib import Path

# The view a scene starts with is the plain one: linear light shown as an sRGB monitor expects it, nothing else done to it.
DEFAULTS={'working_space':'rec709','view':'srgb','exposure':0.0,'lut':'','lut_space':'display',
          'config':'','source':'Linear Rec.709 (sRGB)','display':'sRGB','ocio_view':'ACES 1.0 - SDR Video'}


# The ACES view needs no file: OpenColorIO carries the ACES configuration this names.
ACES_CONFIG='ocio://cg-config-v1.0.0_aces-v1.3_ocio-v2.1'
ACES={'config':ACES_CONFIG,'source':'Linear Rec.709 (sRGB)','display':'sRGB - Display','ocio_view':'ACES 1.0 - SDR Video'}


def built_in(config):
    """Whether an OCIO configuration is one OpenColorIO carries itself, named and not a file."""
    return str(config).startswith('ocio://')


def values(settings):
    result={key:settings.get(key,value) for key,value in DEFAULTS.items()}
    if result['working_space'] not in ('rec709','acescg'):raise ValueError('Unknown render working space')
    if result['view'] not in ('srgb','aces','reinhard','raw','ocio'): raise ValueError('Unknown display transform')
    if result['view']=='aces':
        # ACES for an sRGB monitor is an OCIO view with everything already chosen.
        result.update(ACES,view='ocio')
    if result['lut_space'] not in ('linear','display'): raise ValueError('Unknown LUT placement')
    result['exposure']=float(result['exposure'])
    if not math.isfinite(result['exposure']) or not -20<=result['exposure']<=20: raise ValueError('Exposure must be between -20 and 20 stops')
    for key in ('lut','config','source','display','ocio_view'):
        if not isinstance(result[key],str): raise ValueError('Invalid display setting: '+key)
    return result


def arguments(settings):
    v=values(settings)
    for key in ('lut','config'):
        if v[key] and not built_in(v[key]) and not Path(v[key]).is_file(): raise ValueError('Missing '+key+' file: '+v[key])
    args=[]
    if v['working_space']=='acescg' and v['view'] not in ('raw','ocio'):
        from .working_space import TO_REC709,matrix_argument
        args += ['--colormatrix',matrix_argument(TO_REC709)]
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
