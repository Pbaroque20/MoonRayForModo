"""Serialize an ordered texture graph into native MoonRay maps."""
from . import textures
from .layers import BLENDS

def bindings(material, index, lines, glass=False):
    from .rdla import string, number, vector
    count = [0]
    def node(kind, attributes):
        name = '/modo/graph/%d/%d' % (index,count[0]); count[0]+=1
        lines.append('%s(%s) {' % (kind,string(name)))
        for key, value in attributes.items():
            if value.startswith('bind('):
                unit = '1' if key in ('height','opacity','mask') else ('Vec3(1, 1, 1)' if key=='input_texture_coordinates' else 'Rgb(1, 1, 1)')
                value = value[:-1] + ', ' + unit + ')'
            lines.append('  [%s] = %s,' % (string(key),value))
        lines.append('}')
        return 'bind(%s(%s))' % (kind,string(name))
    def rgb(value):
        return vector(value if isinstance(value,(list,tuple)) else [value]*3,'Rgb')
    defaults = {'diffCol':material['color'], 'rough':material.get('roughness',.4),
        'metallic':material.get('metallic',0),'specCol':material.get('specular',[.04]*3),
        'lumiCol':material.get('emission',[0]*3),'coatAmt':material.get('clearcoat',0),
        'coatRough':material.get('clearcoat_roughness',.01),'tranAmt':material.get('transmission',0),
        'tranCol':material.get('transmission_color',[1]*3),'tranRough':material.get('refraction_roughness',0),
        'normal':[.5,.5,1], 'bump':0, 'groupMask':1, 'aniso':material.get('anisotropy',0),
        'diffAmt':material.get('diffuse_amount',1), 'specAmt':material.get('specular_amount',1),
        'lumiAmt':material.get('emission_amount',1), 'dissolve':1-material.get('presence',1)}
    for effect, raw, amount in [('diffCol','raw_color','diffuse_amount'),
                                ('specCol','raw_specular','specular_amount'),
                                ('lumiCol','raw_emission','emission_amount')]:
        gain = material.get(amount, 1)
        defaults[effect] = material.get(raw, [v/gain if gain else 0 for v in defaults[effect]])
    current = {key:rgb(value) for key,value in defaults.items()}
    used = set()
    layers = material.get('layers')
    if layers is None:
        layers = [dict(value,effect=key,kind=value.get('kind','imageMap')) for key,value in material.get('textures',{}).items()]
    for layer in layers:
        effect = textures.EFFECT_ALIASES.get(layer['effect'], layer['effect'])
        if effect not in textures.EFFECTS:
            raise ValueError('Unsupported image effect: '+effect)
        if glass and effect in ('specCol','specAmt','coatAmt','coatRough','metallic'):
            continue
        kind = layer.get('kind','imageMap')
        mask = None
        coordinates = None
        if layer.get('coordinate_key'):
            coordinates = node('AttributeMap', {'primitive_attribute_name':string(layer['coordinate_key']),
                'primitive_attribute_type':'1', 'warn_when_unavailable':'true', 'default_value':'Rgb(0,0,0)'})
        if kind=='constant':
            foreground = rgb(layer['value'])
        elif kind in ('checker','noise'):
            foreground = node('ModoTextureMap', {'mode':str(2 if kind=='checker' else 3),
                'background':rgb(layer['color1']), 'foreground':rgb(layer['color2']),
                'scale':vector([1,1] if coordinates else layer.get('scale',[1,1]),'Vec2'),
                **({'coordinates':coordinates,'use_coordinates':'true'} if coordinates else {}),
                'octaves':str(layer.get('octaves',4)),'lacunarity':number(layer.get('lacunarity',2)),
                'persistence':number(layer.get('persistence',.5))})
        else:
            prepared = textures.prepare(layer['path'],layer.get('srgb',False))
            attributes = {'texture':string(prepared),'gamma':'0',
                'wrap_around':'true' if layer.get('repeat',True) else 'false',
                'scale':vector([1,1] if coordinates else layer.get('scale',[1,1]),'Vec2')}
            if coordinates:
                attributes.update(texture_coordinates='2', input_texture_coordinates=coordinates)
            alpha = node('ImageMap',dict(attributes,alpha_only='true')) if effect in textures.COLOR_EFFECTS else None
            if layer.get('use_alpha'):
                mask = alpha
            gain = [-1 if layer.get('flip_red') else 1,-1 if layer.get('flip_green') else 1,1]
            attributes.update(gain_offset_enabled='true',gain=rgb(gain),
                              offset_adjust=rgb([1 if v<0 else 0 for v in gain]))
            foreground = node('ImageMap',attributes)
            if alpha:
                # OIIO loads associated RGB; the layer blend applies alpha once.
                foreground = node('ModoTextureMap',{'background':foreground,'foreground':alpha,'blend':'5'})
        if layer.get('invert'):
            foreground = node('ModoTextureMap',{'background':rgb(1),'foreground':foreground,'blend':'3'})
        blend = layer.get('blend','normal')
        if blend not in BLENDS:
            raise ValueError('Unsupported blend: '+blend)
        attributes = {'background':current[effect],'foreground':foreground,
                      'blend':str(BLENDS[blend]),'opacity':number(layer.get('opacity',1))}
        if mask:
            attributes['mask'] = mask
        current[effect] = node('ModoTextureMap',attributes)
        used.add(effect)
    result = {}
    amounts = {'diffCol':'diffAmt', 'specCol':'specAmt', 'lumiCol':'lumiAmt'}
    for color_effect, amount_effect in amounts.items():
        if amount_effect in used:
            used.add(color_effect)
    for effect in sorted(used-{'normal','bump','diffAmt','specAmt','lumiAmt','dissolve'}):
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
    if used & {'normal','bump'}:
        result['normal'] = node('ModoTextureMap',{'mode':'1','normal':current['normal'],
            'height':current['bump'] if 'bump' in used else '0',
            'bump_strength':number(material.get('bump_strength',.005) if 'bump' in used else 0)})
    return result
