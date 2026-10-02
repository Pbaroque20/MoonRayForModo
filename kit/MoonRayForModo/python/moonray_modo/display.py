"""Display transforms only; rendering, texture inputs and saved EXRs stay linear."""
import math
from pathlib import Path

DEFAULTS={'view':'reinhard','exposure':0.0,'lut':'','lut_space':'display',
          'config':'','source':'Linear Rec.709 (sRGB)','display':'sRGB','ocio_view':'ACES 1.0 - SDR Video'}


def values(settings):
    result={key:settings.get(key,value) for key,value in DEFAULTS.items()}
    if result['view'] not in ('srgb','reinhard','raw','ocio'): raise ValueError('Unknown display transform')
    if result['lut_space'] not in ('linear','display'): raise ValueError('Unknown LUT placement')
    result['exposure']=float(result['exposure'])
    if not math.isfinite(result['exposure']) or not -20<=result['exposure']<=20: raise ValueError('Exposure must be between -20 and 20 stops')
    for key in ('lut','config','source','display','ocio_view'):
        if not isinstance(result[key],str): raise ValueError('Invalid display setting: '+key)
    return result


def arguments(settings):
    v=values(settings)
    for key in ('lut','config'):
        if v[key] and not Path(v[key]).is_file(): raise ValueError('Missing '+key+' file: '+v[key])
    args=['--mulc',str(2.0**v['exposure'])]
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
