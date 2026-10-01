"""Select a single interior medium for a surface material assignment."""
import json
from .textures import EFFECT_ALIASES


def effect(layer):
    return EFFECT_ALIASES.get(layer['effect'],layer['effect'])


def color_layers(material):
    # Keep scoped mask layers so grouped transmission textures stay masked.
    return [layer for layer in (material.get('layers') or []) if effect(layer) in ('tranCol','groupMask')]


def enabled(material):
    if material.get('native_shader'): return False
    mapped = any(effect(layer)=='tranAmt' for layer in (material.get('layers') or [])) or any(
        EFFECT_ALIASES.get(key,key)=='tranAmt' for key in material.get('textures',{}))
    return material.get('absorption_distance',0)>0 and (material.get('transmission',0)>0 or mapped) and not material.get('thin_geometry',False)


def surface(material):
    if not enabled(material):
        return material
    result=dict(material,transmission_color=[1,1,1],
                textures={key:value for key,value in material.get('textures',{}).items()
                          if EFFECT_ALIASES.get(key,key)!='tranCol'})
    if material.get('layers') is not None:
        result['layers']=[layer for layer in material['layers'] if effect(layer)!='tranCol']
    return result


def medium(material):
    stack=material.get('material_stack')
    if not stack:
        return material if enabled(material) else None
    active=[]
    for index,layer in enumerate(stack):
        weight=layer.get('layer_opacity',1)
        if index and weight<=0:
            continue
        masked=any(effect(entry)=='groupMask' for entry in (layer.get('layers') or [])) or any(
            EFFECT_ALIASES.get(key,key)=='groupMask' for key in layer.get('textures',{}))
        if index and weight>=1 and not masked:
            active=[]
        active.append(layer)
    signatures=[]
    for layer in active:
        signature=None
        if enabled(layer):
            signature={'distance':layer['absorption_distance'],'color':layer.get('transmission_color',[1,1,1]),
                       'layers':color_layers(layer),
                       'textures':{key:value for key,value in layer.get('textures',{}).items()
                                   if EFFECT_ALIASES.get(key,key)=='tranCol'}}
        signatures.append(json.dumps(signature,sort_keys=True))
    if len(set(signatures))>1:
        raise ValueError('Layered material has different interior absorption settings. Use a common interior or separate closed meshes; mixed interiors are not translated.')
    return active[-1] if active and enabled(active[-1]) else None
