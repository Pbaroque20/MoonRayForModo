"""Translate the explicitly selected MoonShine Material to DwaBaseMaterial."""
def emit(material, tag, index, bindings, lines):
    from .rdla import string, number, vector
    attributes = {
        'albedo':vector(material['color'],'Rgb'),
        'metallic':number(material.get('metallic',0)),
        'metallic_color':vector(material['color'],'Rgb'),
        'roughness':number(material.get('roughness',.4)),
        'anisotropy':number(max(-1,min(1,material.get('anisotropy',0)))),
        'refractive_index':number(material.get('ior',1.5)),
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
