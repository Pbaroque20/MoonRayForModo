"""Read evaluated Modo gradients without changing channels or selection.

Only bounded scalar surface inputs are supported here. Their 0..1 domain is
sampled from the host's filter stack, including animated gradient modifiers.
Ray-dependent inputs must not be replaced with a constant surface value.
"""
import math

INPUTS={'driverA','driverB','driverC','driverD','diffAmt','specAmt','lumiAmt',
        'coatAmt','coatRough','diffRough','rough','metallic','tranAmt','tranRough',
        'subsAmt','aniso','bump','coatBump','dissolve','groupMask'}

def capture(layer,channel,is_color):
    from .textures import EFFECT_ALIASES
    import lx
    name=str(channel(layer,'param',''))
    source=EFFECT_ALIASES.get(name,name)
    if source not in INPUTS:
        raise ValueError('Gradient input '+name+' has no translated sample source')
    def reader(name,required=True):
        try:
            item_channel=layer.channel(name)
            if item_channel is None:
                if not required:return None
                raise ValueError('Missing gradient channel '+name)
            value=item_channel.get()
            if isinstance(value,(int,float)):
                if not math.isfinite(value):raise ValueError('Nonfinite gradient '+name)
                return lambda position:float(value)
            gradient=lx.object.GradientFilter(value)
            if not gradient.test():raise ValueError('Cannot read evaluated gradient '+name)
            return gradient.Generate
        except (RuntimeError,TypeError,AttributeError) as exc:
            raise ValueError('Cannot read evaluated gradient '+name+': '+str(exc)) from exc
    filters=[reader('color.'+axis) for axis in 'RGB'] if is_color else [reader('value')]
    alpha_filter=reader('color.A',required=False) if is_color else None
    positions=[i/256.0 for i in range(257)]
    colors=[]
    for position in positions:
        try:row=[float(f(position)) for f in filters]
        except (RuntimeError,TypeError,AttributeError) as exc:raise ValueError('Gradient evaluation failed: '+str(exc)) from exc
        if len(row)==1:row*=3
        if not all(math.isfinite(x) for x in row):raise ValueError('Nonfinite evaluated gradient')
        colors.append(row)
    data={'input':source,'positions':positions,'colors':colors}
    if alpha_filter is not None:
        try:alpha=[float(alpha_filter(x)) for x in positions]
        except (RuntimeError,TypeError,AttributeError) as exc:raise ValueError('Gradient alpha evaluation failed: '+str(exc)) from exc
        if not all(math.isfinite(x) for x in alpha):raise ValueError('Nonfinite gradient alpha')
        data['alpha']=[max(0,min(1,x)) for x in alpha]
    return data

RAMP_POINTS=20

def reduced(data):
    """The gradient as MoonRay's RampMap can hold it: at most 20 points, evenly spaced."""
    if len(data['positions'])<=RAMP_POINTS:return data
    positions=[i/(RAMP_POINTS-1) for i in range(RAMP_POINTS)]
    result=dict(data,positions=positions,colors=[sample(data,x) for x in positions])
    if 'alpha' in data:
        result['alpha']=[sample(dict(data,colors=[[a]*3 for a in data['alpha']]),x)[0] for x in positions]
    return result

def emit(data,current,node,rgb):
    from .rdla import array,number
    # RampMap refuses more points than this and the layer would render blank.
    data=reduced(data)
    source=data['input']
    if source not in current:raise ValueError('Missing gradient source '+source)
    signal=node('ModoTextureMap',{'mode':'7','component':'0','foreground':current[source]})
    return node('RampMap',{'ramp_type':'8','wrap_type':'1','color_space':'0',
        'input':signal,
        'positions':array([number(x) for x in data['positions']]),
        'colors':array([rgb(x) for x in data['colors']]),
        'interpolations':array(['1']*len(data['positions']))})


def sample(data,value):
    """Same clamped linear lookup as the emitted RampMap, for environments."""
    from bisect import bisect_right
    positions=data['positions'];colors=data['colors']
    right=bisect_right(positions,value)
    if right==0:return list(colors[0])
    if right==len(positions):return list(colors[-1])
    left=right-1;amount=(value-positions[left])/(positions[right]-positions[left])
    return [a+(b-a)*amount for a,b in zip(colors[left],colors[right])]
