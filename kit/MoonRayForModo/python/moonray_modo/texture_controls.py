"""Explicit layer processing shared by surface and environment textures."""
import math

def capture(item, channel):
    controls={key:float(channel(item,key,default)) for key,default in
              (('gamma',1),('brightness',1),('contrast',1))}
    if not all(math.isfinite(v) for v in controls.values()) or controls['gamma']<=0:
        raise ValueError('Texture corrections must be finite and gamma must be positive')
    # Low Value and High Value: what the image's black and its white come out as. Kept only where they are set.
    low,high=float(channel(item,'min',0)),float(channel(item,'max',1))
    if not (math.isfinite(low) and math.isfinite(high)):
        raise ValueError('Texture Low Value and High Value must be finite')
    if (low,high)!=(0.0,1.0):controls.update(low=low,high=high)
    return controls

def remap(controls):
    """(gain, offset) of Low Value and High Value: the image's 0 to 1 becomes low to high."""
    low,high=float(controls.get('low',0)),float(controls.get('high',1))
    return high-low,low

def affine(controls):
    """(gain, offset) of contrast, then brightness, then Low Value and High Value, each a gain and an offset: one."""
    brightness=controls.get('brightness',1);contrast=controls.get('contrast',1)
    gain,offset=remap(controls)
    return contrast*brightness*gain,.5*(1-contrast)*brightness*gain+offset
def emit(value, controls, node, number):
    # Work on unassociated linear RGB; alpha is a coverage mask, not a color.
    # The same two nodes whatever the values, at no change where nothing is set: a node there only while a value was
    # set made a change of Low Value, High Value, gamma, brightness or contrast to or from its default a new scene to
    # MoonRay (scene_delta: its lines change), which loaded everything again, twenty seconds on a heavy scene.
    value=node('ColorCorrectGammaMap',{'input':value,'gamma':number(controls.get('gamma',1))})
    gain,offset=affine(controls)
    return node('ColorCorrectGainOffsetMap',{'input':value,'gain':number(gain),'offset':number(offset)})
