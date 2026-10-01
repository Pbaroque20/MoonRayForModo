"""Native CPU environment tests: colors, visibility, gradients and HDR range."""
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
root=Path(__file__).resolve().parents[1]
modo=Path(r'C:\Program Files\Modo16.1v9\modo'); extra=modo/'resrc/python3kit/extra64'
sys.path[:0]=[str(root/'kit/MoonRayForModo/python'),str(extra/'Python/Scripts')]
dlls=[os.add_dll_directory(str(p)) for p in (modo,extra)]
from PySide2 import QtGui
from moonray_modo import rdla,environments
from moonray_modo import native
folder=root/'test-results/environment';folder.mkdir(parents=True,exist_ok=True)
runtime=root/'runtime/native-avx'
scene={'camera':{'matrix':rdla.IDENTITY,'focal_mm':35,'film_mm':36},
    'materials':{'':{'shader':'DwaBaseMaterial','color':[.8,.8,.8],'specular_amount':0}},
    'meshes':[{'name':'plane','vertices':[[-.5,-.5,-3],[.5,-.5,-3],[.5,.5,-3],[-.5,.5,-3]],
               'faces':[[0,1,2,3]]}], 'lights':[]}
env={'kind':'constant','intensity':1,'zenith':[.2,.1,.05],'nadir':[.05,.1,.2],
     'sky':[.1,.1,.1],'ground':[.02,.02,.02],'sky_exponent':4,'ground_exponent':4,
     'camera':True,'reflection':True,'refraction':True,'indirect':True}
scene['environments']=[env]
pics={}
def render(name,mode='vectorized'):
    path,output=folder/(name+'.rdla'),folder/(name+'.png')
    path.write_text(rdla.scene_text(scene,96,96,4,0))
    with (folder/(name+'.log')).open('w') as log:
        result=subprocess.run([str(runtime/'moonray.exe')]+native.arguments(path,output,2,mode),
            env=native.environment(runtime),stdout=log,stderr=subprocess.STDOUT,timeout=90,
            creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode==0,name
    assert 'Warning (lib.render)' not in (folder/(name+'.log')).read_text(),name
    pic=QtGui.QImage(str(output));assert not pic.isNull()
    pics[name]=pic
    print('Rendered',name,flush=True)
    return pic
base=render('constant');corner=base.pixelColor(4,4)
assert corner.red()>corner.green()>corner.blue()>0,corner.getRgb()
env['intensity']=2
bright=render('double-intensity').pixelColor(4,4)
assert abs(bright.red()-2*corner.red())<3,(corner.getRgb(),bright.getRgb())
env['intensity']=1;env['camera']=False
hidden=render('camera-hidden')
assert hidden.pixelColor(4,4).red()==0
assert hidden.pixelColor(48,48).red()>10, 'Camera hiding also removed illumination'
env['indirect']=False
dark=render('diffuse-hidden')
assert dark.pixelColor(48,48).red()<3
env['indirect']=True;env['camera']=True
for kind in ('grad2','grad4','overcast'):
    env['kind']=kind
    pic=render(kind)
    assert pic.pixelColor(4,4).getRgb()!=pic.pixelColor(4,90).getRgb(),kind
    assert max(abs(a-b) for a,b in zip(environments.gradient_color(env,1),env['zenith']))<1e-6
    assert max(abs(a-b) for a,b in zip(environments.gradient_color(env,-1),env['nadir']))<1e-6
env.update(kind='constant',camera=False)
scene['materials']['']={'shader':'DwaBaseMaterial','color':[0,0,0],
    'specular_amount':1,'roughness':0,'ior':1.5}
reflection=render('reflection-on').pixelColor(48,48).red()
env['reflection']=False
assert render('reflection-off').pixelColor(48,48).red()<reflection,reflection
env['reflection']=True
scene['materials'][''].update(transmission=1,thin_geometry=True,specular_amount=0)
refraction=render('refraction-on').pixelColor(48,48).red()
env['refraction']=False
assert render('refraction-off').pixelColor(48,48).red()<refraction,refraction
env['refraction']=True;env['camera']=True
source=folder/'hdr-quadrants.pfm'
with source.open('wb') as out:
    out.write(b'PF\n128 64\n-1.0\n')
    for y in range(64):
        for x in range(128):
            out.write(struct.pack('<3f',*([4,0,0] if x<64 else [0,4,0])))
env.update(kind='image',path=str(source),srgb=False,intensity=.1,matrix=list(rdla.IDENTITY))
original=render('hdr-image')
# Rotate the locator 180 degrees around Y: the opposite image half must appear.
env['matrix']=[-1,0,0,0,0,1,0,0,0,0,-1,0,0,0,0,1]
rotated=render('hdr-rotated')
assert original.pixelColor(4,4).getRgb()!=rotated.pixelColor(4,4).getRgb()
assert max(original.pixelColor(4,4).getRgb()[:3])>80, 'HDR radiance was clipped to one'
scalar=render('hdr-scalar','scalar')
delta=sum(abs(rotated.pixelColor(x,y).getRgb()[c]-scalar.pixelColor(x,y).getRgb()[c])
    for y in range(96) for x in range(96) for c in range(3))/(96*96*3)
assert delta<3,delta
(folder/'render.json').write_text(json.dumps({'passed':True,'intensity':True,'camera_visibility':True,
    'diffuse_visibility':True,'reflection_visibility':True,'refraction_visibility':True,
    'gradients':True,'hdr_range':True,'rotation':True,'scalar_avx_difference':delta},indent=2))
print('Native CPU environment checks passed')
