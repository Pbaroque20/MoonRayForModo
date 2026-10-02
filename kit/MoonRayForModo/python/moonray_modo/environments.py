"""Modo environment collection and CPU EnvLight translation."""
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
    for environment in scene.items('environment', superType=False):
        if not render_visible(environment):
            continue
        intensity = float(channel(environment, 'radiance', 1))
        if intensity <= 0:
            continue
        item = {'name':environment.name, 'intensity':intensity,
                'camera':bool(channel(environment,'visCam',1)),
                'indirect':bool(channel(environment,'visInd',1)),
                'reflection':bool(channel(environment,'visRefl',1)),
                'refraction':bool(channel(environment,'visRefr',1))}
        children = [i for i in environment.children()
                    if channel(i,'enable',1) and channel(i,'render',1) and channel(i,'opacity',1)>0]
        stack = []
        for index, layer in enumerate(children):
            try:
                if channel(layer,'effect','envColor') != 'envColor':
                    raise ValueError('only Environment Color layers are supported')
                from .layers import BLENDS
                mode = channel(layer,'blend','normal')
                if mode not in BLENDS:
                    raise ValueError('unsupported environment blend '+mode)
                opacity = float(channel(layer,'opacity',1))
                entry = dict(item, opacity=opacity, blend=mode, invert=bool(channel(layer,'invert',0)))
                if layer.type == 'envMaterial':
                    kind = channel(layer,'type','grad4')
                    if kind not in ('constant','grad2','grad4','overcast','physical'):
                        raise ValueError('physical daylight is not yet translated')
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
                        from .sun import direction as sun_direction
                        entry.update(sun_direction=sun_direction(sun),
                                     normalize=bool(channel(layer,'normalize',False)),
                                     sky_gamma=max(.01,float(channel(layer,'clampedGamma',1))),
                                     haze=float(channel(sun,'haze',1)),
                                     ground_albedo=rgb(channel(layer,'albedo',.2),'Physical sky ground albedo'))
                        warnings.append('Physical daylight uses a single-scattering approximation; sun angles, linked Sun Light, haze, ground albedo and sky clamp/gamma are translated; ozone and solar-disc parity remain unverified: '+layer.name)
                    if channel(layer,'fogType','none') != 'none':
                        warnings.append('Environment fog is not translated: '+layer.name)
                elif layer.type == 'imageMap':
                    connected = layer.itemGraph('shadeLoc').forward()
                    locator = next((i for i in connected if i.type=='txtrLocator'),None)
                    clip = next((i for i in connected if i.type=='videoStill'),None)
                    if not locator or channel(locator,'projType') != 'spherical':
                        raise ValueError('environment images require Spherical projection (latitude/longitude)')
                    if not clip:
                        raise ValueError('environment images require a still image')
                    if any(channel(layer,k,v)!=v for k,v in {'gamma':1,'brightness':1,'contrast':1,
                            'swizzling':0,'redInv':0,'greenInv':0,'blueInv':0}.items()):
                        raise ValueError('environment image color corrections are unsupported')
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
                    if space not in ('(default)','(none)','sRGB','Linear','linear'):
                        raise ValueError('unsupported color space '+space)
                    entry.update(kind='image',path=str(path.resolve()),mtime=path.stat().st_mtime_ns,
                        size=path.stat().st_size, matrix=world_matrix(locator),
                        srgb=space=='sRGB' or (space=='(default)' and path.suffix.lower() not in ('.exr','.hdr','.tx')))
                else:
                    raise ValueError('unsupported environment layer type '+layer.type)
                stack.append(entry)
                if opacity==1 and mode=='normal':
                    break
            except (ValueError, LookupError, OSError) as exc:
                warnings.append('Environment %s: %s.' % (layer.name,exc))
        if stack:
            if len(stack)==1 and stack[0]['kind']!='physical' and stack[0]['opacity']==1 and stack[0]['blend']=='normal' and not stack[0]['invert'] and not stack[0].get('transformed'):
                result.append(stack[0])
            else:
                result.append(dict(item,kind='stack',layers=stack))
    return result


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
    folder=Path(os.environ.get('LOCALAPPDATA',tempfile.gettempdir()))/'MoonRayForModo/Environments'
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
    return textures.prepare(target,False,mipmaps=False)


def emit(environments, lines):
    from .rdla import string,number,vector,matrix
    for index,environment in enumerate(environments):
        attributes={'intensity':number(environment['intensity']),
                    'visible_in_camera':'1' if environment.get('camera',True) else '0'}
        for lobe,visible in [('diffuse_reflection','indirect'),('diffuse_transmission','indirect'),
                             ('glossy_reflection','reflection'),('mirror_reflection','reflection'),
                             ('glossy_transmission','refraction'),('mirror_transmission','refraction')]:
            attributes['visible_'+lobe]='true' if environment.get(visible,True) else 'false'
        if environment['kind']=='stack':
            from .environment_layers import texture
            attributes['texture'] = string(texture(environment))
            attributes['texture_filter'] = '1'
        elif environment['kind']=='constant':
            attributes['color']=vector(environment['zenith'],'Rgb')
        else:
            path=(textures.prepare(environment['path'],environment.get('srgb',False),mipmaps=False)
                  if environment['kind']=='image' else gradient_texture(environment))
            attributes['texture']=string(path)
            # EnvLight's importance distribution rejects the terminal 1x1 mip.
            # Use a full-resolution tiled image with bilinear filtering.
            attributes['texture_filter']='1'
        if 'matrix' in environment:
            attributes['node_xform']=matrix(environment['matrix'])
        lines.append('table.insert(lights, EnvLight("/modo/environment/scene/%d") {' % index)
        lines.extend('  [%s] = %s,' % (string(k),v) for k,v in attributes.items())
        lines.append('})')
