"""Ordered Modo texture-layer sampling; no changes to the scene."""
from pathlib import Path
from . import textures

BLENDS = {'normal':0, 'multiply':1, 'add':2, 'subtract':3, 'screen':4}

def ordered_items(parent):
    for item in parent.children():
        yield item
        yield from ordered_items(item)

def material_tag(item):
    from .host import channel
    tag = None
    parent = item.parent
    while parent and parent.type != 'polyRender':
        if not channel(parent, 'enable', 1):
            return None
        if parent.type != 'mask':
            raise ValueError('unsupported shader parent ' + parent.type)
        if channel(parent, 'opacity', 1) != 1 or channel(parent, 'blend', 'normal') != 'normal':
            raise ValueError('group opacity and group blending are unsupported')
        kind, value = channel(parent, 'ptyp', ''), channel(parent, 'ptag', '')
        if kind in ('Material', 'material', 'MATR') and value:
            if tag is not None and tag != value:
                raise ValueError('nested material selections are unsupported')
            tag = value
        elif kind or value:
            raise ValueError('only material-tag masks and unfiltered groups are supported')
        parent = parent.parent
    return tag if tag is not None else ''

def collect(scene, materials, warnings, baked_effects=(), layer_filter=None, material_key=None):
    from .host import channel, color
    items = list(ordered_items(scene.renderItem))
    positions = {item.id:i for i,item in enumerate(items)}
    for layer in reversed(items): # Modo's upper rows are applied last.
        if layer.type not in ('imageMap','constant','checker','noise'):
            continue
        if layer_filter is not None and layer.id not in layer_filter:
            continue
        if not channel(layer,'enable',1) or not channel(layer,'render',1):
            continue
        if channel(layer,'effect','') in baked_effects:
            continue
        try:
            if layer_filter is None:
                tag = material_tag(layer)
            else:
                # Render Cache already resolved item, part and instance masks.
                # Their compositing still needs explicit support before use.
                parent=layer.parent
                while parent and parent.type != 'polyRender':
                    if channel(parent,'opacity',1)!=1 or channel(parent,'blend','normal')!='normal':
                        raise ValueError('group opacity and group blending are unsupported')
                    parent=parent.parent
                tag = material_key
            if tag is None:
                continue
            if tag not in materials:
                raise ValueError('mask has no translated base material')
            base = materials[tag].get('base_layer_id')
            if base in positions and positions[layer.id] > positions[base]:
                # An upper material replaces this layer's channels.
                warnings.append('Layer %s is below its material and is overridden. Move it above the material in the same Shader Tree group.' % layer.name)
                continue
            effect = channel(layer,'effect','')
            effect = textures.EFFECT_ALIASES.get(effect, effect)
            if effect not in textures.EFFECTS:
                raise ValueError('unsupported effect '+effect)
            blend = channel(layer,'blend','normal')
            if blend not in BLENDS:
                raise ValueError('unsupported blend '+blend)
            node = {'kind':layer.type, 'effect':effect, 'opacity':float(channel(layer,'opacity',1)),
                    'blend':blend, 'uv_map':'', 'invert':bool(channel(layer,'invert',0))}
            if effect == 'normal' and (blend != 'normal' or layer.type != 'imageMap'):
                raise ValueError('normal maps require an image and Normal blending')
            is_color = effect in textures.COLOR_EFFECTS or effect == 'normal'
            if layer.type == 'constant':
                node['value'] = color(layer,'color',(0,0,0)) if is_color else [float(channel(layer,'value',1))]*3
            else:
                connected = layer.itemGraph('shadeLoc').forward()
                locator = next((i for i in connected if i.type=='txtrLocator'),None)
                if not locator or channel(locator,'projType','') != 'uv':
                    raise ValueError('choose UV projection')
                node['uv_map'] = channel(locator,'uvMap','')
                if not node['uv_map']:
                    raise ValueError('choose a named UV map')
                if any(channel(locator,key,default) != default for key,default in
                       {'uvRotation':0,'m00':1,'m01':0,'m02':0,'m10':0,'m11':1,'m12':0,'randOffset':'none'}.items()):
                    raise ValueError('UV transforms other than repeat counts are unsupported')
                node['scale'] = [float(channel(locator,'wrapU',1)),float(channel(locator,'wrapV',1))]
                if layer.type == 'imageMap':
                    clip = next((i for i in connected if i.type=='videoStill'),None)
                    if not clip:
                        raise ValueError('requires a still image; UDIM folders are unsupported')
                    checks = {'gamma':1,'brightness':1,'contrast':1,'swizzling':0,'blueInv':0}
                    if effect != 'normal':
                        checks.update(redInv=0,greenInv=0)
                    if any(channel(layer,key,value) != value for key,value in checks.items()):
                        raise ValueError('image color corrections are unsupported')
                    node['flip_red'] = bool(channel(layer,'redInv',0))
                    node['flip_green'] = bool(channel(layer,'greenInv',0))
                    tile = channel(locator,'tileU','repeat')
                    if tile not in ('repeat','edge') or channel(locator,'tileV','repeat') != tile:
                        raise ValueError('requires matching Repeat or Edge modes')
                    node['repeat'] = tile=='repeat'
                    path = Path(channel(clip,'filename',''))
                    if not path.is_absolute() and getattr(scene,'filename',None):
                        path = Path(scene.filename).parent/path
                    if not path.is_file():
                        raise ValueError('missing image '+str(path))
                    space = channel(clip,'colorspace','(default)')
                    if space not in ('(default)','(none)','sRGB','Linear','linear'):
                        raise ValueError('unsupported color space '+space)
                    node.update(path=str(path.resolve()),mtime=path.stat().st_mtime_ns,size=path.stat().st_size,
                        srgb=effect not in ('normal','bump') and (space=='sRGB' or
                            (space=='(default)' and effect in textures.COLOR_EFFECTS and path.suffix.lower() not in ('.exr','.hdr','.tx'))),
                        use_alpha=effect in textures.COLOR_EFFECTS and channel(layer,'alpha','use')=='use')
                else:
                    node.update(color1=color(layer,'color1',(0,0,0)) if is_color else [float(channel(layer,'value1',0))]*3,
                                color2=color(layer,'color2') if is_color else [float(channel(layer,'value2',1))]*3)
                    if channel(layer,'bias',.5)!=.5 or channel(layer,'gain',.5)!=.5:
                        raise ValueError('procedural bias/gain adjustments are unsupported')
                    if layer.type=='checker' and (channel(layer,'type','square')!='square' or channel(layer,'variation',0)):
                        raise ValueError('only unvaried square checkers are supported')
                    if layer.type=='noise':
                        if channel(layer,'type','fractal')!='fractal' or any(channel(layer,k,0) for k in ('flowNoise','angle','smoothTops')):
                            raise ValueError('only static fractal noise is supported')
                        node.update(octaves=int(channel(layer,'freqs',4)),lacunarity=float(channel(layer,'freqRatio',2)),
                                    persistence=float(channel(layer,'ampRatio',.5)))
                        warnings.append('Noise uses a MoonRay UV fractal approximation, not the exact Modo pattern: '+layer.name)
            material = materials[tag]
            uv = node['uv_map']
            if uv and material.get('uv_map') not in (None,uv):
                raise ValueError('multiple UV sets in one material are unsupported')
            if uv:
                material['uv_map'] = uv
            material.setdefault('layers',[]).append(node)
            # Keep source metadata available to existing callers and live digests.
            material.setdefault('textures',{})[effect] = node
        except (ValueError,LookupError,OSError) as exc:
            warnings.append('Layer %s: %s.' % (layer.name,exc))
