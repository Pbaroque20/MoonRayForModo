"""Modo environment collection and CPU EnvLight translation."""
from .cache_folder import root as cache_root
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import tempfile
import uuid
from . import textures
from .channel_values import rgb


def collect(scene, warnings):
    from .host import channel, color, world_matrix, render_visible
    result = []
    # Where the preferences say to follow Modo, the environment lights the scene only with Global Illumination on
    # in the Render item: it is seen as the backdrop and in reflections all the same.
    lights = True
    try:
        from .preferences import Preferences
        if Preferences().get('environment_lighting') == 'modo':
            lights = bool(channel(scene.renderItem, 'globEnable', 1))
    except Exception:
        lights = True
    for environment in scene.items('environment', superType=False):
        if not render_visible(environment):
            continue
        intensity = float(channel(environment, 'radiance', 1))
        if intensity <= 0:
            continue
        item = {'identity':environment.id,'name':environment.name, 'intensity':intensity,
                'camera':bool(channel(environment,'visCam',1)),
                'indirect':bool(channel(environment,'visInd',1)) and lights,
                'reflection':bool(channel(environment,'visRefl',1)),
                'refraction':bool(channel(environment,'visRefr',1))}
        from .layers import ordered_items,texture_groups
        children = [i for i in ordered_items(environment) if i.type!='mask'
                    and channel(i,'enable',1) and channel(i,'render',1) and channel(i,'opacity',1)>0]
        stack = []
        for index, layer in enumerate(children):
            try:
                effect=channel(layer,'effect','envColor')
                if effect not in {'envColor','groupMask','layerMask'}|textures.INTERNAL_EFFECTS:
                    raise ValueError('unsupported environment effect '+str(effect))
                scopes=texture_groups(layer,channel,stop_type='environment')
                if scopes is None:continue
                parent=layer.parent
                while parent and parent.type!='environment':
                    if channel(parent,'ptag','') or parent.itemGraph('shadeLoc').forward():
                        raise ValueError('Item/tag masks cannot be evaluated on a direction-only environment')
                    parent=parent.parent
                from .layers import BLENDS
                mode = channel(layer,'blend','normal')
                if mode not in BLENDS:
                    raise ValueError('unsupported environment blend '+mode)
                opacity = float(channel(layer,'opacity',1))
                entry = dict(item, layer_identity=layer.id, effect=effect, groups=scopes, opacity=opacity, blend=mode, invert=bool(channel(layer,'invert',0)))
                if effect=='layerMask':
                    siblings=list(reversed(list(layer.parent.children())))
                    above=next(i for i,v in enumerate(siblings) if v.id==layer.id)-1
                    entry['mask_target']=siblings[above].id if above>=0 else ''
                if layer.type == 'envMaterial':
                    kind = channel(layer,'type','grad4')
                    if kind not in ('constant','grad2','grad4','overcast','physical'):
                        raise ValueError('unsupported environment material type '+str(kind))
                    entry.update(kind=kind,zenith=color(layer,'zenColor'),sky=color(layer,'skyColor'),
                        ground=color(layer,'gndColor'),nadir=color(layer,'nadColor'),
                        sky_exponent=float(channel(layer,'skyExp',4)),
                        ground_exponent=float(channel(layer,'gndExp',4)))
                    if kind=='physical':
                        from . import properties
                        sun_id = properties.read(environment).get('sun_item')
                        linked=[item for item in layer.itemGraph('shadeLoc').forward() if item.type=='sunLight']
                        suns = [scene.item(sun_id)] if sun_id else linked or list(scene.items('sunLight',superType=False))
                        if len(suns)!=1:
                            raise ValueError('physical sky requires one Sun Light or an explicit MoonRay sun_item setting')
                        sun = suns[0]
                        if not render_visible(sun):
                            # A sky lit by a sun that is hidden is dark: no sun, so no daylight either.
                            black=[0.0,0.0,0.0]
                            entry.update(kind='constant',zenith=black,sky=black,ground=black,nadir=black,dark=True)
                            warnings.append('The physical sky of %s is dark: its sun, %s, is hidden.'%(environment.name,sun.name))
                    if entry['kind']=='physical':
                        from .sun import direction as sun_direction
                        entry.update(sun_direction=sun_direction(sun),
                                     normalize=bool(channel(layer,'normalize',False)),
                                     sky_gamma=max(.01,float(channel(layer,'clampedGamma',1))),
                                     haze=float(channel(sun,'haze',1)),
                                     ground_albedo=rgb(channel(layer,'albedo',.2),'Physical sky ground albedo'))
                        # The solar disc is the sun light itself, seen by the camera; see host.solar_discs.
                        entry.update(sun_identity=sun.id,solar_disc=max(0.0,float(channel(layer,'disc',1))),
                                     inscatter=min(1.0,max(0.0,float(channel(layer,'inscatter',0)))))
                elif layer.type=='gradient':
                    from .gradients import capture
                    data=capture(layer,channel,effect=='envColor')
                    if data['input'] not in textures.INTERNAL_EFFECTS|{'groupMask'}:raise ValueError('Environment gradient requires a Driver or Group Mask input')
                    entry.update(kind='gradient',gradient=data)
                    warnings.append('Environment gradient '+layer.name+': sampled over 0..1; outside values clamp.')
                elif layer.type=='constant':
                    entry.update(kind='color',color=color(layer,'color',(0,0,0)) if effect=='envColor' else [float(channel(layer,'value',1))]*3)
                elif layer.type in ('grid','dots'):
                    from .procedurals import capture
                    entry.update(kind='procedural',procedural=capture(layer,channel,color,effect=='envColor'))
                    locator=next((i for i in layer.itemGraph('shadeLoc').forward() if i.type=='txtrLocator'),None)
                    if not locator or channel(locator,'projType')!='spherical':raise ValueError('Environment procedurals require a spherical Texture Locator')
                    entry.update(matrix=world_matrix(locator),scale=[float(channel(locator,'wrapU',1)),float(channel(locator,'wrapV',1))],rotation=float(channel(locator,'uvRotation',0)),
                        uv_matrix=[float(channel(locator,k,v)) for k,v in zip(('m00','m01','m02','m10','m11','m12'),(1,0,0,0,1,0))])
                elif layer.type == 'imageMap':
                    connected = layer.itemGraph('shadeLoc').forward()
                    locator = next((i for i in connected if i.type=='txtrLocator'),None)
                    clip = next((i for i in connected if i.type=='videoStill'),None)
                    if not locator or channel(locator,'projType') != 'spherical':
                        raise ValueError('environment images require Spherical projection (latitude/longitude)')
                    if not clip:
                        raise ValueError('environment images require a still image')
                    from .texture_controls import capture
                    # Kept only where they change something: neutral ones would send a plain HDRI to the layered path.
                    corrections=capture(layer,channel)
                    if corrections!={'gamma':1.0,'brightness':1.0,'contrast':1.0}:entry['corrections']=corrections
                    entry['image_channel']=channel(layer,'rgba','use') if channel(layer,'swizzling',0) else channel(layer,'alpha','use')
                    entry['flips']=[bool(channel(layer,c+'Inv',0)) for c in ('red','green','blue')]
                    if channel(locator,'randOffset','none')!='none':
                        raise ValueError('environment random offsets are unsupported')
                    entry.update(uv_matrix=[float(channel(locator,k,v)) for k,v in zip(
                        ('m00','m01','m02','m10','m11','m12'),(1,0,0,0,1,0))],
                        rotation=float(channel(locator,'uvRotation',0)),
                        scale=[float(channel(locator,'wrapU',1)),float(channel(locator,'wrapV',1))])
                    entry['transformed']=entry['uv_matrix']!=[1,0,0,0,1,0] or entry['rotation']!=0 or entry['scale']!=[1,1]
                    path = Path(channel(clip,'filename',''))
                    if not path.is_absolute() and getattr(scene,'filename',None):
                        path = Path(scene.filename).parent/path
                    if not path.is_file():
                        raise ValueError('missing image '+str(path))
                    space = channel(clip,'colorspace','(default)')
                    if entry['image_channel']=='use':
                        # Modo's image layers use their alpha by default; an image with none (any HDR) has nothing to use.
                        from .environment_layers import has_alpha
                        if not has_alpha(path):entry['image_channel']='ignore'
                    entry.update(kind='image',color_space=space,path=str(path.resolve()),mtime=path.stat().st_mtime_ns,
                        size=path.stat().st_size, matrix=world_matrix(locator),
                        srgb=space=='sRGB' or (space=='(default)' and path.suffix.lower() not in ('.exr','.hdr','.tx')))
                    flips=flipped_across(entry)
                    if flips:
                        # Horizontal or Vertical Wrap -1 (or both), nothing else changed: the image mirrored at its full
                        # size (mirrored_image), rather than baked small with the layered environments, which smeared an
                        # HDRI's sun and lit the scene wrongly; and a vertical flip there smeared the top row over the sky.
                        mirrored=mirrored_image(path,*flips)
                        entry.update(path=str(mirrored),mtime=mirrored.stat().st_mtime_ns,size=mirrored.stat().st_size,
                                     scale=[1.0,1.0],transformed=False,mirrored_from=str(path.resolve()))
                else:
                    raise ValueError('unsupported environment layer type '+layer.type)
                stack.append(entry)
                # Keep lower rows: nested groups and Layer Masks can expose them.
            except (ValueError, LookupError, OSError) as exc:
                warnings.append('Environment %s: %s.' % (layer.name,exc))
        if len(stack)>1 and covers(stack[0]) and not any(layer.get('groups') or layer.get('effect')!='envColor' for layer in stack):
            # An opaque image on top hides every layer under it (as an HDRI over Modo's own environment material):
            # it is the environment alone, sent whole rather than baked with what cannot be seen.
            stack=stack[:1]
        if stack:
            if len(stack)==1 and not stack[0].get('groups') and stack[0].get('effect')=='envColor' and stack[0]['kind'] not in ('physical','color','procedural','gradient') and stack[0]['opacity']==1 and stack[0]['blend']=='normal' and not stack[0]['invert'] and not stack[0].get('transformed') and not stack[0].get('corrections') and not any(stack[0].get('flips') or []) and stack[0].get('image_channel','ignore') not in ('use','only'):
                result.append(stack[0])
            else:
                result.append(dict(item,kind='stack',layers=stack))
    return result


def flipped_across(entry):
    """(across, down) where an environment image's placement is a flip alone: Horizontal Wrap -1 mirrors it left to right,
    Vertical Wrap -1 top to bottom, either or both at 1 or -1, with no rotation and no other transform; None otherwise.
    u * -1, wrapped, is the image mirrored; so is v (the bake clamped v instead, and smeared the top row over the sky)."""
    scale=[float(v) for v in entry.get('scale',[1,1])]
    if (len(scale)!=2 or any(v not in (1.0,-1.0) for v in scale) or scale==[1.0,1.0]
            or [float(v) for v in entry.get('uv_matrix',[1,0,0,0,1,0])]!=[1,0,0,0,1,0] or float(entry.get('rotation',0))!=0):
        return None
    return (scale[0]==-1.0,scale[1]==-1.0)


def mirrored_image(path,across=True,down=False):
    """An image mirrored left to right (across) and or top to bottom (down) at its full size, made once with the runtime's oiiotool and kept in the texture
    cache, named by the image's path, size and time: an HDR one (.hdr, .exr, .tx) as a float EXR, any other as a PNG of
    its own depth, so that how its colours are read does not change."""
    from . import native
    import subprocess
    path=Path(path).resolve();stat=path.stat()
    # A left-to-right mirror keeps the name it was first cached under.
    kind='mirrored-v1' if (across,down)==(True,False) else 'mirrored-v1-%d%d'%(across,down)
    key=hashlib.sha256(repr((str(path),stat.st_size,stat.st_mtime_ns,kind)).encode('utf-8')).hexdigest()
    hdr=path.suffix.lower() in ('.exr','.hdr','.tx')
    folder=cache_root()/'Textures';folder.mkdir(parents=True,exist_ok=True)
    target=folder/(key+('.exr' if hdr else '.png'))
    if target.is_file() and target.stat().st_size:return target
    tool=native.tool('oiiotool.exe')
    staged=folder/(key+'-'+uuid.uuid4().hex+target.suffix)
    try:
        result=subprocess.run([str(tool),str(path)]+(['--flop'] if across else [])+(['--flip'] if down else [])+(['-d','float'] if hdr else [])+['-o',str(staged)],env=native.environment(tool.parent),
                              stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=600,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode or not staged.is_file():raise ValueError('Could not mirror the environment image %s: %s'%(path.name,result.stdout[-600:]))
        staged.replace(target)
    finally:
        if staged.exists():staged.unlink()
    return target


def covers(layer):
    """Whether an environment layer hides all under it: an image seen whole, opaque, with no alpha of its own."""
    return (layer.get('kind')=='image' and layer.get('effect')=='envColor' and layer.get('opacity')==1 and layer.get('blend')=='normal'
            and not layer.get('invert') and layer.get('image_channel','ignore') not in ('use','only') and not layer.get('groups'))


def gradient_color(environment, height):
    """Y-up approximation of Modo's gradient controls; linear scene colors."""
    kind=environment['kind']; height=max(-1,min(1,height))
    zenith,nadir=environment['zenith'],environment['nadir']
    if kind=='constant': return zenith
    if kind=='overcast': return [v*(1+2*height)/3 for v in zenith] if height>=0 else nadir
    if kind=='grad2': a,b,t=nadir,zenith,(height+1)/2
    elif height>=0:
        a,b=environment['sky'],zenith
        t=1-(1-height)**max(.001,environment['sky_exponent'])
    else:
        a,b=environment['ground'],nadir
        t=1-(1+height)**max(.001,environment['ground_exponent'])
    return [x+(y-x)*t for x,y in zip(a,b)]


def gradient_texture(environment):
    values={k:environment[k] for k in ('kind','zenith','sky','ground','nadir','sky_exponent','ground_exponent')}
    digest=hashlib.sha256(('gradient-v1|'+json.dumps(values,sort_keys=True)).encode()).hexdigest()
    folder=cache_root() / 'Environments'
    folder.mkdir(parents=True,exist_ok=True)
    target=folder/(digest+'.pfm')
    if not target.is_file():
        staged=folder/(digest+'-'+uuid.uuid4().hex+'.pfm')
        try:
            with staged.open('wb') as out:
                out.write(b'PF\n512 256\n-1.0\n')
                # PFM stores rows bottom-up, so the first row is the nadir.
                for y in range(256):
                    height=math.sin(((y+.5)/256-.5)*math.pi)
                    out.write(struct.pack('<3f',*gradient_color(environment,height))*512)
            staged.replace(target)
        finally:
            if staged.exists(): staged.unlink()
    return textures.prepare(target,False,mipmaps=False,light=True)


def emit(environments, lines):
    from .rdla import string,number,vector,matrix
    from .working_space import color as working_color,texture as working_texture
    for index,environment in enumerate(environments):
        attributes={'intensity':number(environment['intensity']),'label':string('modo_environment'),
                    'visible_in_camera':'1' if environment.get('camera',True) else '0'}
        for lobe,visible in [('diffuse_reflection','indirect'),('diffuse_transmission','indirect'),
                             ('glossy_reflection','reflection'),('mirror_reflection','reflection'),
                             ('glossy_transmission','refraction'),('mirror_transmission','refraction')]:
            attributes['visible_'+lobe]='true' if environment.get(visible,True) else 'false'
        if environment['kind']=='stack':
            from .environment_layers import held_placement,texture
            held=held_placement(environment) if 'matrix' not in environment else None
            if held:
                # Baked at rest once; turning it turns the light (environment_layers.held_placement).
                baked,placement=held
                attributes['texture'] = string(textures.register(working_texture(texture(baked))))
                attributes['node_xform'] = matrix(placement)
            else:
                attributes['texture'] = string(textures.register(working_texture(texture(environment))))
            attributes['texture_filter'] = '1'
        elif environment['kind']=='constant':
            attributes['color']=vector(working_color(environment['zenith']),'Rgb')
        else:
            path=(textures.prepare(environment['path'],environment.get('srgb',False),mipmaps=False,color_space=environment.get('color_space',''),light=True)
                  if environment['kind']=='image' else gradient_texture(environment))
            attributes['texture']=string(textures.register(working_texture(path)))
            # EnvLight's importance distribution rejects the terminal 1x1 mip.
            # Use a full-resolution tiled image with bilinear filtering.
            attributes['texture_filter']='1'
        if 'matrix' in environment:
            placed=environment['matrix']
            if environment['kind']=='image':
                # MoonRay's environment light shows a latitude-longitude image half a turn about the vertical from
                # where Modo's spherical projection puts it (tools/probe_hdri_turn.py): turned so in its own space first.
                placed=[-v for v in placed[0:4]]+list(placed[4:8])+[-v for v in placed[8:12]]+list(placed[12:16])
            attributes['node_xform']=matrix(placed)
        lines.append('table.insert(lights, EnvLight("/modo/environment/scene/%d") {' % index)
        lines.extend('  [%s] = %s,' % (string(k),v) for k,v in attributes.items())
        lines.append('})')
