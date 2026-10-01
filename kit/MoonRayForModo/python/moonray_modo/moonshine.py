"""MoonShine material and ordered BSDF-layer serialization."""
import math
def emit(material, tag, index, bindings, lines):
    from .rdla import string, number, vector
    reflection_ior = material.get('ior',1.5)
    if material.get('standard_material') and not material.get('metallic',0):
        f0 = max(0,min(.99,sum(material.get('specular',[.04]*3))/3))
        reflection_ior = (1+math.sqrt(f0))/(1-math.sqrt(f0))
    attributes = {
        'albedo':vector(material['color'],'Rgb'),
        'metallic':number(material.get('metallic',0)),
        'metallic_color':vector(material['color'],'Rgb'),
        'roughness':number(material.get('roughness',.4)),
        'scattering_radius':number(max(0,material.get('subsurface_distance',0)) if material.get('subsurface_amount',0)>0 else 0),
        'scattering_color':vector(material.get('subsurface_color',[1,1,1]),'Rgb'),
        'bssrdf':str(int(material.get('subsurface_model',0))),
        'specular_model':'0' if material.get('anisotropy',0) else '1',
        'shading_tangent':vector([math.cos(material.get('anisotropy_angle',0)), math.sin(material.get('anisotropy_angle',0))],'Vec2'),
        'anisotropy':number(max(-1,min(1,material.get('anisotropy',0)))),
        'refractive_index':number(reflection_ior),
        'use_independent_transmission_refractive_index':'true',
        'independent_transmission_refractive_index':number(material.get('ior',1.5)),
        'transmission':number(material.get('transmission',0)),
        'transmission_color':vector(material.get('transmission_color',[1,1,1]),'Rgb'),
        'use_independent_transmission_roughness':'true',
        'independent_transmission_roughness':number(material.get('refraction_roughness',0)),
        'presence':number(material.get('presence',1)),
        'show_emission':'true',
        'emission':vector(material.get('emission',[0,0,0]),'Rgb'),
        'show_clearcoat':'true',
        'clearcoat':number(material.get('clearcoat',0)),
        'clearcoat_roughness':number(material.get('clearcoat_roughness',.01)),
        'show_specular':'true' if material.get('specular_amount',.04)>0 else 'false',
        'thin_geometry':'true' if material.get('thin_geometry',False) else 'false',
    }
    names={'diffuseColor':'albedo','emissiveColor':'emission','ior':'refractive_index',
        'transmissionColor':'transmission_color','refractionRoughness':'independent_transmission_roughness',
        'clearcoatRoughness':'clearcoat_roughness','specularAmount':'specular'}
    for key,value in bindings.items():
        if key=='layerMask':
            continue
        if key=='anisotropy':
            attributes['specular_model']='0'
        if key=='normal':
            name='/modo/normal/%s' % index
            lines += ['ModoNormalMap(%s) { ["input"] = %s }' % (string(name),value)]
            attributes['input_normal']='ModoNormalMap(%s)' % string(name)
        elif key!='specularColor':
            attributes[names.get(key,key)]=value
            if key=='diffuseColor':
                attributes['metallic_color']=value
            if key=='specularAmount':
                attributes['show_specular']='true'
    lines.append('materials[%s] = DwaBaseMaterial("/modo/material/%s") {' % (string(tag),index))
    lines.extend('  [%s] = %s,' % (string(k),v) for k,v in attributes.items())
    lines.append('}')

    amount = max(0,min(1,material.get('subsurface_amount',0)))
    if 0 < amount < 1 and material.get('subsurface_distance',0)>0:
        surface_name = '/modo/material/%s/surface' % index
        surface = dict(attributes, scattering_radius='0')
        lines.append('DwaBaseMaterial(%s) {' % string(surface_name))
        lines.extend('  [%s] = %s,' % (string(k),v) for k,v in surface.items())
        lines.append('}')
        lines.append('materials[%s] = DwaLayerMaterial(%s) { ["material_A"] = materials[%s], ["material_B"] = DwaBaseMaterial(%s), ["mask"] = %s }' %
                     (string(tag),string('/modo/material/%s/sss_mix'%index),string(tag),string(surface_name),number(amount)))


def emit_stack(stack, tag, index, lines):
    from .rdla import string, number
    from .graph import bindings
    for i, material in enumerate(stack):
        key = '/modo/internal/%s/%s' % (index,i)
        identity = 1000000 + index*1000+i
        if i >= 1000:
            raise ValueError('Material stack exceeds 1000 layers')
        maps = bindings(dict(material,shader='DwaBaseMaterial'),identity,lines)
        mask = maps.pop('layerMask',None)
        emit(material, key, identity, maps, lines)
        if i == 0:
            lines.append('materials[%s] = materials[%s]' % (string(tag),string(key)))
        else:
            weight = material.get('layer_opacity',1)
            weight_expression = mask.rsplit(', ',1)[0]+', '+number(weight)+')' if mask else number(weight)
            lines.append('materials[%s] = DwaLayerMaterial(%s) { ["material_A"] = materials[%s], ["material_B"] = materials[%s], ["mask"] = %s }' %
                         (string(tag),string('/modo/layers/%s/%s'%(index,i)),string(key),string(tag),weight_expression))
