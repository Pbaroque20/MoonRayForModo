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
        raise ValueError('Unsupported environment blend: '+mode)
    opacity = max(0,min(1,opacity))
    return [a+(component(a,b)-a)*opacity for a,b in zip(background,foreground)]


def image_pixels(layer, folder, width, height):
    runtime = Path(native.default_runtime())
    converter = runtime/'oiiotool.exe'
    if not converter.is_file():
        raise ValueError('Layered environments require oiiotool.exe in the MoonRay runtime')
    # prepare performs the same explicit color conversion as material maps.
    source = textures.prepare(layer['path'],layer.get('srgb',False),mipmaps=False,color_space=layer.get('color_space',''))
    target = folder/(uuid.uuid4().hex+'.pfm')
    try:
        command = [str(converter),source,'--ch','R,G,B','--resize','%dx%d!'%(width,height),'-o',str(target)]
        result = subprocess.run(command,env=native.environment(runtime),stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:
            raise ValueError('Environment conversion failed: '+result.stdout.decode(errors='replace')[-1000:])
        with target.open('rb') as stream:
            if stream.readline().strip()!=b'PF': raise ValueError('Expected RGB PFM')
            w,h = map(int,stream.readline().split())
            scale = float(stream.readline())
            if (w,h)!=(width,height): raise ValueError('Unexpected environment dimensions')
            data = stream.read()
            if len(data)!=w*h*12: raise ValueError('Invalid environment pixel data')
            pixels = struct.unpack(('<' if scale<0 else '>')+'%df'%(w*h*3),data)
        return pixels
    finally:
        if target.exists(): target.unlink()


def texture(environment, width=512, height=256):
    from .environments import gradient_color
    from .daylight import color as daylight_color
    if any(layer['kind']=='physical' for layer in environment['layers']):
        width,height = 256,128
    digest = hashlib.sha256(('stack-v3|%dx%d|'%(width,height)+json.dumps([environment,textures._policy.get()],sort_keys=True)).encode()).hexdigest()
    folder = Path(os.environ.get('LOCALAPPDATA',tempfile.gettempdir()))/'MoonRayForModo/Environments'
    folder.mkdir(parents=True,exist_ok=True)
    target = folder/(digest+'.pfm')
    if not target.exists():
        layers = []
        for layer in reversed(environment['layers']):
            pixels = image_pixels(layer,folder,width,height) if layer['kind']=='image' else None
            inv = coordinates.inverse(layer['matrix']) if 'matrix' in layer else None
            layers.append((layer,pixels,inv))
        staged = folder/(digest+'-'+uuid.uuid4().hex+'.pfm')
        try:
            with staged.open('wb') as out:
                out.write(('PF\n%d %d\n-1.0\n'%(width,height)).encode())
                for y in range(height):
                    latitude = ((y+.5)/height-.5)*math.pi
                    for x in range(width):
                        longitude = ((x+.5)/width-.5)*2*math.pi
                        direction = (math.sin(longitude)*math.cos(latitude), math.sin(latitude), math.cos(longitude)*math.cos(latitude))
                        color = [0,0,0]
                        for layer,pixels,inv in layers:
                            if pixels is None:
                                foreground = daylight_color(direction,layer) if layer['kind']=='physical' else gradient_color(layer,direction[1])
                            else:
                                d = direction if inv is None else [sum(direction[j]*inv[j*4+i] for j in range(3)) for i in range(3)]
                                length = max(1e-12, math.sqrt(sum(v*v for v in d)))
                                uv=(.5+math.atan2(d[0],d[2])/(2*math.pi),
                                    .5+math.asin(max(-1,min(1,d[1]/length)))/math.pi)
                                u,v=coordinates.transform_uv(layer,[uv])[0]
                                u,v=u*width-.5,v*height-.5
                                ix,iy = math.floor(u),math.floor(v)
                                tx,ty = u-ix,v-iy
                                foreground = [0,0,0]
                                for dx,dy,weight in ((0,0,(1-tx)*(1-ty)),(1,0,tx*(1-ty)),(0,1,(1-tx)*ty),(1,1,tx*ty)):
                                    index = (max(0,min(height-1,iy+dy))*width+(ix+dx)%width)*3
                                    foreground = [c+pixels[index+k]*weight for k,c in enumerate(foreground)]
                            if layer['kind']=='physical' and layer.get('normalize'):
                                foreground=[min(1,max(0,c))**(1/layer.get('sky_gamma',1)) for c in foreground]
                            if layer.get('invert'): foreground = [1-c for c in foreground]
                            color = blend(color,foreground,layer.get('blend','normal'),layer.get('opacity',1))
                        out.write(struct.pack('<3f',*color))
            staged.replace(target)
        finally:
            if staged.exists(): staged.unlink()
    return textures.prepare(target,False,mipmaps=False)
