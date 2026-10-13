"""Deterministic 2D procedural textures (Grid, Dots, Cellular, Wood, Weave, Ripples), sampled into an image that
repeats without a seam and rendered as an image map. Each is after Modo's pattern and its settings, in two
dimensions: it is not Modo's own evaluation, and a pattern Modo works out through a solid is laid on by UV here."""
import functools
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import tempfile
import uuid

KINDS=('grid','dots','cellular','wood','weave','ripples')
# What each of the later patterns reads from its layer, with what Modo starts it at.
EXTRA={'cellular':(('type','angular'),('cellWidth',.6),('transWidth',.3),('freqs',1),('freqRatio',2.0),('ampRatio',.5),('variation',0.0)),
       'wood':(('ringScale',.25),('wave',.5),('waveScale',1.0),('grain',.5),('grainScale',.1)),
       'weave':(('yarnWidth',.6),('roundness',.6)),
       'ripples':(('sources',8),('wavelength',.2),('phase',0.0))}
def capture(layer, channel, color, is_color=True):
    kind=layer.type
    if kind in EXTRA:
        data={'kind':kind,'pattern':'','bias':float(channel(layer,'bias',.5)),'gain':float(channel(layer,'gain',.5)),
              'color1':color(layer,'color1',(0,0,0)) if is_color else [float(channel(layer,'value1',0))]*3,
              'color2':color(layer,'color2',(1,1,1)) if is_color else [float(channel(layer,'value2',1))]*3,
              'alpha1':float(channel(layer,'alpha1',1)), 'alpha2':float(channel(layer,'alpha2',1))}
        for key,default in EXTRA[kind]:
            value=channel(layer,key,default)
            data[key]=str(value) if isinstance(default,str) else int(value) if isinstance(default,int) else float(value)
        if not all(math.isfinite(v) for v in data.values() if isinstance(v,(int,float))):raise ValueError('Nonfinite procedural parameter')
        return data
    pattern=channel(layer,'type','square')
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

@functools.lru_cache(maxsize=131072)
def _chance(*whole):
    """A number from 0 to 1 that is always the same for the same whole numbers."""
    return int.from_bytes(hashlib.blake2b(struct.pack('<%dq'%len(whole),*whole),digest_size=4).digest(),'little')/4294967295.0

def _noise(x,y,period,seed=0,period_y=None):
    """Smooth noise from 0 to 1 that repeats every period whole steps across, and every period_y up (the same unless given)."""
    period_y=period_y or period
    x0,y0=math.floor(x),math.floor(y);fx,fy=x-x0,y-y0
    fx=fx*fx*(3-2*fx);fy=fy*fy*(3-2*fy)
    at=lambda i,j:_chance(int(i)%period,int(j)%period_y,seed)
    low=at(x0,y0)*(1-fx)+at(x0+1,y0)*fx;high=at(x0,y0+1)*(1-fx)+at(x0+1,y0+1)*fx
    return low*(1-fy)+high*fy

def _step(value,edge,soft):
    """0 below an edge and 1 above it, easing between over soft either side."""
    if soft<=1e-9:return 1.0 if value>=edge else 0.0
    t=max(0.0,min(1.0,(value-edge+soft)/(2*soft)));return t*t*(3-2*t)

def _cells(u,v,count,round_,seed):
    """In a repeating field of count by count cells, each with a point in it: how far to the nearest point's
    cell edge (or, round, how near the point itself), in cells, and which cell that is."""
    x,y=u*count,v*count;cx,cy=math.floor(x),math.floor(y)
    first=second=9.0;nearest=(0,0)
    for j in (-1,0,1):
        for i in (-1,0,1):
            a,b=int(cx+i),int(cy+j)
            px=a+.15+.7*_chance(a%count,b%count,seed);py=b+.15+.7*_chance(a%count,b%count,seed+1)
            d=math.hypot(x-px,y-py)
            if d<first:second=first;first=d;nearest=(a%count,b%count)
            elif d<second:second=d
    return (first if round_ else .5*(second-first)),nearest

def _late(data,u,v):
    """How much of the first colour there is, 0 to 1, for the patterns that are not Grid or Dots."""
    kind=data['kind'];u-=math.floor(u);v-=math.floor(v)
    if kind=='cellular':
        round_=data.get('type')=='round';width=max(0.0,min(1.0,data['cellWidth']));soft=.25*max(0.0,data['transWidth'])
        total=weight=0.0;amplitude=1.0;count=4
        for octave in range(max(1,min(4,int(data['freqs'])))):
            distance,cell=_cells(u,v,count,round_,7*octave)
            # Round: within the cell's width of its point. Angular: further than the gap from the cell's edge.
            inside=_step(.5*width-distance,0.0,soft) if round_ else _step(distance,.5*(1-width),soft)
            inside*=1-max(0.0,min(1.0,data['variation']))*_chance(cell[0],cell[1],13+octave)
            total+=inside*amplitude;weight+=amplitude
            amplitude*=max(0.0,data['ampRatio']);count=max(count+1,int(round(count*max(1.0,data['freqRatio']))))
        return total/weight if weight else 0.0
    if kind=='wood':
        # Rings cut along the plank: bands across u, bent by a slow wander and roughened by a fine grain along v.
        rings=max(1,int(round(1/max(.02,data['ringScale']))));slow=max(1,int(round(2*max(.1,data['waveScale']))))
        wander=(_noise(u*slow,v*slow,slow,3)-.5)*2*max(0.0,data['wave'])
        ring=u*rings+wander;ring-=math.floor(ring)
        # Dark at the start of a ring, easing to light across it, as a year's growth does.
        t=1-ring**.6
        fine=max(4,int(round(4/max(.02,data['grainScale']))))
        t+=(_noise(u*fine,v*max(2,fine//8),fine,5,max(2,fine//8))-.5)*max(0.0,data['grain'])*.6
        return max(0.0,min(1.0,t))
    if kind=='weave':
        # Yarns over and under by turns: four each way to a tile. Each is highest along its middle and where it
        # passes over, and dips at its edges and where it goes under.
        x,y=u*4,v*4;cx,cy=math.floor(x),math.floor(y);fx,fy=x-cx,y-cy
        width=max(.05,min(1.0,data['yarnWidth']));across=(int(cx)+int(cy))%2==0
        along,side=(fx,fy) if across else (fy,fx)
        off=abs(side-.5)
        if off>.5*width:return 0.0
        profile=math.cos(math.pi*off/width);arch=math.sin(math.pi*along)
        roundness=max(0.0,min(1.0,data['roundness']))
        return max(0.0,min(1.0,(1-roundness)+roundness*profile*(.5+.5*arch)))
    # Ripples: rings spreading from several points, their crests and troughs added up.
    sources=max(1,min(64,int(data['sources'])));length=max(.01,data['wavelength']);total=0.0
    for index in range(sources):
        dx=abs(u-_chance(index,17));dy=abs(v-_chance(index,29))
        # The nearer way round, so that the rings meet themselves across the tile's edges.
        distance=math.hypot(min(dx,1-dx),min(dy,1-dy))
        total+=math.cos(2*math.pi*(distance/length-data['phase']))
    return max(0.0,min(1.0,.5+.5*total/math.sqrt(sources)))

def sample(data,u,v):
    if data['kind'] in EXTRA:
        t=_bias(_late(data,u,v),data['bias'])
        g=data['gain'];t=.5*_bias(2*t,1-g) if t<.5 else 1-.5*_bias(2-2*t,1-g)
        low,high=sorted((data['alpha1'],data['alpha2']))
        alpha=min(high,max(low,data['alpha1']*t+data['alpha2']*(1-t)))
        return ([a*t+b*(1-t) for a,b in zip(data['color1'],data['color2'])], max(0,min(1,alpha)))
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
    # Blended as shares of each end, so that the ends come out as they were given: written as one end plus a
    # step toward the other, 0.8 + (0.2 - 0.8) is a hair under 0.2, outside the range the pattern was asked for.
    low,high=sorted((data['alpha1'],data['alpha2']))
    alpha=min(high,max(low,data['alpha1']*t+data['alpha2']*(1-t)))
    return ([a*t+b*(1-t) for a,b in zip(data['color1'],data['color2'])], max(0,min(1,alpha)))

def bake(data,resolution=512):
    # The later patterns take longer to work out and are sampled a little coarser.
    if data.get('kind') in EXTRA:resolution=min(resolution,256)
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
