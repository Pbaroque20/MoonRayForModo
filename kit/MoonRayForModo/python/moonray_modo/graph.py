"""Serialize an ordered texture graph into native MoonRay maps."""
from . import textures
from .layers import BLENDS

def bindings(material, index, lines, glass=False, absorption=False, separate_masks=False, mask_state=None, group_mask=None):
    from .rdla import string, number, vector
    count = [0]
    def node(kind, attributes):
        name = '/modo/graph/%d/%d' % (index,count[0]); count[0]+=1
        lines.append('%s(%s) {' % (kind,string(name)))
        for key, value in attributes.items():
            if value.startswith('bind('):
                unit = '1' if key in ('height','opacity','mask') or (kind=='RampMap' and key=='input') else ('Vec3(1, 1, 1)' if key=='input_texture_coordinates' else 'Rgb(1, 1, 1)')
                value = value[:-1] + ', ' + unit + ')'
            lines.append('  [%s] = %s,' % (string(key),value))
        lines.append('}')
        return 'bind(%s(%s))' % (kind,string(name))
    def rgb(value):
        return vector(value if isinstance(value,(list,tuple)) else [value]*3,'Rgb')
    defaults = defaults_for(material)
    if absorption:defaults.update(absorption_values(material))
    current = {key:rgb(value) for key,value in defaults.items()}
    from .compositing import Groups
    def group_blend(background, foreground, opacity, mask):
        attributes = {'background':background, 'foreground':foreground,
                      'blend':'0', 'opacity':number(opacity)}
        if mask is not None:
            attributes['mask'] = mask
        return node('ModoTextureMap', attributes)
    # Native material partitions share target masks and the enclosing mask value.
    pending_masks={} if mask_state is None else mask_state
    if group_mask is not None:current['groupMask']=group_mask
    def scoped_blend(background,foreground,group,mask,effect):
        if group.get('invert') and effect in textures.COLOR_EFFECTS:
            foreground=node('ModoTextureMap',{'background':rgb(1),'foreground':foreground,'blend':'3'})
        attributes={'background':background,'foreground':foreground,'blend':str(BLENDS[group.get('blend','normal')]),'opacity':number(group.get('opacity',1))}
        external=pending_masks.get(group['id'])
        if external:mask=node('ModoTextureMap',{'background':mask,'foreground':external,'blend':'1'}) if mask else external
        if mask is not None:attributes['mask']=mask
        return node('ModoTextureMap',attributes)
    groups = Groups(current, group_blend, scoped_blend)
    layers = material.get('layers')
    if layers is None:
        layers = [dict(value,effect=key,kind=value.get('kind','imageMap')) for key,value in material.get('textures',{}).items()]
    for layer in layers:
        layer=dict(layer)
        if layer.get('procedural'):
            from .procedurals import bake
            path,alpha_path=bake(layer['procedural'])
            layer.update(kind='imageMap',path=str(path),procedural_alpha=str(alpha_path),image_channel='ignore',srgb=False,color_space='raw',bias=.5,gain=.5)
        groups.select(layer.get('groups', []))
        current, used = groups.current, groups.used
        effect = textures.EFFECT_ALIASES.get(layer['effect'], layer['effect'])
        if layer.get('kind')=='materialBase':
            source=layer['material']
            row_mask=pending_masks.pop(layer.get('identity'),None)
            base_values=defaults_for(source)
            if absorption:base_values.update(absorption_values(source))
            for target,foreground in base_values.items():
                if target in {'groupMask','layerMask'}|textures.INTERNAL_EFFECTS:continue
                if layer.get('invert') and target in textures.COLOR_EFFECTS:
                    foreground=[1-v for v in foreground] if isinstance(foreground,list) else 1-foreground
                current[target]=node('ModoTextureMap',{'background':current[target],'foreground':rgb(foreground),'blend':str(BLENDS[layer.get('blend','normal')]),'opacity':number(layer.get('opacity',1)),**({'mask':row_mask} if row_mask else {})})
                used.add(target)
            continue
        if absorption and effect=='tranCol' and layer.get('absorption_distance',material.get('absorption_distance',0))<=0:continue
        if effect not in textures.EFFECTS:
            raise ValueError('Unsupported image effect: '+effect)
        if glass and effect in ('specCol','specAmt','coatAmt','coatRough','metallic'):
            continue
        kind = layer.get('kind','imageMap')
        mask = None
        coordinates = None
        if layer.get('coordinate_key') and effect not in ('normal','normalCoat','bump','coatBump'):
            coordinates = node('AttributeMap', {'primitive_attribute_name':string(layer['coordinate_key']),
                'primitive_attribute_type':'1', 'warn_when_unavailable':'true', 'default_value':'Rgb(0,0,0)'})
        normal_basis=None
        named_basis=layer.get('coordinate_key') if effect in ('normal','normalCoat','bump','coatBump') else None
        if named_basis:
            coordinates=node('ModoTextureMap',{'mode':'12','uv_name':string(named_basis)})
        if effect in ('normal','normalCoat','bump','coatBump') and kind!='constant' and not coordinates:
            from .coordinates import affine
            matrix,offset=affine(layer)
            normal_basis=matrix
            coordinates=node('ModoTextureMap',{'mode':'12','uv_affine':vector(matrix,'Vec4'),'uv_offset':vector(offset,'Vec2')})
        if kind=='gradient':
            from .gradients import emit as emit_gradient
            foreground=emit_gradient(layer['gradient'],current,node,rgb)
            if 'alpha' in layer['gradient']:
                mask=emit_gradient(dict(layer['gradient'],colors=[[v]*3 for v in layer['gradient']['alpha']]),current,node,rgb)
        elif kind=='constant':
            foreground = rgb(layer['value'])
        elif kind in ('checker','noise'):
            foreground = node('ModoTextureMap', {'mode':str(2 if kind=='checker' else 3),
                'background':rgb(0), 'foreground':rgb(1),
                'scale':vector([1,1] if coordinates else layer.get('scale',[1,1]),'Vec2'),
                **({'coordinates':coordinates,'use_coordinates':'true'} if coordinates else {}),
                'octaves':str(layer.get('octaves',4)),'lacunarity':number(layer.get('lacunarity',2)),
                'persistence':number(layer.get('persistence',.5))})
            if layer.get('bias',.5)!=.5:
                foreground=node('RemapMap',{'input':foreground,'midpoint_bias':number(layer['bias'])})
            if layer.get('gain',.5)!=.5:
                foreground=node('ModoTextureMap',{'mode':'8','foreground':foreground,'distance':number(layer['gain'])})
            if layer.get('alpha1',1)!=1 or layer.get('alpha2',1)!=1:
                mask=node('ModoTextureMap',{'background':rgb(layer.get('alpha1',1)),'foreground':rgb(layer.get('alpha2',1)),'opacity':foreground})
            foreground=node('ModoTextureMap',{'background':rgb(layer['color1']),'foreground':rgb(layer['color2']),'opacity':foreground})
        else:
            prepared = textures.prepare(layer['path'],layer.get('srgb',False),color_space=layer.get('color_space',''))
            tile_modes = {'repeat':0, 'edge':1, 'mirror':2, 'reset':3}
            tile_u = layer.get('tile_u', 'repeat' if layer.get('repeat',True) else 'edge')
            tile_v = layer.get('tile_v', tile_u)
            if tile_u not in tile_modes or tile_v not in tile_modes:
                raise ValueError('Unsupported texture repeat mode')
            coverage = None
            wrapped = tile_u != 'repeat' or tile_v != 'repeat'
            if wrapped:
                if '<UDIM>' in layer['path']:
                    raise ValueError('UDIM tile addressing requires Repeat on both axes')
                wrapping = {'scale':vector([1,1] if coordinates else layer.get('scale',[1,1]),'Vec2'),
                            'tile_u':str(tile_modes[tile_u]), 'tile_v':str(tile_modes[tile_v])}
                if coordinates:
                    wrapping.update(coordinates=coordinates,use_coordinates='true')
                if 'reset' in (tile_u,tile_v):
                    coverage = node('ModoTextureMap',dict(wrapping,mode='6'))
                coordinates = node('ModoTextureMap',dict(wrapping,mode='5'))
            attributes = {'texture':string(prepared),'gamma':'0',
                'wrap_around':'false' if wrapped else 'true',
                'scale':vector([1,1] if coordinates else layer.get('scale',[1,1]),'Vec2')}
            if coordinates:
                attributes.update(texture_coordinates='2', input_texture_coordinates=coordinates)
            alpha = node('ImageMap',dict(attributes,alpha_only='true'))
            if layer.get('procedural_alpha'):
                mask=node('ImageMap',dict(attributes,texture=string(textures.prepare(layer['procedural_alpha'],False,color_space='raw'))))
            source_channel = layer.get('image_channel','use' if layer.get('use_alpha') else 'ignore')
            if source_channel not in ('use','ignore','only','red','green','blue'):
                raise ValueError('Unsupported image channel: '+str(source_channel))
            if source_channel == 'use':
                mask = alpha
            if coverage:
                mask = node('ModoTextureMap',{'background':mask,'foreground':coverage,'blend':'1'}) if mask else coverage
            if source_channel == 'only':
                foreground = alpha
            else:
                foreground = node('ImageMap',attributes)
                # The sampled RGB is associated. Recover RGB before channel
                # extraction/inversion, then apply alpha once in layer blending.
                foreground = node('ModoTextureMap',{'background':foreground,'foreground':alpha,'blend':'5'})
                flips = [bool(layer.get('flip_'+c)) for c in ('red','green','blue')]
                if any(flips):
                    foreground = node('ModoTextureMap',{'background':foreground,
                        'foreground':rgb([-1 if flip else 1 for flip in flips]),'blend':'1'})
                    foreground = node('ModoTextureMap',{'background':foreground,
                        'foreground':rgb([1 if flip else 0 for flip in flips]),'blend':'2'})
                if source_channel in ('red','green','blue'):
                    foreground = node('ModoTextureMap',{'mode':'7','foreground':foreground,
                        'component':str(('red','green','blue').index(source_channel))})
        if layer.get('corrections'):
            from .texture_controls import emit as correct
            foreground=correct(foreground,layer['corrections'],node,number)
        if kind not in ('checker','noise') and layer.get('bias',.5)!=.5:
            foreground=node('RemapMap',{'input':foreground,'midpoint_bias':number(layer['bias'])})
        if kind not in ('checker','noise') and layer.get('gain',.5)!=.5:
            foreground=node('ModoTextureMap',{'mode':'8','foreground':foreground,'distance':number(layer['gain'])})
        if layer.get('invert'):
            foreground = node('ModoTextureMap',{'background':rgb(1),'foreground':foreground,'blend':'3'})
        if effect in ('normal','normalCoat') and named_basis:
            foreground=node('ModoTextureMap',{'mode':'13','foreground':foreground,'uv_name':string(named_basis),'tile_u':str({'repeat':0,'edge':1,'mirror':2,'reset':3}.get(layer.get('tile_u'),0)),'tile_v':str({'repeat':0,'edge':1,'mirror':2,'reset':3}.get(layer.get('tile_v'),0))})
        elif effect in ('normal','normalCoat') and normal_basis is not None:
            foreground=node('ModoTextureMap',{'mode':'13','foreground':foreground,'uv_affine':vector(normal_basis,'Vec4'),'uv_offset':vector(offset,'Vec2'),'tile_u':str({'repeat':0,'edge':1,'mirror':2,'reset':3}.get(layer.get('tile_u'),0)),'tile_v':str({'repeat':0,'edge':1,'mirror':2,'reset':3}.get(layer.get('tile_v'),0))})
        blend = layer.get('blend','normal')
        if blend=='normalblend' and effect in ('normal','normalCoat'):
            # Reoriented normal mapping: preserve both tangent-space directions.
            t=node('OpMap',{'operation':'0','op1':current[effect],'op1_factor':'2','op2':rgb([-1,-1,0])})
            u=node('OpMap',{'operation':'2','op1':foreground,'op2':rgb([-2,-2,2])})
            u=node('OpMap',{'operation':'0','op1':u,'op2':rgb([1,1,-1])})
            dot=node('OpMap',{'operation':'8','op1':t,'op2':u})
            z=node('ModoTextureMap',{'mode':'7','foreground':t,'component':'2'})
            factor=node('ModoTextureMap',{'background':dot,'foreground':z,'blend':'5'})
            n=node('OpMap',{'operation':'2','op1':t,'op2':factor})
            n=node('OpMap',{'operation':'1','op1':n,'op2':u})
            n=node('OpMap',{'operation':'10','op1':n})
            foreground=node('OpMap',{'operation':'0','op1':n,'op1_factor':'.5','op2':rgb(.5)})
            blend='normal'
        if blend not in BLENDS:
            raise ValueError('Unsupported blend: '+blend)
        single_mask=pending_masks.pop(layer.get('identity'),None)
        if single_mask:
            mask=node('ModoTextureMap',{'background':mask,'foreground':single_mask,'blend':'1'}) if mask else single_mask
        attributes = {'background':current[effect],'foreground':foreground,
                      'blend':str(BLENDS[blend]),'opacity':number(layer.get('opacity',1))}
        if mask:
            attributes['mask'] = mask
        if effect=='layerMask':
            attributes['background']=rgb(1)
            pending_masks[layer.get('mask_target','')]=node('ModoTextureMap',attributes)
            continue
        current[effect] = node('ModoTextureMap',attributes)
        used.add(effect)
    current, used = groups.finish()
    # Native material rows are emitted outside this channel graph. Preserve the
    # target mask for their BSDF compositor instead of leaving it pending.
    material_mask=pending_masks.pop(material.get('base_layer_id'),None)
    if material_mask and not separate_masks:
        current['groupMask']=node('ModoTextureMap',{'background':current['groupMask'],'foreground':material_mask,'blend':'1'}) if 'groupMask' in used else material_mask
        used.add('groupMask')
    if absorption:
        from .working_space import expression
        value=current['tranCol']
        value=value[:-1]+', Rgb(1,1,1))' if value.startswith('bind(') else value
        value=expression(value,'/modo/absorption/working/'+str(index),lines)
        if value.startswith('bind('):value=value.rsplit(', Rgb(1,1,1)',1)[0]+')'
        attenuation=node('ModoTextureMap',{'mode':'11','foreground':value,'background':current['absorptionDensity']})
        return {'transmissionColor':attenuation[:-1]+', Rgb(1,1,1))'}
    result = {}
    if material_mask and separate_masks:result['_rowMask']=material_mask[:-1]+', 1)'
    amounts = {'diffCol':'diffAmt', 'specCol':'specAmt', 'lumiCol':'lumiAmt'}
    for color_effect, amount_effect in amounts.items():
        if amount_effect in used:
            used.add(color_effect)
    for effect in sorted(used-textures.INTERNAL_EFFECTS-{'normal','normalCoat','coatBump','bump','diffAmt','specAmt','lumiAmt','dissolve'}):
        value = current[effect]
        if effect in amounts:
            amount_effect = amounts[effect]
            if amount_effect in used or defaults[amount_effect] != 1:
                value = node('ModoTextureMap',{'background':value,'foreground':current[amount_effect],'blend':'1'})
        unit = 'Rgb(1, 1, 1)' if effect in textures.COLOR_EFFECTS else '1'
        result[textures.EFFECTS[effect]] = value[:-1] + ', ' + unit + ')'
    if 'specAmt' in used and material.get('shader') == 'DwaBaseMaterial':
        result['specularAmount'] = current['specAmt'][:-1] + ', 1)'
    if 'dissolve' in used:
        value = node('ModoTextureMap',{'background':rgb(1),'foreground':current['dissolve'],'blend':'3'})
        result['presence'] = value[:-1] + ', 1)'
    for normal_effect,bump_effect,result_key in (('normal','bump','normal'),('normalCoat','coatBump','coatNormal')):
        if used & {normal_effect,bump_effect}:
            result[result_key] = node('ModoTextureMap',{'mode':'1','normal':current[normal_effect],
                'height':current[bump_effect] if bump_effect in used else '0',
                'bump_strength':number(material.get('bump_strength',.005) if bump_effect in used else 0)})
    return result


def defaults_for(material):
    defaults = {**{key:0 for key in textures.INTERNAL_EFFECTS}, 'diffCol':material.get('color',[.5,.5,.5]), 'rough':material.get('roughness',.4),
        'metallic':material.get('metallic',0),'specCol':material.get('specular',[.04]*3),
        'lumiCol':material.get('emission',[0]*3),'coatAmt':material.get('clearcoat',0),
        'coatRough':material.get('clearcoat_roughness',.01),'tranAmt':material.get('transmission',0),
        'tranCol':material.get('transmission_color',[1]*3),'tranRough':material.get('refraction_roughness',0),
        'normal':[.5,.5,1], 'normalCoat':[.5,.5,1], 'coatBump':0, 'diffRough':material.get('diffuse_roughness',0), 'bump':0, 'layerMask':1, 'groupMask':1, 'aniso':material.get('anisotropy',0),
        'subsCol':material.get('subsurface_color',[1,1,1]), 'subsAmt':material.get('subsurface_amount',0),
        'diffAmt':material.get('diffuse_amount',1), 'specAmt':material.get('specular_amount',1),
        'lumiAmt':material.get('emission_amount',1), 'dissolve':1-material.get('presence',1)}
    for effect, raw, amount in [('diffCol','raw_color','diffuse_amount'),
                                ('specCol','raw_specular','specular_amount'),
                                ('lumiCol','raw_emission','emission_amount')]:
        gain = material.get(amount, 1)
        defaults[effect] = material.get(raw, [v/gain if gain else 0 for v in defaults[effect]])
    defaults["ior"] = material.get("ior",1.5)
    return defaults


def absorption_values(material):
    from .absorption import enabled
    active=enabled(material)
    return {'tranCol':material.get('transmission_color',[1,1,1]) if active else [1,1,1],
            'absorptionDensity':1/material['absorption_distance'] if active else 0}
