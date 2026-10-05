"""Read nested Shader Tree scale controls without applying changes to Modo."""
import math

def factor(item,control,channel):
    if channel(item,'ignSclGrp',False):return 1.0
    result=1.0;parent=item.parent
    while parent and parent.type not in ('polyRender','environment'):
        if parent.type=='mask' and channel(parent,control,False):
            scale=float(channel(parent,'scaleGroup',1.0))
            if not math.isfinite(scale) or scale<=0:raise ValueError('Shader Tree group scale must be positive and finite')
            result*=scale
        parent=parent.parent
    if not math.isfinite(result) or result<=0:raise ValueError('Nested Shader Tree group scale is out of range')
    return result

def material(item,value,channel):
    for target,control in (('bump_strength','scaleBump'),('absorption_distance','scaleADist'),('subsurface_distance','scaleSDist')):
        value[target]*=factor(item,control,channel)
    return value

def texture(item,value,channel):
    if value.get('projection','uv')=='uv':
        scale=factor(item,'scaleUV',channel)
        # Scaling texture size inversely scales its UV frequency.
        value['scale']=[v/scale for v in value.get('scale',[1,1])]
    elif value.get('locator_matrix'):
        scale=factor(item,'scaleSize',channel)
        matrix=list(value['locator_matrix'])
        for row in range(3):
            for col in range(3):matrix[4*row+col]*=scale
        value['locator_matrix']=matrix
    return value
