"""Deterministic 2D Grid/Dots textures; sampled for the native image-map path."""
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import tempfile
import uuid

KINDS=('grid','dots')
def capture(layer, channel, color, is_color=True):
    kind=layer.type;pattern=channel(layer,'type','square')
    supported=('line','square','triangle','hexagon') if kind=='grid' else ('square','triangle','hexagon')
    if pattern not in supported:raise ValueError(kind+' '+str(pattern)+' needs a 3D procedural evaluator')
    data={'kind':kind,'pattern':pattern,'width':float(channel(layer,'lineWidth' if kind=='grid' else 'dotWidth',.1)),
          'transition':float(channel(layer,'transWidth',0)), 'bias':float(channel(layer,'bias',.5)), 'gain':float(channel(layer,'gain',.5)),
          'color1':color(layer,'color1',(0,0,0)) if is_color else [float(channel(layer,'value1',0))]*3,
          'color2':color(layer,'color2',(1,1,1)) if is_color else [float(channel(layer,'value2',1))]*3,
          'alpha1':float(channel(layer,'alpha1',1)), 'alpha2':float(channel(layer,'alpha2',1))}
    if not all(math.isfinite(v) for k,v in data.items() if isinstance(v,(int,float))):raise ValueError('Nonfinite procedural parameter')
    return data

def _bias(x,b):
    b=max(.00001,min(.99999,b));x=max(0,min(1,x))
    return x/((1/b-2)*(1-x)+1)

def sample(data,u,v):
    # Unit cells repeat seamlessly; rows use a triangular lattice when requested.
    pattern=data['pattern'];x=u-math.floor(u);y=v-math.floor(v)
    if pattern in ('triangle','hexagon'):
        y=v*2;row=math.floor(y);y-=row;x=(u-.5*(row%2))%1
    dx=abs(x-.5);dy=abs(y-.5)
    if data['kind']=='dots':distance=math.hypot(dx,dy)
    elif pattern=='line':distance=min(x,1-x)
    elif pattern=='triangle':distance=min(min(y,1-y)*.5,abs((x+y*.5)%1-.5),abs((x-y*.5)%1-.5))
    elif pattern=='hexagon':distance=abs(max(dx,dx*.5+dy*.75)-.5)
    else:distance=min(x,1-x,y,1-y)
    radius=max(0,min(1,data['width']))*.5;transition=max(0,data['transition'])*.5
    t=(1.0 if distance<=radius else 0.0) if transition<=1e-9 else max(0,min(1,(radius+transition-distance)/(2*transition)))
    t=t*t*(3-2*t);t=_bias(t,data['bias'])
    g=data['gain'];t=.5*_bias(2*t,1-g) if t<.5 else 1-.5*_bias(2-2*t,1-g)
    return ([b+(a-b)*t for a,b in zip(data['color1'],data['color2'])], max(0,min(1,data['alpha2']+(data['alpha1']-data['alpha2'])*t)))

def bake(data,resolution=512):
    key=hashlib.sha256(json.dumps(['procedural-v1',resolution,data],sort_keys=True).encode()).hexdigest()
    root=Path(os.environ.get('LOCALAPPDATA',tempfile.gettempdir()))/'MoonRayForModo/Procedurals';root.mkdir(parents=True,exist_ok=True)
    paths=[root/(key+suffix+'.pfm') for suffix in ('','-alpha')]
    if not all(p.is_file() for p in paths):
        temporary=[p.with_name(p.name+'.'+uuid.uuid4().hex+'.tmp') for p in paths]
        try:
            with temporary[0].open('wb') as rgb,temporary[1].open('wb') as alpha:
                header=('PF\n%d %d\n-1.0\n'%(resolution,resolution)).encode();rgb.write(header);alpha.write(header)
                for y in range(resolution):
                    for x in range(resolution):
                        c,a=sample(data,(x+.5)/resolution,(y+.5)/resolution)
                        rgb.write(struct.pack('<3f',*c));alpha.write(struct.pack('<3f',a,a,a))
            for src,dst in zip(temporary,paths):src.replace(dst)
        finally:
            for p in temporary:
                if p.exists():p.unlink()
    return paths
