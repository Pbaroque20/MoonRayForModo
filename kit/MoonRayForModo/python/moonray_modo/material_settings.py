"""Validation for scene-owned MoonShine controls (no host dependencies)."""
import math

DEFAULTS = {'subsurface_model':0, 'anisotropy_angle':0.0,
            'sss_input_normal':False, 'sss_resolve_self_intersections':True}


def validate(key, value):
    if key not in DEFAULTS:
        raise ValueError('Unknown MoonShine material control: '+key)
    if type(DEFAULTS[key]) is bool:
        if value not in (False,True,0,1):
            raise ValueError(key+' must be a boolean')
        return bool(value)
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(key+' must be finite')
    if key == 'subsurface_model':
        if number not in (0,1,2):
            raise ValueError('Choose Normalized Diffusion, Dipole, or Random Walk')
        return int(number)
    return number


def values(settings):
    return {key:validate(key,settings.get(key,default)) for key,default in DEFAULTS.items()}
