"""Render scalar material maps on CPU, including alpha holes and AVX parity."""
import json
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
modo = Path(r'C:\Program Files\Modo16.1v9\modo')
extra = modo/'resrc/python3kit/extra64'
sys.path[:0] = [str(root/'kit/MoonRayForModo/python'),str(extra/'Python/Scripts')]
dlls = [os.add_dll_directory(str(p)) for p in (modo,extra)]
from PySide2 import QtGui
from moonray_modo import rdla,native
folder = root/'test-results/amount-maps'
folder.mkdir(parents=True,exist_ok=True)
source = folder/'black-white.png'
image = QtGui.QImage(64,64,QtGui.QImage.Format_RGB32)
for y in range(64):
    for x in range(64):
        image.setPixelColor(x,y,QtGui.QColor(0,0,0) if x<32 else QtGui.QColor(255,255,255))
assert image.save(str(source))
runtime = Path(os.environ.get('MOONRAY_MODO_RUNTIME', str(root/'runtime/native-avx')))
scene = {'camera':{'matrix':rdla.IDENTITY,'focal_mm':35,'film_mm':36},
         'materials':{}, 'lights':[],
         'meshes':[{'name':'mapped plane','vertices':[[-1,-1,-3],[1,-1,-3],[1,1,-3],[-1,1,-3]],
             'faces':[[0,1,2,3]],'uvs':[[0,0],[1,0],[1,1],[0,1]],'smooth':False}]}
results = {}
def render(name,mode='vectorized',environment=1):
    path,output = folder/(name+'.rdla'),folder/(name+'.png')
    path.write_text(rdla.scene_text(scene,96,96,3,environment))
    with (folder/(name+'.log')).open('w') as log:
        result = subprocess.run([str(runtime/'moonray.exe')]+native.arguments(path,output,2,mode),
            env=native.environment(runtime),stdout=log,stderr=subprocess.STDOUT,timeout=90,
            creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode==0, name
    assert 'Warning (lib.render)' not in (folder/(name+'.log')).read_text(), name
    pic = QtGui.QImage(str(output)); assert not pic.isNull()
    return pic

for shader in ('','DwaBaseMaterial'):
    for effect in ('diffAmount','lumiAmount','specAmount','dissolve'):
        material = {'shader':shader,'color':[0,0,0],'raw_color':[0,0,0],
            'diffuse_amount':0, 'specular':[0,0,0], 'raw_specular':[1,1,1],
            'specular_amount':0, 'emission':[0,0,0], 'raw_emission':[0,0,0],
            'emission_amount':0,'roughness':.3,'ior':1.5,
            'layers':[{'kind':'imageMap','effect':effect,'path':str(source),'srgb':False}]}
        if effect=='diffAmount': material['raw_color']=[1,1,1]
        if effect=='lumiAmount': material['raw_emission']=[1,1,1]
        if effect=='dissolve':
            material.update(emission=[1,1,1],raw_emission=[1,1,1],emission_amount=1)
        scene['materials']={'':material}
        name=('moonshine-' if shader else 'standard-')+effect
        environment=0 if effect in ('lumiAmount','dissolve') else 1
        if effect=='specAmount': environment=4 # Dielectric F0 is only 4% at IOR 1.5.
        pic=render(name,environment=environment)
        scalar=render(name+'-scalar','scalar',environment)
        left=pic.pixelColor(32,48); right=pic.pixelColor(64,48)
        if effect=='dissolve':
            assert left.alpha()>240 and right.alpha()<10, (name,left.getRgb(),right.getRgb())
        else:
            assert right.red()>left.red()+20, (name,left.getRgb(),right.getRgb())
        delta=sum(abs(pic.pixelColor(x,y).getRgb()[c]-scalar.pixelColor(x,y).getRgb()[c])
            for y in range(25,71) for x in range(25,71) for c in range(4))/(46*46*4)
        assert delta<3, (name,delta)
        results[name]={'left':left.getRgb(),'right':right.getRgb(),'scalar_avx_difference':delta}
        print('Passed',name,flush=True)

# An amount map replaces the constant amount; the color layer then multiplies
# it exactly once, after both stacks have applied their layer opacity.
scene['materials']={'':{'color':[0,0,0], 'raw_emission':[1,1,1], 'emission_amount':0,
    'layers':[{'kind':'constant','effect':'lumiAmount','value':[1,1,1],'opacity':.5},
              {'kind':'constant','effect':'lumiColor','value':[.5,0,0]}]}}
mapped=render('combined-map',environment=0)
scene['materials']={'':{'color':[0,0,0],'emission':[.25,0,0]}}
reference=render('combined-reference',environment=0)
assert abs(mapped.pixelColor(48,48).red()-reference.pixelColor(48,48).red())<=1
(folder/'report.json').write_text(json.dumps({'passed':True,'renders':results,
    'amount_replaces_constant':True,'color_amount_composition':True},indent=2))
print('CPU amount-map and dissolve checks passed')
