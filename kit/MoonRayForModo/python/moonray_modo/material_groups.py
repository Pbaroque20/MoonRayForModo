"""Compile material rows and nested groups as a single parameter stack.

Modo blends channels before shading. This path preserves that ordering for
translated Modo/DwaBase surfaces, including scalar properties and texture masks.
Native shader graphs retain their explicit BSDF-layer path.
"""
import copy

def supported(stack):
    return bool(stack) and all(not m.get('native_shader') and not m.get('node_graph') for m in stack)

def flatten(stack):
    layers=[]
    for material in stack:
        scopes=material.get('material_groups',[])
        masks=[layer for layer in material.get('layers',[]) if layer.get('effect')=='layerMask' and layer.get('mask_target')==material.get('base_layer_id')]
        layers.extend(dict(layer,groups=layer.get('absolute_groups',scopes+layer.get('groups',[]))) for layer in masks)
        layers.append({'identity':material.get('base_layer_id'),'kind':'materialBase','effect':'diffCol','material':material,
                       'opacity':material.get('layer_opacity',1),'groups':scopes,
                       'blend':material.get('layer_blend','normal'),'invert':material.get('layer_invert',False)})
        for layer in material.get('layers',[]):
            if layer in masks:continue
            layers.append(dict(layer,groups=layer.get('absolute_groups',scopes+layer.get('groups',[])),absorption_distance=material.get('absorption_distance',0)))
    return layers

def merged(stack):
    result=dict(stack[-1],shader='DwaBaseMaterial',layers=flatten(stack))
    # These are the backing values below the first authored material row.
    result.update(color=[.5]*3,raw_color=[.5]*3,roughness=.4,transmission=0,
                  emission=[0]*3,raw_emission=[0]*3,metallic=0,layer_opacity=1)
    result['subsurface_distance']=max(m.get('subsurface_distance',0) for m in stack)
    result['dispersion_abbe']=next((m.get('dispersion_abbe',0) for m in reversed(stack) if m.get('dispersion_abbe',0)>0),0)
    result.pop('material_stack',None)
    return result
