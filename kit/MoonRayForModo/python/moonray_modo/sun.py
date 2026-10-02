"""Read the evaluated Modo physical-sun angles and linked sky source."""
import math


def direction(item):
    from .host import channel,world_matrix
    if channel(item,'sunPos',False) and not channel(item,'useWorldXfrm',False):
        azimuth=float(channel(item,'azimuth',0))+float(channel(item,'north',0))
        elevation=float(channel(item,'elevation',0))
        return [math.sin(azimuth)*math.cos(elevation),math.sin(elevation),math.cos(azimuth)*math.cos(elevation)]
    matrix=world_matrix(item)
    return [-v for v in matrix[8:11]]


def matrix(item):
    from .host import world_matrix
    toward=direction(item)
    length=math.sqrt(sum(v*v for v in toward))
    if length<=0 or not math.isfinite(length): raise ValueError('Invalid physical sun direction')
    z=[-v/length for v in toward]
    up=[0,1,0] if abs(z[1])<.999 else [1,0,0]
    x=[up[1]*z[2]-up[2]*z[1],up[2]*z[0]-up[0]*z[2],up[0]*z[1]-up[1]*z[0]]
    length=math.sqrt(sum(v*v for v in x));x=[v/length for v in x]
    y=[z[1]*x[2]-z[2]*x[1],z[2]*x[0]-z[0]*x[2],z[0]*x[1]-z[1]*x[0]]
    result=world_matrix(item);result[:12]=x+[0]+y+[0]+z+[0]
    return result
