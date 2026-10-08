"""Read the evaluated Modo physical-sun angles and linked sky source."""
import math


def physical(item):
    """The colour and strength of a sun placed by date and time, which Modo works out itself; None for any other light."""
    from .host import channel
    from .daylight import sun_light
    if not channel(item,'sunPos',False):return None
    toward=direction(item);length=math.sqrt(sum(v*v for v in toward))
    if length<=0:return None
    elevation=math.degrees(math.asin(max(-1.0,min(1.0,toward[1]/length))))
    tint,strength=sun_light(elevation,float(channel(item,'haze',2.0)),bool(channel(item,'thinning',True)),float(channel(item,'gamma',2.2)),
                            str(channel(item,'clamp','clamp')),float(channel(item,'radiance',3.0)))
    # Modo's strength is what falls on a surface; a white surface under a MoonRay distant light of 1 shows 1,
    # which is pi times that. The sky is in Modo's units, so the sun must be too.
    return tint,strength/math.pi


def direction(item):
    from .host import channel,world_matrix
    if channel(item,'sunPos',False) and not channel(item,'useWorldXfrm',False):
        azimuth=float(channel(item,'azimuth',0))+float(channel(item,'north',0))
        elevation=float(channel(item,'elevation',0))
        return [math.sin(azimuth)*math.cos(elevation),math.sin(elevation),math.cos(azimuth)*math.cos(elevation)]
    # A light shines along its -Z, so its +Z is where the sun stands.
    matrix=world_matrix(item)
    return list(matrix[8:11])


def matrix(item):
    from .host import world_matrix
    toward=direction(item)
    length=math.sqrt(sum(v*v for v in toward))
    if length<=0 or not math.isfinite(length): raise ValueError('Invalid physical sun direction')
    z=[v/length for v in toward]
    up=[0,1,0] if abs(z[1])<.999 else [1,0,0]
    x=[up[1]*z[2]-up[2]*z[1],up[2]*z[0]-up[0]*z[2],up[0]*z[1]-up[1]*z[0]]
    length=math.sqrt(sum(v*v for v in x));x=[v/length for v in x]
    y=[z[1]*x[2]-z[2]*x[1],z[2]*x[0]-z[0]*x[2],z[0]*x[1]-z[1]*x[0]]
    result=world_matrix(item);result[:12]=x+[0]+y+[0]+z+[0]
    return result
