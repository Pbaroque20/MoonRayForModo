"""Bake environment layers in linear light to a cached latitude/longitude map."""
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import uuid
from . import coordinates, native, textures


def blend(background, foreground, mode, opacity):
    def component(a,b):
        if mode=='normal': return b
        if mode=='multiply': return a*b
        if mode=='add': return a+b
        if mode=='subtract': return a-b
        if mode=='screen': return 1-(1-a)*(1-b)
        if mode=='divide': return a/max(1e-6,b)
        if mode=='difference': return abs(a-b)
        if mode=='darken': return min(a,b)
        if mode=='lighten': return max(a,b)
        if mode=='overlay': return 2*a*b if a<.5 else 1-2*(1-a)*(1-b)
        if mode=='hardlight': return 2*a*b if b<.5 else 1-2*(1-a)*(1-b)
        if mode=='exclusion': return a+b-2*a*b
        if mode=='softlight':
            d=((16*a-12)*a+4)*a if a<=.25 else math.sqrt(max(0,a))
            return a-(1-2*b)*a*(1-a) if b<=.5 else a+(2*b-1)*(d-a)
        if mode=='colordodge':return 1 if b>=1 else min(1,a/max(1e-6,1-b))
        if mode=='colorburn':return 0 if b<=0 else 1-min(1,(1-a)/max(1e-6,b))
        raise ValueError('Unsupported environment blend: '+mode)
    opacity = max(0,min(1,opacity))
    return [a+(component(a,b)-a)*opacity for a,b in zip(background,foreground)]


def alpha_index(xml):
    import xml.etree.ElementTree as ET
    start=xml.find('<ImageSpec');end=xml.find('</ImageSpec>',start)
    if start<0 or end<0:raise ValueError('Cannot read environment image metadata')
    spec=ET.fromstring(xml[start:end+len('</ImageSpec>')])
    value=spec.findtext('alpha_channel')
    if value is None:raise ValueError('Environment metadata omits alpha-channel information')
    return int(value)


def image_pixels(layer, folder, width, height):
    runtime=Path(native.default_runtime());converter=runtime/'oiiotool.exe'
    if not converter.is_file():raise ValueError('Layered environments require oiiotool.exe')
    source=textures.prepare(layer['path'],layer.get('srgb',False),mipmaps=False,color_space=layer.get('color_space',''))
    def run(args):
        result=subprocess.run([str(converter)]+args,env=native.environment(runtime),stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:raise ValueError('Environment conversion failed: '+result.stdout.decode(errors='replace')[-1000:])
        return result.stdout.decode(errors='replace')
    def read(args):
        target=folder/(uuid.uuid4().hex+'.pfm')
        try:
            run(args+['-o',str(target)])
            with target.open('rb') as stream:
                if stream.readline().strip()!=b'PF':raise ValueError('Expected RGB PFM')
                w,h=map(int,stream.readline().split());scale=float(stream.readline());data=stream.read()
                if (w,h)!=(width,height) or len(data)!=w*h*12:raise ValueError('Invalid environment pixel dimensions')
                return struct.unpack(('<' if scale<0 else '>')+'%df'%(w*h*3),data)
        finally:
            if target.exists():target.unlink()
    channel=layer.get('image_channel','use')
    if channel not in ('use','ignore','only','red','green','blue'):raise ValueError('Unsupported environment image channel')
    alpha=None
    if channel in ('use','only'):
        index=alpha_index(run(['--info:format=xml','-v',source]))
        if index>=0:
            alpha=read([source,'--ch',','.join([str(index)]*3),'--resize','%dx%d!'%(width,height)])[::3]
    args=[source,'--resize','%dx%d!'%(width,height),'--unpremult','--ch','R,G,B']
    if channel=='only':
        if alpha is None:alpha=(1.0,)*(width*height)
        # Alpha is linear data; never apply an input color transform to it.
        controls=layer.get('corrections',{});flips=layer.get('flips',[False]*3)
        def corrected(a):
            value=max(0,a)**(1/controls.get('gamma',1))
            value=((value-.5)*controls.get('contrast',1)+.5)*controls.get('brightness',1)
            return [1-value if flip else value for flip in flips]
        pixels=tuple(v for a in alpha for v in corrected(a))
        return pixels,None
    controls=layer.get('corrections',{})
    if controls.get('gamma',1)!=1:args+=['--maxc','0','--powc',str(1/controls['gamma'])]
    if controls.get('contrast',1)!=1:args+=['--subc','.5','--mulc',str(controls['contrast']),'--addc','.5']
    if controls.get('brightness',1)!=1:args+=['--mulc',str(controls['brightness'])]
    flips=layer.get('flips',[False]*3)
    if any(flips):args+=['--mulc',','.join('-1' if v else '1' for v in flips),'--addc',','.join('1' if v else '0' for v in flips)]
    if channel in ('red','green','blue'):args+=['--ch',','.join([{'red':'R','green':'G','blue':'B'}[channel]]*3)]
    return read(args),alpha


def texture(environment, width=512, height=256):
    from .environments import gradient_color
    from .daylight import color as daylight_color
    from .compositing import Groups
    from .procedurals import sample
    from .gradients import sample as gradient_sample
    if any(layer['kind']=='physical' for layer in environment['layers']):
        width,height = 256,128
    digest = hashlib.sha256(('stack-v10-daylight|%dx%d|'%(width,height)+json.dumps([environment,textures._policy.get()],sort_keys=True)).encode()).hexdigest()
    folder = Path(os.environ.get('LOCALAPPDATA',tempfile.gettempdir()))/'MoonRayForModo/Environments'
    folder.mkdir(parents=True,exist_ok=True)
    target = folder/(digest+'.pfm')
    if not target.exists():
        layers = []
        for layer in reversed(environment['layers']):
            pixels,alpha = image_pixels(layer,folder,width,height) if layer['kind']=='image' else (None,None)
            inv = coordinates.inverse(layer['matrix']) if 'matrix' in layer else None
            layers.append((layer,pixels,alpha,inv))
        staged = folder/(digest+'-'+uuid.uuid4().hex+'.pfm')
        try:
            with staged.open('wb') as out:
                out.write(('PF\n%d %d\n-1.0\n'%(width,height)).encode())
                for y in range(height):
                    latitude = ((y+.5)/height-.5)*math.pi
                    for x in range(width):
                        longitude = ((x+.5)/width-.5)*2*math.pi
                        direction = (math.sin(longitude)*math.cos(latitude), math.sin(latitude), math.cos(longitude)*math.cos(latitude))
                        pending_masks={}
                        def composite(a,b,group,mask,effect):
                            weight=group.get('opacity',1)
                            if mask is not None:weight*=sum(mask)/3
                            if group['id'] in pending_masks:weight*=sum(pending_masks[group['id']])/3
                            if group.get('invert') and effect=='envColor':b=[1-c for c in b]
                            return blend(a,b,group.get('blend','normal'),weight)
                        scopes=Groups({'envColor':[0,0,0],'groupMask':[1,1,1],**{key:[0,0,0] for key in textures.INTERNAL_EFFECTS}},None,composite)
                        for layer,pixels,alpha,inv in layers:
                            scopes.select(layer.get('groups',[]))
                            effect=layer.get('effect','envColor')
                            coverage=1.0
                            if layer['kind']=='gradient':
                                values=scopes.current[layer['gradient']['input']]
                                foreground=gradient_sample(layer['gradient'],sum(values)/3)
                                if 'alpha' in layer['gradient']:
                                    coverage=gradient_sample(dict(layer['gradient'],colors=[[v]*3 for v in layer['gradient']['alpha']]),sum(values)/3)[0]
                            elif layer['kind']=='color':
                                foreground=layer['color']
                            elif layer['kind']=='procedural':
                                d=direction if inv is None else [sum(direction[j]*inv[j*4+i] for j in range(3)) for i in range(3)]
                                length=max(1e-12,math.sqrt(sum(v*v for v in d)))
                                uv=(.5+math.atan2(d[0],d[2])/(2*math.pi),.5+math.asin(max(-1,min(1,d[1]/length)))/math.pi)
                                u,v=coordinates.transform_uv(layer,[uv])[0]
                                foreground,coverage=sample(layer['procedural'],u,v)
                            elif pixels is None:
                                # The renderers show this picture's columns from right to left of the way they are worked out here,
                                # which only a sky with a sun in it can tell.
                                foreground = daylight_color((-direction[0],direction[1],direction[2]),layer) if layer['kind']=='physical' else gradient_color(layer,direction[1])
                            else:
                                d = direction if inv is None else [sum(direction[j]*inv[j*4+i] for j in range(3)) for i in range(3)]
                                length = max(1e-12, math.sqrt(sum(v*v for v in d)))
                                uv=(.5+math.atan2(d[0],d[2])/(2*math.pi),
                                    .5+math.asin(max(-1,min(1,d[1]/length)))/math.pi)
                                u,v=coordinates.transform_uv(layer,[uv])[0]
                                u,v=u*width-.5,v*height-.5
                                ix,iy = math.floor(u),math.floor(v)
                                tx,ty = u-ix,v-iy
                                foreground = [0,0,0];coverage=0.0 if alpha is not None else 1.0
                                for dx,dy,weight in ((0,0,(1-tx)*(1-ty)),(1,0,tx*(1-ty)),(0,1,(1-tx)*ty),(1,1,tx*ty)):
                                    index = (max(0,min(height-1,iy+dy))*width+(ix+dx)%width)*3
                                    a=max(0,min(1,alpha[index//3])) if alpha is not None else 1.0
                                    if alpha is not None:coverage+=a*weight
                                    foreground = [c+pixels[index+k]*weight*a for k,c in enumerate(foreground)]
                                if alpha is not None:foreground=[c/max(1e-12,coverage) for c in foreground]
                            if layer.get('invert'): foreground = [1-c for c in foreground]
                            row_mask=pending_masks.pop(layer.get('layer_identity'),None)
                            if row_mask is not None:coverage*=sum(row_mask)/3
                            if effect=='layerMask':
                                pending_masks[layer.get('mask_target','')]=blend([1,1,1],foreground,layer.get('blend','normal'),layer.get('opacity',1)*coverage)
                            else:
                                scopes.current[effect]=blend(scopes.current[effect],foreground,layer.get('blend','normal'),layer.get('opacity',1)*coverage)
                                scopes.used.add(effect)
                        color=scopes.finish()[0]['envColor']
                        out.write(struct.pack('<3f',*color))
            staged.replace(target)
        finally:
            if staged.exists(): staged.unlink()
    return textures.prepare(target,False,mipmaps=False)
