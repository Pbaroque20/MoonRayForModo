"""Deferred real-render feature checks. Requires rebuilt/staged native shaders.

Each group creates independent fixtures and retains images, logs and a report.
This checks visible feature response, not equivalence to Modo's renderer.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('feature',choices=['materials','textures','geometry','environments','rendering'])
parser.add_argument('--runtime',type=Path,default=root/'runtime/native-avx')
args=parser.parse_args()
modo=Path(r'C:\Program Files\Modo16.1v9\modo')
extra=modo/'resrc/python3kit/extra64'
sys.path[:0]=[str(extra/'Python/Scripts'),str(root/'kit/MoonRayForModo/python')]
handles=[os.add_dll_directory(str(p)) for p in (modo,extra)]
from PySide2 import QtGui
from moonray_modo import native,rdla
folder=root/'test-results/cpu-features'/args.feature
folder.mkdir(parents=True,exist_ok=True)
vertices=[[-.7,-.7,-3.7],[.7,-.7,-3.7],[.7,.7,-3.7],[-.7,.7,-3.7],
          [-.7,-.7,-2.3],[.7,-.7,-2.3],[.7,.7,-2.3],[-.7,.7,-2.3]]
faces=[[0,3,2,1],[4,5,6,7],[0,1,5,4],[3,7,6,2],[0,4,7,3],[1,2,6,5]]
base={'camera':{'matrix':rdla.IDENTITY,'focal_mm':35,'film_mm':36},
      'materials':{'':{'shader':'DwaBaseMaterial','color':[.7,.4,.2],'roughness':.25}},
      'meshes':[{'name':'closed cube','vertices':vertices,'faces':faces,'smooth':False,
                 'uvs':[[0,0],[1,0],[1,1],[0,1]]*6}]}
cases={}
def case(name):
    cases[name]=copy.deepcopy(base)
    return cases[name]

case('reference')
if args.feature=='materials':
    case('subsurface')['materials'][''].update(subsurface_amount=1,subsurface_distance=.5,subsurface_color=[1,.1,.05])
    for name,amount in [('mapped_surface',0),('mapped_subsurface',1)]:
        case(name)['materials'][''].update(subsurface_amount=0,subsurface_distance=.5,
            layers=[{'kind':'constant','effect':'subsAmount','value':[amount]*3},
                    {'kind':'constant','effect':'subsColor','value':[1,.05,.02]}])
    glass={'color':[1,1,1],'transmission':1,'ior':1.5,'absorption_distance':.2,
           'transmission_color':[.1,.8,.2]}
    case('layered_absorption')['materials']['']['material_stack']=[glass,dict(glass,roughness=.3,layer_opacity=.5)]
    case('layers')['materials']['']['material_stack']=[{'color':[1,0,0]},{'color':[0,0,1],'layer_opacity':.8}]
    for name,distance in [('clear',0),('absorption',.1)]:
        case(name)['materials'][''].update(transmission=1,ior=1.5,transmission_color=[.1,.8,.2],absorption_distance=distance)
    case('anisotropy')['materials'][''].update(metallic=1,anisotropy=.8)
elif args.feature=='textures':
    for tile,color in ((1001,(255,0,0)),(1002,(0,255,0))):
        (folder/('tile.%d.ppm'%tile)).write_bytes(b'P6\n8 8\n255\n'+bytes(color)*64)
    for name,u in [('tile_one',0),('tile_two',1)]:
        value=case(name)
        value['materials']['']['layers']=[{'kind':'imageMap','effect':'diffCol','path':str(folder/'tile.<UDIM>.ppm'),
                                         'srgb':True,'coordinate_key':'named','scale':[1,1]}]
        value['meshes'][0]['uv_sets']={'named':[[u+.1,.1],[u+.9,.1],[u+.9,.9],[u+.1,.9]]*6}
    # Asymmetric RGBA fixture exposes mirroring, clipping, and channel routing.
    header=bytearray(18);header[2]=2;header[12]=16;header[14]=16;header[16]=32;header[17]=0x28
    rgba=bytes(component for y in range(16) for x in range(16)
               for component in (192,48,16+x*15,32+y*14))
    packed=folder/'packed.tga';packed.write_bytes(bytes(header)+rgba)
    for mode in ('repeat','mirror','edge','reset'):
        value=case('wrap_'+mode)
        value['materials']['']['layers']=[{'kind':'imageMap','effect':'diffCol','path':str(packed),
            'coordinate_key':'named','tile_u':mode,'tile_v':'edge','image_channel':'ignore'}]
        value['meshes'][0]['uv_sets']={'named':[[-.4,.1],[1.8,.1],[1.8,.9],[-.4,.9]]*6}
    for channel in ('red','green','only','use','ignore'):
        value=case('channel_'+channel)
        value['materials']['']['layers']=[{'kind':'imageMap','effect':'diffCol',
            'path':str(packed),'image_channel':channel}]
elif args.feature=='geometry':
    case('smooth')['meshes'][0].update(subdivision=True,smooth=True)
    value=case('creased'); value['meshes'][0].update(subdivision=True,smooth=True,creases=[[4,5,8],[5,6,8],[6,7,8],[7,4,8]])
    transform=list(rdla.IDENTITY);transform[12]=1
    case('instances')['meshes'][0]['instances']=[rdla.IDENTITY,transform]
elif args.feature=='environments':
    common={'intensity':1,'kind':'stack','layers':[{'kind':'constant','zenith':[1,0,0],'opacity':.5,'blend':'normal'},
                                               {'kind':'constant','zenith':[0,0,1],'opacity':1,'blend':'normal'}]}
    case('layered')['environments']=[common]
    other=copy.deepcopy(common);other['layers'][0]['opacity']=1
    case('opaque')['environments']=[other]
elif args.feature=='rendering':
    case('orthographic')['camera'].update(projection='ortho',ortho_width=4)
    case('region')['region']=[.25,.25,.75,.75]
    moving=case('motion');moving['motion_steps']=[-.25,.25]
    moving['meshes'][0]['vertices_close']=[[x+1,y,z] for x,y,z in vertices]

report={'passed':False,'level':'real renderer response; Modo parity not established','cases':{}}
pixels={}
try:
    for name,value in cases.items():
        source=folder/(name+'.rdla');image=folder/(name+'.png')
        source.write_text(rdla.scene_text(value,128,128,4,0 if args.feature=='environments' else .5),encoding='utf-8')
        with (folder/(name+'.log')).open('w') as log:
            result=subprocess.run([str(args.runtime/'moonray.exe')]+native.arguments(source,image,2),
                env=native.environment(args.runtime),stdout=log,stderr=subprocess.STDOUT,timeout=180,
                creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode: raise RuntimeError(name+' renderer failed; inspect its log')
        decoded=QtGui.QImage(str(image))
        if decoded.isNull(): raise RuntimeError(name+' image cannot be decoded')
        pixels[name]=[decoded.pixelColor(x,y).getRgb()[:3] for y in range(24,104) for x in range(24,104)]
        report['cases'][name]={'image_sha256':hashlib.sha256(image.read_bytes()).hexdigest()}
    pairs={'materials':[('reference','subsurface'),('reference','layers'),('clear','absorption'),
                        ('mapped_surface','mapped_subsurface')],
           'textures':[('tile_one','tile_two'),('wrap_repeat','wrap_mirror'),
                       ('wrap_edge','wrap_reset'),('channel_red','channel_green'),
                       ('channel_only','channel_ignore'),('channel_use','channel_ignore')],
           'geometry':[('smooth','creased')],
           'environments':[('layered','opaque')],'rendering':[('reference','orthographic'),('reference','motion')]}
    report['mean_absolute_changes']={}
    for a,b in pairs[args.feature]:
        difference=sum(abs(x-y) for p,q in zip(pixels[a],pixels[b]) for x,y in zip(p,q))/(len(pixels[a])*3)
        report['mean_absolute_changes'][a+' / '+b]=difference
        if difference<.5: raise AssertionError('No meaningful image response: '+a+' / '+b)
    report['passed']=True
except Exception:
    report['error']=traceback.format_exc()
finally:
    (folder/'render-report.json').write_text(json.dumps(report,indent=2))
raise SystemExit(0 if report['passed'] else 1)
