"""MoonShine material and ordered BSDF-layer serialization."""
import math
def emit(material, tag, index, bindings, lines):
    from .rdla import string, number, vector
    from .material_settings import values
    controls = values(material)
    sss_weight = bindings.get('subsurfaceAmount')
    reflection_ior = material.get('ior',1.5)
    if material.get('standard_material') and not material.get('metallic',0):
        f0 = max(0,min(.99,sum(material.get('specular',[.04]*3))/3))
        reflection_ior = (1+math.sqrt(f0))/(1-math.sqrt(f0))
    attributes = {
        'albedo':vector(material['color'],'Rgb'),
        'metallic':number(material.get('metallic',0)),
        'metallic_color':vector(material['color'],'Rgb'),
        'roughness':number(material.get('roughness',.4)),
        'diffuse_roughness':number(material.get('diffuse_roughness',0)),
        'scattering_radius':number(max(0,material.get('subsurface_distance',0)) if material.get('subsurface_amount',0)>0 or sss_weight else 0),
        'scattering_color':vector(material.get('subsurface_color',[1,1,1]),'Rgb'),
        'bssrdf':str(controls['subsurface_model']),
        'enable_sss_input_normal':'true' if controls['sss_input_normal'] else 'false',
        'resolve_self_intersections':'true' if controls['sss_resolve_self_intersections'] else 'false',
        'specular_model':'0' if material.get('anisotropy',0) else '1',
        'shading_tangent':vector([math.cos(controls['anisotropy_angle']), math.sin(controls['anisotropy_angle'])],'Vec2'),
        'anisotropy':number(max(-1,min(1,material.get('anisotropy',0)))),
        'refractive_index':number(reflection_ior),
        'use_independent_transmission_refractive_index':'true',
        'independent_transmission_refractive_index':number(material.get('ior',1.5)),
        'dispersion_abbe_number':number(material.get('dispersion_abbe',0)),
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
        'diffuseRoughness':'diffuse_roughness','clearcoatRoughness':'clearcoat_roughness','specularAmount':'specular', 'subsurfaceColor':'scattering_color'}
    for key,value in bindings.items():
        if key in ('layerMask','subsurfaceAmount'):
            continue
        if key=='anisotropy':
            attributes['specular_model']='0'
        if key in ('normal','coatNormal'):
            name='/modo/normal/%s/%s' % (index,key)
            lines += ['ModoNormalMap(%s) { ["input"] = %s }' % (string(name),value)]
            attributes['input_normal' if key=='normal' else 'independent_clearcoat_normal']='ModoNormalMap(%s)' % string(name)
            if key=='coatNormal':attributes['use_independent_clearcoat_normal']='true'
        elif key=='ior':
            attributes['independent_transmission_refractive_index']=value
            if not material.get('standard_material'):attributes['refractive_index']=value
        elif key=='specularAmount' and material.get('standard_material'):
            attributes['specular']='1'
            attributes['show_specular']='true'
        elif key!='specularColor':
            attributes[names.get(key,key)]=value
            if key=='diffuseColor':
                attributes['metallic_color']=value
            if key=='specularAmount':
                attributes['show_specular']='true'
    if material.get('standard_material') and 'specularColor' in bindings:
        # Modo's standard specular amount is normal-incidence reflectance,
        # whereas Dwa specular is an additional lobe weight. Preserve that distinction.
        path='/modo/fresnel/'+str(index)
        lines.append('ModoTextureMap(%s) { ["mode"] = 9, ["foreground"] = %s }'%(string(path),bindings['specularColor']))
        attributes['refractive_index']='bind(ModoTextureMap(%s), 1)'%string(path)
        attributes['specular']='1';attributes['show_specular']='true'
    from .working_space import surface as working_surface
    attributes=working_surface(attributes,'/modo/material/'+str(index),lines,{'albedo','metallic_color','scattering_color','transmission_color','emission','clearcoat_attenuation_color'})
    lines.append('materials[%s] = DwaBaseMaterial("/modo/material/%s") {' % (string(tag),index))
    lines.extend('  [%s] = %s,' % (string(k),v) for k,v in attributes.items())
    lines.append('}')

    amount = max(0,min(1,material.get('subsurface_amount',0)))
    if (sss_weight or 0 < amount < 1) and material.get('subsurface_distance',0)>0:
        surface_name = '/modo/material/%s/surface' % index
        surface = dict(attributes, scattering_radius='0')
        lines.append('DwaBaseMaterial(%s) {' % string(surface_name))
        lines.extend('  [%s] = %s,' % (string(k),v) for k,v in surface.items())
        lines.append('}')
        lines.append('materials[%s] = DwaLayerMaterial(%s) { ["material_A"] = materials[%s], ["material_B"] = DwaBaseMaterial(%s), ["mask"] = %s }' %
                     (string(tag),string('/modo/material/%s/sss_mix'%index),string(tag),string(surface_name),sss_weight or number(amount)))


def emit_stack(stack, tag, index, lines, library=None, native_index=None):
    from .rdla import string, number
    from .graph import bindings
    from .material_groups import supported, merged
    if supported(stack):
        material=merged(stack)
        maps=bindings(material,index,lines)
        emit(material,tag,index,maps,lines)
        return
    from .compositing import Groups
    scopes_list=[g for material in stack for g in material.get('material_groups',[])]
    if any(g.get('blend','normal')!='normal' or g.get('invert') for g in scopes_list):
        raise ValueError('Native BSDF groups support Normal blending without inversion; arithmetic material groups require explicit graph nodes')
    if any(m.get('layer_blend','normal')!='normal' or m.get('layer_invert') for m in stack):
        raise ValueError('Native BSDF material layers require Normal blending without inversion')
    serial=[0]
    def mix(background,foreground,opacity,mask):
        opacity=float(opacity)
        if not math.isfinite(opacity) or not 0<=opacity<=1:raise ValueError('Material opacity must be between zero and one')
        if opacity==0:return background
        if opacity==1 and mask is None:return foreground
        name='/modo/layers/%s/%s'%(index,serial[0]);serial[0]+=1
        weight=mask.rsplit(', ',1)[0]+', '+number(opacity)+')' if mask else number(opacity)
        ref='DwaLayerMaterial(%s)'%string(name)
        lines.append('%s { ["material_A"] = %s, ["material_B"] = %s, ["mask"] = %s }'%(ref,foreground,background,weight))
        return ref
    default='/modo/stackDefault/'+str(index)
    emit({'color':[.5]*3},default,'stack-default-'+str(index),{},lines)
    scopes=Groups({'surface':'materials[%s]'%string(default),'groupMask':None},mix)
    for i,material in enumerate(stack):
        if i>=1000:raise ValueError('Material stack exceeds 1000 layers')
        scopes.select(material.get('material_groups',[]))
        key='/modo/internal/%s/%s'%(index,i)
        identity=1000000+index*1000+i
        maps=bindings(dict(material,shader='DwaBaseMaterial'),identity,lines,separate_masks=True)
        row_mask=maps.pop('_rowMask',None)
        group_mask=maps.pop('layerMask',None)
        if group_mask:
            scopes.current['groupMask']=group_mask;scopes.used.add('groupMask')
        if material.get('native_shader'):
            from .shader_library import emit as native_emit,compatible
            layered=len(stack)>1 or row_mask or group_mask or material.get('layer_opacity',1)!=1 or any(g.get('opacity',1)!=1 for g in material.get('material_groups',[]))
            if layered and not compatible(material['native_shader'],'INTERFACE_DWABASELAYERABLE'):
                raise ValueError(material['native_shader']+' cannot be mixed in a Dwa Shader Tree stack; assign it separately')
            if material.get('node_graph'):
                from .nodes import emit as native_emit
            ref=native_emit(material,'/modo/native/stack/%s'%identity,native_index or [1000000000+identity],lines,library or {})
            lines.append('materials[%s] = %s'%(string(key),ref))
        else:
            emit(material,key,identity,maps,lines)
        scopes.current['surface']=mix(scopes.current['surface'],'materials[%s]'%string(key),material.get('layer_opacity',1),row_mask)
        scopes.used.add('surface')
    value,used=scopes.finish()
    # Ungrouped masks control the complete root stack.
    if 'groupMask' in used:
        value['surface']=mix('materials[%s]'%string(default),value['surface'],1,value['groupMask'])
    lines.append('materials[%s] = %s'%(string(tag),value['surface']))
