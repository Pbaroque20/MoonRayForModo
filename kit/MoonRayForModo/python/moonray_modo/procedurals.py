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


# ---- In three dimensions, at render time (MoonRay's ModoProceduralMap) ----------------------------------------------
# The patterns as native-port/maps/ModoProcedural/modo_patterns.h numbers them, the options of their Type, and the
# settings each reads, in the order the map takes them (setting_a to setting_f), with what Modo starts them at.
PATTERNS = {'noise': 0, 'cellular': 1, 'checker': 2, 'grid': 3, 'dots': 4, 'wood': 5, 'weave': 6, 'ripples': 7}
TYPES = {'noise': ('simple', 'fractal', 'turbulence'), 'cellular': ('round', 'angular'), 'checker': ('square', 'cube'),
         'grid': ('line', 'triangle', 'square', 'hexagon', 'cube'), 'dots': ('square', 'hexagon', 'cube')}
MAP_SETTINGS = {'noise': (('freqs', 4), ('freqRatio', 2.0), ('ampRatio', .5)),
                'cellular': (('cellWidth', .6), ('transWidth', .3), ('freqs', 1), ('freqRatio', 2.0), ('ampRatio', .5), ('variation', 0.0)),
                'checker': (('transWidth', .1),), 'grid': (('lineWidth', .1), ('transWidth', .1)), 'dots': (('dotWidth', .8), ('transWidth', .1)),
                'wood': (('ringScale', .25), ('wave', .5), ('waveScale', 1.0), ('grain', .5), ('grainScale', .1)),
                'weave': (('yarnWidth', .6), ('roundness', .6)), 'ripples': (('sources', 8), ('wavelength', .2), ('phase', 0.0))}


def solid(layer, channel, color, is_color, locator_matrix):
    """A procedural layer as MoonRay's ModoProceduralMap works it out, through the object at each point (Modo's Solid
    projection): its pattern, Type and settings, its colours, and rows that take a point of the world into the texture
    locator's space. None for a layer of a kind it does not draw."""
    kind = layer.type
    if kind in ENHANCE:
        return enhance(layer, channel, color, is_color, locator_matrix)
    if kind not in PATTERNS:
        return None
    from .coordinates import inverse
    types = TYPES.get(kind, ())
    chosen = str(channel(layer, 'type', types[0] if types else ''))
    settings = [float(channel(layer, key, default)) for key, default in MAP_SETTINGS[kind]]
    inv = inverse(locator_matrix)
    data = {'pattern': PATTERNS[kind], 'type': types.index(chosen) if chosen in types else 0,
            'settings': settings + [0.0] * (22 - len(settings)) + [float(channel(layer, 'bias', .5)), float(channel(layer, 'gain', .5))],
            'color1': color(layer, 'color1', (0, 0, 0)) if is_color else [float(channel(layer, 'value1', 0))] * 3,
            'color2': color(layer, 'color2', (1, 1, 1)) if is_color else [float(channel(layer, 'value2', 1))] * 3,
            'alpha1': float(channel(layer, 'alpha1', 1)), 'alpha2': float(channel(layer, 'alpha2', 1)),
            'rows': [[inv[0], inv[4], inv[8], inv[12]], [inv[1], inv[5], inv[9], inv[13]], [inv[2], inv[6], inv[10], inv[14]]]}
    if not all(math.isfinite(v) for v in data['settings'] + [v for row in data['rows'] for v in row]):
        raise ValueError('Nonfinite procedural parameter')
    return data


def map_available():
    """Whether the MoonRay runtime has ModoProceduralMap; an older one is given the patterns baked as before."""
    try:
        from . import native
        return (Path(native.default_runtime()) / 'ModoProceduralMap.so').is_file()
    except Exception:
        return False


# ---- Enhance: Modo's patterns (the val.*.RJJ texture layers) -------------------------------------------------------
# Each: its number in modo_patterns.h, the channel that is its Type (its Noise Type, mostly), and its own settings in
# the order the pattern reads them. Choices among words are given as their place in the list Modo gives.
NOISE_TYPES = ('Perlin', 'EnhancedPerlin', 'Gradient', 'Value', 'GradientValue', 'Impulse', 'Lattice', 'Bubble')
CHOICES = {'AxisType': ('XAxis', 'YAxis', 'ZAxis'), 'FlowType': ('Flat', 'Square', 'Inverse'), 'NoiseType': NOISE_TYPES,
           'CellOrder': ('F1', 'F2', 'F3', 'F4'), 'Shape': ('Spheres', 'Cubes', 'Diamonds')}
_FBM = ('NoiseSeed', 'Octaves', 'Frequency', 'Increment', 'Absolute', 'Lower', 'Upper')
ENHANCE = {
    'val.Noise_Agate.RJJ': (100, 'NoiseType', ('NoiseSeed', 'Absolute', 'Lower', 'Upper')),
    'val.Noise_Bozo.RJJ': (101, 'NoiseType', _FBM),
    'val.Noise_Cruddy.RJJ': (102, 'NoiseType', ('NoiseSeed', 'Frequency', 'Magnitude', 'Lower', 'Upper')),
    'val.Noise_Dented.RJJ': (103, 'NoiseType', ('NoiseSeed', 'Octaves', 'Dentedness', 'Lower', 'Upper')),
    'val.Noise_Etched.RJJ': (104, 'NoiseType', ('NoiseSeed', 'Octaves', 'Corrosion', 'Lower', 'Upper')),
    'val.Noise_FlowBozo.RJJ': (105, 'FlowType', ('NoiseSeed', 'Octaves', 'Advection', 'Time', 'Absolute', 'Lower', 'Upper')),
    'val.Noise_Granite.RJJ': (106, 'NoiseType', ('NoiseSeed', 'Octaves', 'Frequency', 'Fold', 'Lower', 'Upper')),
    'val.Noise_Hybrid.RJJ': (107, 'NoiseType', ('NoiseSeed', 'Octaves', 'Frequency', 'Increment', 'Offset', 'Heterogeneous', 'Lower', 'Upper')),
    'val.Noise_Lump.RJJ': (108, 'NoiseType', ('NoiseSeed', 'Octaves', 'Frequency', 'Lower', 'Upper')),
    'val.Noise_MarbleNoise.RJJ': (109, 'NoiseType', ('NoiseSeed', 'Octaves', 'Frequency', 'Increment', 'Lower', 'Upper')),
    'val.Noise_MarbleVein.RJJ': (110, 'NoiseType', ('NoiseSeed', 'Octaves', 'Frequency', 'Increment', 'Sharpness', 'Lower', 'Upper')),
    'val.Noise_MultiFractal.RJJ': (111, 'NoiseType', ('NoiseSeed', 'Octaves', 'Frequency', 'Increment', 'Offset', 'Lower', 'Upper')),
    'val.Noise_Pebbles.RJJ': (112, 'NoiseType', ('NoiseSeed', 'MinFreq', 'MaxFreq', 'Steps', 'Magnitude', 'Frequency', 'Lower', 'Upper')),
    'val.Noise_PuffyClouds.RJJ': (113, 'NoiseType', ('NoiseSeed', 'Octaves', 'Frequency', 'Increment', 'Coverage', 'Heterogeneous', 'Lower', 'Upper')),
    'val.Noise_Ridged.RJJ': (114, 'NoiseType', ('NoiseSeed', 'Octaves', 'Frequency', 'Increment', 'Offset', 'Threshold', 'Lower', 'Upper')),
    'val.Noise_Scar.RJJ': (115, 'NoiseType', ('NoiseSeed', 'Octaves', 'Frequency', 'Increment', 'Lower', 'Upper')),
    'val.Noise_Scruffed.RJJ': (116, 'NoiseType', ('NoiseSeed', 'Length', 'Coverage', 'AxisType', 'Lower', 'Upper')),
    'val.Noise_Strata.RJJ': (117, 'NoiseType', ('NoiseSeed', 'Octaves', 'Frequency', 'Increment', 'Width', 'Magnitude', 'AxisType', 'Lower', 'Upper')),
    'val.Noise_Stucco.RJJ': (118, 'NoiseType', ('NoiseSeed', 'Octaves', 'Frequency', 'Increment', 'Power', 'Lower', 'Upper')),
    'val.Noise_VectorBozo.RJJ': (119, 'NoiseType', ('NoiseSeed', 'Octaves', 'Frequency', 'Magnitude', 'Fractalize', 'Lower', 'Upper')),
    'val.Noise_WrappedfBm.RJJ': (120, 'NoiseType', ('NoiseSeed', 'Octaves', 'Frequency', 'Magnitude', 'Lower', 'Upper')),
    'val.Noise_fBm.RJJ': (121, 'NoiseType', _FBM),
    # The Organic family, 130 on.
    'val.Organic_ArtDeco.RJJ': (130, None, ('Seed', 'Octaves', 'Frequency', 'Increment', 'Power', 'Lower', 'Upper', 'Regions')),
    'val.Organic_Blister.RJJ': (131, None, ('Levels', 'Lower', 'Upper')),
    'val.Organic_Branches.RJJ': (132, 'NoiseType', ('Branches', 'Width', 'Seed', 'Octaves', 'Magnitude', 'Scale', 'Detail', 'Full3D', 'Lower', 'Upper')),
    'val.Organic_Caustic.RJJ': (133, 'NoiseType', ('Seed', 'Octaves', 'Frequency', 'Increment', 'Lower', 'Upper')),
    'val.Organic_Cellular.RJJ': (134, 'CellOrder', ('Seed', 'Octaves', 'Frequency', 'Increment', 'Fractalize', 'Lower', 'Upper', 'Regions')),
    'val.Organic_Cheesy.RJJ': (135, 'CellOrder', ('Seed', 'Octaves', 'Frequency', 'Increment', 'Lower', 'Upper', 'Regions')),
    'val.Organic_Concrete.RJJ': (136, 'NoiseType', ('Seed', 'Lower', 'Upper')),
    'val.Organic_Crackle.RJJ': (137, None, ('Seed', 'Octaves', 'Frequency', 'Increment', 'Fractalize', 'Lower', 'Upper', 'Regions')),
    'val.Organic_Dirt.RJJ': (138, 'NoiseType', ('Seed', 'Frequency1', 'Magnitude1', 'Frequency2', 'Magnitude2', 'Lower', 'Upper')),
    'val.Organic_Disturbed.RJJ': (139, 'NoiseType', ('Seed', 'Distance', 'Frequency', 'Angle', 'Lower', 'Upper')),
    'val.Organic_EasyWood.RJJ': (140, 'NoiseType', ('Seed', 'Octaves', 'Magnitude', 'Scale', 'Detail', 'Lower', 'Upper')),
    'val.Organic_Electric.RJJ': (141, 'NoiseType', ('Seed', 'Octaves', 'Frequency', 'Increment', 'Width', 'Lower', 'Upper')),
    'val.Organic_Fire.RJJ': (142, 'NoiseType', ('Seed', 'FlameHeight', 'Magnitude', 'Fragmentation', 'Detail', 'Speed', 'Time', 'Lower', 'Upper')),
    'val.Organic_FireWall.RJJ': (143, 'NoiseType', ('Seed', 'Octaves', 'Frequency', 'Increment', 'Height', 'Lower', 'Upper')),
    'val.Organic_HardWood.RJJ': (144, 'NoiseType', ('Seed', 'Graininess', 'Ringiness', 'Lower', 'Upper')),
    'val.Organic_Membrane.RJJ': (145, None, ('Seed', 'Octaves', 'Frequency', 'Increment', 'Jitter', 'Grout', 'Bevel', 'Lower', 'Upper')),
    'val.Organic_Minky.RJJ': (146, 'CellOrder', ('Seed', 'Octaves', 'Frequency', 'Increment', 'Power', 'Lower', 'Upper', 'Regions')),
    'val.Organic_Scatter.RJJ': (147, 'Shape', ('Seed', 'Distrib', 'Spread', 'Scale', 'Smooth', 'Lower', 'Upper')),
    'val.Organic_SinBlob.RJJ': (148, None, ('Seed', 'Lower', 'Upper')),
    'val.Organic_Veins.RJJ': (149, 'NoiseType', ('Seed', 'Octaves', 'Veininess', 'Lower', 'Upper')),
    'val.Organic_Wires.RJJ': (150, None, ('Seed', 'Octaves', 'Frequency', 'Increment', 'Jitter', 'Grout', 'Bevel', 'Lower', 'Upper')),
    'val.Organic_WormVein.RJJ': (151, 'NoiseType', ('Seed', 'Lo', 'Hi', 'Lower', 'Upper')),
}


def _setting(layer, channel, name):
    value = channel(layer, name, 0)
    if isinstance(value, str):
        options = CHOICES.get(name, ())
        return float(options.index(value)) if value in options else 0.0
    return float(value)


def enhance(layer, channel, color, is_color, locator_matrix):
    """An Enhance: Modo texture as ModoProceduralMap draws it: its pattern, its Noise Type (or other Type), its
    settings, its Fore and Back colours as the pattern's two (a side set to show the layer beneath it having no
    alpha), its Bias and Gain, and the placement into its locator's space."""
    from .coordinates import inverse
    pattern, kind, names = ENHANCE[layer.type]
    chosen = channel(layer, kind, '') if kind else ''
    options = CHOICES.get(kind, NOISE_TYPES) if kind else ()
    settings = [_setting(layer, channel, name) for name in names]
    if len(settings) > 22:
        raise ValueError('Too many settings for the procedural map')

    def side(prefix):
        if is_color:
            value = color(layer, prefix + 'GroundColor', (0, 0, 0) if prefix == 'Back' else (1, 1, 1))
        else:
            value = [float(channel(layer, prefix + 'Value', 0 if prefix == 'Back' else 1))] * 3
        alpha = 0.0 if channel(layer, prefix + 'Prev', 0) else float(channel(layer, prefix + 'Alpha', 1))
        return value, alpha
    fore, fore_alpha = side('Fore')
    back, back_alpha = side('Back')
    inv = inverse(locator_matrix)
    data = {'pattern': pattern, 'type': options.index(chosen) if chosen in options else 0,
            'settings': settings + [0.0] * (22 - len(settings)) + [float(channel(layer, 'Bias', .5)), float(channel(layer, 'Gain', .5))],
            'color1': fore, 'color2': back, 'alpha1': fore_alpha, 'alpha2': back_alpha,
            'rows': [[inv[0], inv[4], inv[8], inv[12]], [inv[1], inv[5], inv[9], inv[13]], [inv[2], inv[6], inv[10], inv[14]]]}
    if not all(math.isfinite(v) for v in data['settings'] + [v for row in data['rows'] for v in row]):
        raise ValueError('Nonfinite procedural parameter')
    return data

