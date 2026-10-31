"""Ordered Modo texture-layer sampling; no changes to the scene."""
from pathlib import Path
from . import textures
from .mask_types import tag_kind

BLENDS = {'normal':0, 'multiply':1, 'add':2, 'subtract':3, 'screen':4, 'divide':5, 'difference':6, 'darken':7, 'lighten':8, 'overlay':9, 'hardlight':10, 'exclusion':11, 'softlight':12, 'colordodge':13, 'colorburn':14}

def ordered_items(parent):
    """Yield visible Shader Tree order (top to bottom), preserving group scopes."""
    # Child enumeration follows the shading stack in the opposite direction
    # from the displayed rows. Normalize siblings here, not the flattened tree:
    # collect, material_stack and evaluated assignment all expect top-first.
    for item in reversed(list(parent.children())):
        yield item
        yield from ordered_items(item)

def above_shader(render):
    """The items at the top of the Shader Tree that sit above its topmost Base Shader, which Modo does not apply to
    any surface (render outputs, which are not layers, aside)."""
    children = list(render.children())  # bottom first
    shaders = [i for i, item in enumerate(children) if item.type == 'defaultShader']
    if not shaders:
        return set()
    return {item.id for item in children[max(shaders) + 1:] if item.type not in ('renderOutput', 'defaultShader')}


def layer_mask_target(layer,channel):
    if channel(layer,'effect','')!='layerMask' or not layer.parent:return ''
    siblings=list(reversed(list(layer.parent.children())))
    index=next((i for i,item in enumerate(siblings) if item.id==layer.id),-1)
    return siblings[index-1].id if index>0 else ''


def material_tag(item, texture=False):
    from .host import channel
    tag = None
    parent = item.parent
    while parent and parent.type != 'polyRender':
        if not channel(parent, 'enable', 1):
            return None
        if parent.type != 'mask':
            raise ValueError('unsupported shader parent ' + parent.type)
        kind, value = tag_kind(channel(parent, 'ptyp', '')), channel(parent, 'ptag', '')
        if kind == 'material' and value:
            if tag is not None and tag != value:
                return None  # Intersection of two different material tags is empty.
            tag = value
        elif kind not in ('','material') or value:
            raise ValueError('mask requires Modo evaluated membership (type=%r, tag=%r)' % (kind,value))
        parent = parent.parent
    return tag if tag is not None else ''

def texture_groups(layer, channel, stop_type='polyRender'):
    """Capture outer-to-inner scopes without flattening group masks or opacity."""
    result = []
    parent = layer.parent
    while parent and parent.type != stop_type:
        if not channel(parent, 'enable', 1) or not channel(parent, 'render', 1):
            return None
        if parent.type != 'mask':
            raise ValueError('unsupported shader parent ' + parent.type)
        blend = channel(parent, 'blend', 'normal')
        if blend not in BLENDS:raise ValueError('unsupported group blend '+str(blend))
        result.append({'id':parent.id, 'opacity':float(channel(parent,'opacity',1)), 'blend':blend,'invert':bool(channel(parent,'invert',False))})
        parent = parent.parent
    return list(reversed(result))


def collect(scene, materials, warnings, baked_effects=(), layer_filter=None, material_key=None):
    from .host import channel, color
    items = list(ordered_items(scene.renderItem))
    positions = {item.id:i for i,item in enumerate(items)}
    by_id = {item.id:item for item in items}
    ignored = above_shader(scene.renderItem)
    told = set()
    for layer in reversed(items): # Modo's upper rows are applied last.
        if layer_filter is not None and layer.id not in layer_filter:
            continue
        top = layer
        while top.parent is not None and top.parent.id != scene.renderItem.id:
            top = top.parent
        if top.id in ignored:
            # Modo shades nothing with a layer above the Base Shader (seen in its own renders): neither is it here.
            if top.id not in told and (layer.type != 'renderOutput'):
                told.add(top.id)
                warnings.append('%s is above the Base Shader, where Modo does not apply it; it is left out too. Move it below the Base Shader.' % top.name)
            continue
        if not channel(layer,'enable',1) or not channel(layer,'render',1):
            continue
        if channel(layer,'effect','') in baked_effects:
            continue
        from .procedurals import ENHANCE, SURFACE_KINDS
        # Modo's Gabor and Poisson noise are drawn through the object as Enhance: Modo's patterns are.
        SOLID_ONLY = ('val.noise.gabor', 'val.noise.poisson')
        if layer.type not in ('imageMap','constant','checker','noise','grid','dots','gradient','cellular','wood','weave','ripples') and layer.type not in ENHANCE \
                and layer.type not in SURFACE_KINDS and layer.type not in SOLID_ONLY:
            from . import properties
            # A render output says what Modo's own renderer writes; it is not a layer of any material.
            if not properties.is_material(layer) and layer.type not in ('defaultShader','mask','envMaterial','renderOutput','furMaterial') and channel(layer,'effect',None) is not None:
                try:
                    scope=material_key if layer_filter is not None else material_tag(layer,texture=True)
                    if scope in materials and texture_groups(layer,channel) is not None:
                        warnings.append('Layer %s (%s): no Shader Tree translator for effect %s; use a MoonShine graph or baked image.'%(layer.name,layer.type,channel(layer,'effect','')))
                except ValueError:pass
            continue
        try:
            if layer_filter is None:
                tag = material_tag(layer, texture=True)
            else:
                # Render Cache has already resolved selection membership.
                tag = material_key
            if tag is None:
                continue
            if tag not in materials:
                raise ValueError('mask has no translated base material')
            groups = texture_groups(layer, channel)
            if groups is None:
                continue
            base = materials[tag].get('base_layer_id')
            if base in by_id:
                base_groups = texture_groups(by_id[base], channel)
                if base_groups is None:
                    continue
                # The common material scope owns its mask; nested texture-only
                # scopes consume theirs locally when composited into that scope.
                common = 0
                while common < min(len(groups), len(base_groups)) and groups[common]['id'] == base_groups[common]['id']:
                    common += 1
                groups = groups[common:]
            mask_target=layer_mask_target(layer,channel)
            base_scope_ids={group['id'] for group in (texture_groups(by_id[base],channel) or [])} if base in by_id else set()
            if base in positions and positions[layer.id] > positions[base] and mask_target!=base and mask_target not in base_scope_ids:
                # An upper material replaces this layer's channels.
                warnings.append('Layer %s is below its material and is overridden. Move it above the material in the same Shader Tree group.' % layer.name)
                continue
            effect = channel(layer,'effect','')
            effect = textures.EFFECT_ALIASES.get(effect, effect)
            if effect not in textures.EFFECTS:
                raise ValueError('unsupported effect '+effect)
            blend = channel(layer,'blend','normal')
            if blend not in BLENDS and not (effect in ('normal','normalCoat') and blend=='normalblend'):
                raise ValueError('unsupported blend '+blend)
            node = {'identity':layer.id,'kind':layer.type, 'effect':effect, 'opacity':float(channel(layer,'opacity',1)),
                    'blend':blend, 'uv_map':'', 'invert':bool(channel(layer,'invert',0)), 'groups':groups, 'absolute_groups':texture_groups(layer,channel) or []}
            if effect=='layerMask':
                node['mask_target']=mask_target
            if effect in ('normal','normalCoat') and (blend not in ('normal','normalblend') or layer.type != 'imageMap'):
                raise ValueError('normal maps require an image and Normal or Normal Map Blend blending')
            is_color = effect in textures.COLOR_EFFECTS or effect in ('normal','normalCoat')
            if layer.type == 'gradient':
                from .gradients import capture
                node['gradient']=capture(layer,channel,is_color)
                warnings.append('Gradient '+layer.name+': evaluated at 257 samples over input 0..1; outside values clamp. Exact curve and discontinuity parity is unverified.')
            elif layer.type == 'constant':
                node['value'] = color(layer,'color',(0,0,0)) if is_color else [float(channel(layer,'value',1))]*3
            elif layer.type in SURFACE_KINDS:
                # These need no texture locator: they take what is beneath them, or the surface itself.
                from . import procedurals
                if layer.type == 'val.Process_EasyGrad.RJJ':
                    node['kind'] = 'gradient'
                    node['gradient'] = procedurals.easygrad(layer,channel,color,is_color,effect)
                    warnings.append('EasyGrad '+layer.name+': a gradient over the brightness of what is beneath it; Modo equivalence is unverified.')
                elif layer.type == 'val.Process_RegionalHSV.RJJ':
                    node['solid_map'] = procedurals.regional(layer,channel,color)
                    node['procedural'] = None
                    warnings.append('RegionalHSV '+layer.name+': each colour beneath it given its own at random; Modo equivalence is unverified.')
                elif layer.type == 'vmapTexture':
                    node['kind'] = 'gradient'
                    node['gradient'] = procedurals.vertex_map(layer,channel,color,is_color)
                elif layer.type == 'val.RTCurvature':
                    node['kind'] = 'gradient'
                    node['gradient'] = procedurals.curvature(layer,channel,is_color)
                    warnings.append('Curvature '+layer.name+': measured from the normals of the surface, triangle by triangle in MoonLightIPR; Modo equivalence is unverified.')
                else:
                    node['kind'] = 'wireframe'
                    node['wireframe'] = procedurals.wireframe(layer,channel,color,is_color)
            else:
                connected = layer.itemGraph('shadeLoc').forward()
                locator = next((i for i in connected if i.type=='txtrLocator'),None)
                if not locator:
                    raise ValueError('missing Texture Locator')
                projection = channel(locator,'projType','uv')
                solid_map = None
                if projection=='none' and layer.type!='imageMap':
                    # Solid, as Modo starts a procedural layer: the pattern runs through the object. MoonRay works it
                    # out so, at each point (procedurals.solid, ModoProceduralMap); MoonLightIPR, and a runtime
                    # without that map, lay the pattern flat from six sides, which is the nearest to it.
                    from .procedurals import solid
                    from .host import world_matrix
                    solid_map = solid(layer,channel,color,is_color,world_matrix(locator))
                    projection='cubic'
                    warnings.append('Layer %s: Solid projection%s laid on as Cubic.'%(layer.name,', drawn through the object by MoonRay; MoonLightIPR' if solid_map else ''))
                if (layer.type in ENHANCE or layer.type in SOLID_ONLY) and not solid_map:
                    raise ValueError(('Gabor and Poisson noise are' if layer.type in SOLID_ONLY else 'Enhance: Modo textures are')+' drawn with a Solid projection')
                if projection not in ('uv','planar','spherical','cylindrical','cubic'):
                    raise ValueError('unsupported projection '+projection)
                node['projection'] = projection
                node['uv_map'] = channel(locator,'uvMap','') if projection=='uv' else ''
                if projection=='uv' and not node['uv_map']:
                    raise ValueError('choose a named UV map')
                if channel(locator,'randOffset','none') != 'none':
                    raise ValueError('random UV offsets are not translated')
                node['uv_matrix'] = [float(channel(locator,k,v)) for k,v in
                    zip(('m00','m01','m02','m10','m11','m12'),(1,0,0,0,1,0))]
                node['rotation'] = float(channel(locator,'uvRotation',0))
                node['scale'] = [float(channel(locator,'wrapU',1)),float(channel(locator,'wrapV',1))]
                if projection!='uv':
                    from .host import world_matrix
                    node['locator_matrix'] = world_matrix(locator)
                    node['axis'] = channel(locator,'projAxis','z')
                    warnings.append('Locator projection is baked at polygon corners; curved projections require sufficient mesh detail: '+layer.name)
                from .group_scale import texture as scale_texture
                scale_texture(layer,node,channel)
                from .coordinates import key
                node['coordinate_key'] = key(node)
                if layer.type == 'imageMap':
                    clip = next((i for i in connected if i.type=='videoStill'),None)
                    if not clip:
                        raise ValueError('requires a still image or a <UDIM> filename')
                    from .texture_controls import capture
                    node['corrections'] = capture(layer, channel)
                    source_channel = channel(layer,'rgba','use') if channel(layer,'swizzling',0) else channel(layer,'alpha','use')
                    if source_channel not in ('use','ignore','only','red','green','blue'):
                        raise ValueError('unsupported image channel '+str(source_channel))
                    node['image_channel'] = source_channel
                    node['flip_blue'] = bool(channel(layer,'blueInv',0))
                    node['flip_red'] = bool(channel(layer,'redInv',0))
                    node['flip_green'] = bool(channel(layer,'greenInv',0))
                    tile = channel(locator,'tileU','repeat')
                    tile_v = channel(locator,'tileV','repeat')
                    if tile not in ('repeat','edge','mirror','reset') or tile_v not in ('repeat','edge','mirror','reset'):
                        raise ValueError('unsupported image repeat mode')
                    node.update(tile_u=tile,tile_v=tile_v,repeat=tile==tile_v=='repeat')
                    path,recovered = textures.resolve_scene_source(channel(clip,'filename',''),getattr(scene,'filename',None))
                    if recovered:
                        warnings.append('Relocated texture resolved for '+layer.name+': '+str(path))
                    if '<UDIM>' in path.name and (tile!='repeat' or tile_v!='repeat'):
                        raise ValueError('UDIM tile addressing requires Repeat on both axes')
                    sources = textures.source_tiles(path)
                    if not sources:
                        raise ValueError('missing image '+str(path))
                    space = channel(clip,'colorspace','(default)')
                    node.update(color_space=space if effect in textures.COLOR_EFFECTS else 'raw',path=str(path.resolve()),mtime=max(p.stat().st_mtime_ns for p in sources.values()),size=sum(p.stat().st_size for p in sources.values()),
                        tile_signature=[(n,p.stat().st_size,p.stat().st_mtime_ns) for n,p in sorted(sources.items())],
                        srgb=effect not in ('normal','normalCoat','bump','coatBump') and (space=='sRGB' or
                            (space=='(default)' and effect in textures.COLOR_EFFECTS and path.suffix.lower() not in ('.exr','.hdr','.tx'))),
                        use_alpha=source_channel=='use')
                elif layer.type in ENHANCE or layer.type in SOLID_ONLY:
                    # Enhance: Modo's patterns, and Modo's Gabor and Poisson noise, are drawn through the object by
                    # MoonRay and MoonLightIPR alike.
                    node['solid_map']=solid_map
                    node['procedural']=None
                    named=('Modo\'s '+layer.type[4:].replace('.',' ')) if layer.type in SOLID_ONLY else ('Enhance: Modo\'s '+layer.type[4:-4].replace('_',' '))
                    warnings.append('Procedural '+layer.name+': drawn in 3D after '+named+'; Modo pattern equivalence is unverified.')
                elif layer.type in ('grid','dots','cellular','wood','weave','ripples'):
                    from .procedurals import capture
                    if solid_map:node['solid_map']=solid_map
                    try:node['procedural']=capture(layer,channel,color,is_color)
                    except ValueError:
                        # A pattern only the 3D map draws (Grid's and Dots' Cube): MoonLightIPR has none of it.
                        if not solid_map:raise
                        node['procedural']=None
                    warnings.append('Procedural '+layer.name+': '+('drawn in 3D by MoonRay' if solid_map else 'sampled 2D '+layer.type+' translation')+'; Modo pattern equivalence is unverified.')
                else:
                    node.update(color1=color(layer,'color1',(0,0,0)) if is_color else [float(channel(layer,'value1',0))]*3,
                                color2=color(layer,'color2') if is_color else [float(channel(layer,'value2',1))]*3)
                    node.update(alpha1=float(channel(layer,'alpha1',1)),alpha2=float(channel(layer,'alpha2',1)))
                    node['bias'] = float(channel(layer,'bias',.5))
                    node['gain'] = float(channel(layer,'gain',.5))
                    if solid_map:node['solid_map']=solid_map
                    if layer.type=='checker' and not solid_map and (channel(layer,'type','square')!='square' or channel(layer,'variation',0)):
                        raise ValueError('only unvaried square checkers are supported')
                    if layer.type=='noise':
                        if not solid_map and (channel(layer,'type','fractal')!='fractal' or any(channel(layer,k,0) for k in ('flowNoise','angle','smoothTops'))):
                            raise ValueError('only static fractal noise is supported')
                        if solid_map and any(channel(layer,k,0) for k in ('flowNoise','angle','smoothTops')):
                            warnings.append('Noise %s: Flow Noise, Angle and Smooth Tops are not drawn.'%layer.name)
                        node.update(octaves=int(channel(layer,'freqs',4)),lacunarity=float(channel(layer,'freqRatio',2)),
                                    persistence=float(channel(layer,'ampRatio',.5)))
                        warnings.append('Noise uses a MoonRay UV fractal approximation, not the exact Modo pattern: '+layer.name)
            material = materials[tag]
            uv = node['uv_map']
            if uv and (effect in ('normal','normalCoat','bump','coatBump') or not material.get('uv_map')):
                material['uv_map'] = uv
            material.setdefault('layers',[]).append(node)
            # Keep source metadata available to existing callers and live digests.
            material.setdefault('textures',{})[effect] = node
        except (ValueError,LookupError,OSError) as exc:
            warnings.append('Layer %s: %s.' % (layer.name,exc))


def material_stack(scene, candidates, warnings, tag, membership=None):
    """Partition channel layers at material boundaries, then emit bottom to top."""
    from .host import material_values, channel
    ordered = list(ordered_items(scene.renderItem))
    positions = {item.id:i for i,item in enumerate(ordered)}
    candidates = sorted(candidates, key=lambda item:positions[item.id])
    result = []
    captured_group_masks=set()
    for index, base in reversed(list(enumerate(candidates))):
        value = material_values(base)
        value['shader'] = 'DwaBaseMaterial'
        value['material_groups'] = texture_groups(base, channel) or []
        allowed = set()
        upper = positions[candidates[index-1].id] if index else -1
        for layer in ordered[upper+1:positions[base.id]]:
            if membership is not None and layer.id not in membership:
                continue
            try:
                if membership is not None or material_tag(layer, texture=True) in (tag,''):
                    allowed.add(layer.id)
            except ValueError:
                continue
        scope_ids={group['id'] for group in value['material_groups']}
        for layer in ordered:
            target=layer_mask_target(layer,channel)
            if membership is not None and layer.id not in membership:continue
            if target==base.id:allowed.add(layer.id)
            elif target in scope_ids and layer.id not in captured_group_masks:
                allowed.add(layer.id);captured_group_masks.add(layer.id)
            elif layer.id in captured_group_masks:allowed.discard(layer.id)
        collect(scene, {tag:value}, warnings, layer_filter=allowed, material_key=tag)
        if value.get("node_override") and (value.get("node_graph") or value.get("native_shader")):
            masked=any(layer.get('effect') in ('groupMask','layerMask') for layer in value.get('layers',[]))
            groups_opaque=all(g.get('opacity',1)==1 and g.get('blend','normal')=='normal' and not g.get('invert') for g in value['material_groups'])
            inherited_masks=any(layer.get('effect') in ('groupMask','layerMask') for row in result for layer in row.get('layers',[]))
            if value.get('layer_opacity',1)==1 and not masked and not inherited_masks and groups_opaque and not value['material_groups']:
                result=[] # An opaque override can discard the hidden lower stack.
            elif not result:
                result.append({'color':[.5]*3,'shader':'DwaBaseMaterial','name':'Default surface'})
        result.append(value)
    return result
