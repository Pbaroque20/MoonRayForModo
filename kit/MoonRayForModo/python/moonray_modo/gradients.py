"""Read evaluated Modo gradients without changing channels or selection.

Only bounded scalar surface inputs are supported here. Their 0..1 domain is
sampled from the host's filter stack, including animated gradient modifiers.
Ray-dependent inputs must not be replaced with a constant surface value.
"""
import math

INPUTS={'driverA','driverB','driverC','driverD','diffAmt','specAmt','lumiAmt',
        'coatAmt','coatRough','diffRough','rough','metallic','tranAmt','tranRough',
        'subsAmt','aniso','bump','coatBump','dissolve','groupMask'}

# Modo's Sample and Surface Parameters a Gradient may run over, each worked out at the point being shaded (emit, and
# MoonLightIPR's kernel), as measured against Modo's renders (tools/probe_gui_gradient_inputs.py): the incidences are
# 1 less the cosine of the angle (to the camera, or to the layer's locator), the slope the angle from up in radians,
# distances in the scene's units, the screen's place 0 to 1 across. Each with the span its values are sampled over
# where the gradient's own keys do not say (SPANS); None: found from where the gradient changes.
SAMPLED={'incidenceAngle':(0.0,2.0),'incidenceNobump':(0.0,2.0),'locatorIncAngle':(0.0,2.0),'slope':(0.0,math.pi),
         'slopeUndisplaced':(0.0,math.pi),'cameraDistance':None,'screenX':(0.0,1.0),'screenY':(0.0,1.0),'screenR':(0.0,2.0),
         'distance':None,'distanceX':None,'distanceY':None,'distanceZ':None,'objDistance':None,'objDistanceX':None,
         'objDistanceY':None,'objDistanceZ':None,'backFacing':(0.0,1.0)}


# Texture U and V: which coordinate of the layer's UV map.
TEXTURE_UV={'textureU':0,'textureV':1}

# Bump and Displacement Height: the Bump or Displacement value the layers beneath give, not scaled by the material's bump
# amplitude or displacement distance, as measured against Modo's renders (tools/probe_gui_gradient_heights.py): read as
# the Gradient reads those channels.
HEIGHTS={'bumpHeight':'bump','displaceHeight':'displace'}

# Inputs Modo's renders read as one number on every visible surface (tools/probe_gui_gradient_clip.py): Clip Distance 0,
# with the camera's clipping on or off. The gradient is held at that number.
HELD={'clipDist':0.0}


def texture_projection(layer,channel,axis):
    """How a Gradient on Texture U (axis 0) or V (1) reads its coordinate, as measured against Modo's renders
    (tools/probe_gui_gradient_uv.py): ('uv', the UV map's name), the map's own coordinate; or ('local', locator place,
    the locator's axis over its length squared, wrapped), the point's coordinate in the texture locator's space along
    that axis: as it is under the default projection (Solid), plus a half and wrapped to 0..1 under Planar along Z."""
    locator=next((i for i in layer.itemGraph('shadeLoc').forward() if i.type=='txtrLocator'),None)
    if locator is None:raise ValueError("Texture U and V need the layer's texture locator")
    projection=channel(locator,'projType','uv')
    if projection=='uv':
        name=str(channel(locator,'uvMap','') or '')
        if not name:raise ValueError('Texture U and V: choose a named UV map')
        return ('uv',name)
    if projection not in ('none','planar'):
        raise ValueError('Texture U and V are followed with UV map, Solid and Planar projections, not '+str(projection))
    if projection=='planar' and str(channel(locator,'projAxis',2)) not in ('2','z','Z'):
        raise ValueError('Texture U and V under a Planar projection are followed along Z only')
    from .host import world_matrix
    matrix=[float(v) for v in world_matrix(locator)]
    along=matrix[4*axis:4*axis+3]
    size=sum(v*v for v in along) or 1.0
    return ('local',matrix[12:15],[v/size for v in along],projection=='planar')


def locator_place(layer):
    """Where a texture layer's locator is in the world, [0, 0, 0] where it has none."""
    try:
        locator=next((i for i in layer.itemGraph('shadeLoc').forward() if i.type=='txtrLocator'),None)
        if locator is None:return [0.0,0.0,0.0]
        from .host import world_matrix
        matrix=world_matrix(locator)
        return [float(v) for v in matrix[12:15]]
    except Exception:
        return [0.0,0.0,0.0]


def changing_span(filters,low=0.0,high=1e5):
    """The span over which a gradient changes: (first, last) input where any of its curves differs from its ends, found by
    sampling ever further out; at least a unit wide."""
    points=sorted({0.0}|{s*10**e*k for e in range(-3,6) for k in (1,2,5) for s in (1,-1)})
    points=[x for x in points if low<=x<=high]
    values=[[float(f(x)) for f in filters] for x in points]
    moving=[i for i in range(1,len(points)) if any(abs(a-b)>1e-6 for a,b in zip(values[i],values[i-1]))]
    if not moving:return low,max(low+1.0,min(high,1.0))
    first,last=points[moving[0]-1],points[moving[-1]]
    return first,max(last,first+1e-3)

def capture(layer,channel,is_color):
    from .textures import EFFECT_ALIASES
    import lx
    name=str(channel(layer,'param',''))
    source=EFFECT_ALIASES.get(name,name)
    source=HEIGHTS.get(source,source)
    if (source not in INPUTS and source not in SAMPLED and source not in TEXTURE_UV and source not in HELD
            and source not in ('textureValue','surfaceID','displace')):
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
    span=None
    if source in SAMPLED:
        # Sampled over the input's span (its natural one, or where the gradient changes), positions 0..1 across it.
        span=SAMPLED[source] or changing_span(filters+([alpha_filter] if alpha_filter else []),0.0)
        low,high=span
        inputs=[low+(high-low)*x for x in positions]
    else:
        inputs=positions
    colors=[]
    for position in inputs:
        try:row=[float(f(position)) for f in filters]
        except (RuntimeError,TypeError,AttributeError) as exc:raise ValueError('Gradient evaluation failed: '+str(exc)) from exc
        if len(row)==1:row*=3
        if not all(math.isfinite(x) for x in row):raise ValueError('Nonfinite evaluated gradient')
        colors.append(row)
    data={'input':source,'positions':positions,'colors':colors}
    if source=='surfaceID':
        # Surface ID: a number from 0 to 1 for each item (Modo's own differ, from its own hash), as Variation by Item
        # gives it (occlusion.variation), through the gradient over 0..1.
        from .procedurals import VARIATION_MAP
        data.update(input='@vmap',vmap=VARIATION_MAP,label='Surface ID')
    if source in HELD:
        # One number everywhere: layers.py makes the layer a Constant of the gradient there.
        data.update(input='@held',held=HELD[source])
    if source=='textureValue':
        # The Value of the layer beneath (not its colour), 0..1: layers.py looks it up over a Constant beneath.
        data['input']='@texture_value'
    if source in TEXTURE_UV:
        # Texture U or V: the layer's UV map at each corner (texture_uv.apply), a weight over the span its keys change
        # in; or the point's place in the texture locator's space, worked out where it is shaded.
        reading=texture_projection(layer,channel,TEXTURE_UV[source])
        low,high=changing_span(filters+([alpha_filter] if alpha_filter else []),-1e5,1e5)
        if reading[0]=='local':
            low,high=(0.0,1.0) if reading[3] else (min(low,-1.0),max(high,1.0))
            inputs=[low+(high-low)*x for x in positions]
            colors=[[float(f(position)) for f in filters] for position in inputs]
            colors=[row*3 if len(row)==1 else row for row in colors]
            if not all(math.isfinite(x) for row in colors for x in row):raise ValueError('Nonfinite evaluated gradient')
            data={'input':'@sample','sample':'textureLocal','span':[low,high],'locator':reading[1],'positions':positions,
                  'colors':colors,'axis_vector':reading[2],'wrap':reading[3]}
            if alpha_filter is not None:
                data['alpha']=[max(0.0,min(1.0,float(alpha_filter(x)))) for x in inputs]
            return data
        uv_map=reading[1]
        low,high=min(low,0.0),max(high,1.0)
        inputs=[low+(high-low)*x for x in positions]
        colors=[[float(f(position)) for f in filters] for position in inputs]
        colors=[row*3 if len(row)==1 else row for row in colors]
        if not all(math.isfinite(x) for row in colors for x in row):raise ValueError('Nonfinite evaluated gradient')
        from .texture_uv import map_name
        data={'input':'@vmap','vmap':map_name(TEXTURE_UV[source],uv_map,low,high),'label':'Texture '+'UV'[TEXTURE_UV[source]],
              'positions':positions,'colors':colors,'texture':{'axis':TEXTURE_UV[source],'uv_map':uv_map,'low':low,'high':high}}
        if alpha_filter is not None:
            data['alpha']=[max(0.0,min(1.0,float(alpha_filter(x)))) for x in inputs]
        return data
    if span is not None:
        # The input's span the positions run over, and the layer's locator, which the distances and the locator's
        # incidence are measured from (its place in the world).
        data.update(input='@sample',sample=source,span=[float(span[0]),float(span[1])],locator=locator_place(layer))
    if alpha_filter is not None:
        try:alpha=[float(alpha_filter(x)) for x in inputs]
        except (RuntimeError,TypeError,AttributeError) as exc:raise ValueError('Gradient alpha evaluation failed: '+str(exc)) from exc
        if not all(math.isfinite(x) for x in alpha):raise ValueError('Nonfinite gradient alpha')
        data['alpha']=[max(0,min(1,x)) for x in alpha]
    return data

# MoonRay's RampMap takes 20 points, but what evaluates it (RampControl, RAMP_MAX_POINTS) keeps the first 10 and holds the
# last of those from there on.
RAMP_POINTS=10

def reduced(data):
    """The gradient as MoonRay's RampMap can hold it: at most 10 of its points, those it is furthest out without."""
    count=len(data['positions'])
    if count<=RAMP_POINTS:return data
    rows=[list(colour)+([data['alpha'][i]] if 'alpha' in data else []) for i,colour in enumerate(data['colors'])]
    places=data['positions']
    kept=[0,count-1]
    while len(kept)<RAMP_POINTS:
        worst,where=-1.0,None
        for left,right in zip(kept,kept[1:]):
            for i in range(left+1,right):
                amount=(places[i]-places[left])/(places[right]-places[left])
                off=max(abs(a+(b-a)*amount-c) for a,b,c in zip(rows[left],rows[right],rows[i]))
                if off>worst:worst,where=off,i
        if where is None or worst<=1e-6:break
        kept=sorted(kept+[where])
    result=dict(data,positions=[places[i] for i in kept],colors=[data['colors'][i] for i in kept])
    if 'alpha' in data:result['alpha']=[data['alpha'][i] for i in kept]
    return result

def emit(data,current,node,rgb):
    from .rdla import array,number,string
    # RampMap refuses more points than this and the layer would render blank.
    data=reduced(data)
    source=data['input']
    if source=='@curvature':
        # Modo's Curvature: MoonRay's CurvatureMap, 0.5 flat, turned so that a bulge reads towards 1.
        measured=node('CurvatureMap',{'mode':'2','scale':number(data.get('scale',1)),'power':'1'})
        signal=node('ModoTextureMap',{'background':rgb(1),'foreground':measured,'blend':'3'})
    elif source=='@vmap':
        # Modo's Weight Map Texture: the weight the shape carries under the map's name (vertex_maps). A mesh without the
        # map reads 0, its Low.
        weight=node('AttributeMap',{'primitive_attribute_name':string(data.get('vmap','')),'primitive_attribute_type':'0','default_value':'Rgb(0,0,0)'})
        signal=node('ModoTextureMap',{'mode':'7','component':'0','foreground':weight})
    elif source=='@sample':
        signal=sample_signal(data,node,rgb)
    elif source not in current:raise ValueError('Missing gradient source '+source)
    elif data.get('luminance'):
        # Enhance: Modo's EasyGrad: looked up by the brightness of its own channel beneath it.
        signal=node('OpMap',{'operation':'8','op1':current[source],'op2':rgb([0.2126,0.7152,0.0722])})
    else:signal=node('ModoTextureMap',{'mode':'7','component':'0','foreground':current[source]})
    return node('RampMap',{'ramp_type':'8','wrap_type':'1','color_space':'0',
        'input':signal,
        'positions':array([number(x) for x in data['positions']]),
        'colors':array([rgb(x) for x in data['colors']]),
        'interpolations':array(['1']*len(data['positions']))})


def sample_signal(data,node,rgb):
    """A Sample or Surface Parameter at the point being shaded, as MoonRay's maps make it, scaled from its span to 0..1
    (the RampMap's positions): see SAMPLED. AttributeMap gives the point, its normal and the way to the observer in render
    space; TransformSpaceMap takes them to the world, the camera or the screen; OpMap does the arithmetic."""
    kind=data['sample']
    locator=rgb([float(v) for v in data.get('locator',[0,0,0])])
    def op(operation,a,b=None):
        return node('OpMap',{'operation':operation,'op1':a,'op2':b if b is not None else rgb(0)})
    def moved(value,to_space,kind_of='0'):
        return node('TransformSpaceMap',{'input':value,'input_type':kind_of,'from_space':'0','to_space':to_space})
    point=node('AttributeMap',{'map_type':'1'})
    normal=node('AttributeMap',{'map_type':'3'})
    world_point=moved(point,'2')
    if kind in ('incidenceAngle','incidenceNobump'):
        # 1 less the cosine of the angle to the camera.
        value=op('1',rgb(1),op('8',normal,node('AttributeMap',{'map_type':'20'})))
    elif kind=='locatorIncAngle':
        # 1 less the cosine of the angle to the layer's locator.
        towards=op('10',op('1',locator,world_point))
        value=op('1',rgb(1),op('8',moved(normal,'2','2'),towards))
    elif kind in ('slope','slopeUndisplaced'):
        # The angle from up, in radians.
        value=op('24',op('8',moved(normal,'2','2'),rgb([0,1,0])))
    elif kind=='cameraDistance':
        value=op('20',moved(point,'1'))
    elif kind in ('screenX','screenY','screenR'):
        # MoonRay's screen space runs -1 to 1 across the picture: Modo's 0 to 1, and its R twice the distance from the
        # middle as a share of the width.
        on_screen=moved(point,'3')
        if kind=='screenR':
            value=op('20',op('2',on_screen,rgb([1,1,0])))
        else:
            value=op('0',op('2',op('8',on_screen,rgb([1,0,0] if kind=='screenX' else [0,-1,0])),rgb(.5)),rgb(.5))
    elif kind in ('distance','objDistance'):
        value=op('20',op('1',world_point,locator))
    elif kind in ('distanceX','distanceY','distanceZ','objDistanceX','objDistanceY','objDistanceZ'):
        axis=[[1,0,0],[0,1,0],[0,0,1]]['XYZ'.index(kind[-1])]
        value=op('15',op('8',op('1',world_point,locator),rgb(axis)))
    elif kind=='backFacing':
        value=node('TwoSidedMap',{'front_color':rgb(0),'back_color':rgb(1)})
    elif kind=='textureLocal':
        # Texture U or V under a Solid or Planar projection: the point in the texture locator's space along its axis
        # (the axis over its length squared, so that a scaled locator stretches it); Planar a half on, wrapped to 0..1.
        value=op('8',op('1',world_point,locator),rgb([float(v) for v in data['axis_vector']]))
        if data.get('wrap'):
            value=op('0',value,rgb(.5))
            value=op('1',value,op('17',value))
    else:
        raise ValueError('Gradient input %s has no translated sample source'%kind)
    low,high=data.get('span',[0.0,1.0])
    scaled=op('2',op('1',value,rgb(low)),rgb(1.0/max(high-low,1e-9)))
    return node('ModoTextureMap',{'mode':'7','component':'0','foreground':scaled})


def sample(data,value):
    """Same clamped linear lookup as the emitted RampMap, for environments."""
    from bisect import bisect_right
    positions=data['positions'];colors=data['colors']
    right=bisect_right(positions,value)
    if right==0:return list(colors[0])
    if right==len(positions):return list(colors[-1])
    left=right-1;amount=(value-positions[left])/(positions[right]-positions[left])
    return [a+(b-a)*amount for a,b in zip(colors[left],colors[right])]
