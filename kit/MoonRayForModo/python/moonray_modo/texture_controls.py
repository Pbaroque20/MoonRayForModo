"""Explicit layer processing shared by surface and environment textures."""
import math

def capture(item, channel):
    controls={key:float(channel(item,key,default)) for key,default in
              (('gamma',1),('brightness',1),('contrast',1))}
    if not all(math.isfinite(v) for v in controls.values()) or controls['gamma']<=0:
        raise ValueError('Texture corrections must be finite and gamma must be positive')
    return controls

def emit(value, controls, node, number):
    # Work on unassociated linear RGB; alpha is a coverage mask, not a color.
    gamma=controls.get('gamma',1);brightness=controls.get('brightness',1);contrast=controls.get('contrast',1)
    if gamma!=1:value=node('ColorCorrectGammaMap',{'input':value,'gamma':number(gamma)})
    if contrast!=1:
        value=node('ColorCorrectGainOffsetMap',{'input':value,'gain':number(contrast),'offset':number(.5*(1-contrast))})
    if brightness!=1:value=node('ColorCorrectGainOffsetMap',{'input':value,'gain':number(brightness)})
    return value
