"""Normalize Modo channel values without discarding vector components."""
import math


def rgb(value, name):
    components=value if isinstance(value,(tuple,list)) else [value]*3
    if len(components)!=3:
        raise ValueError(name+' must contain three RGB components')
    try:
        result=[float(component) for component in components]
    except (TypeError,ValueError) as exc:
        raise ValueError(name+' must contain numeric RGB components') from exc
    if not all(math.isfinite(component) for component in result):
        raise ValueError(name+' must contain finite RGB components')
    return result


def fresnel_controls(settings, specular_amount, reflection_amount, specular_fresnel, reflection_fresnel):
    # Native shaders use the inspector's own IOR/Fresnel parameters.
    if settings.get('native_shader'):
        return []
    return [name for name,amount,value in (
        ('Specular Fresnel',specular_amount,specular_fresnel),
        ('Reflection Fresnel',reflection_amount,reflection_fresnel))
        if amount>0 and not math.isclose(value,1.0,rel_tol=0,abs_tol=1e-6)]
