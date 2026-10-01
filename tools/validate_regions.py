"""Verify region orientation, full-frame dimensions and unchanged inside pixels."""
import json
import os
from pathlib import Path
import subprocess
import sys
root=Path(__file__).resolve().parents[1]
modo=Path(r'C:\Program Files\Modo16.1v9\modo'); extra=modo/'resrc/python3kit/extra64'
sys.path[:0]=[str(root/'kit/MoonRayForModo/python'),str(extra/'Python/Scripts')]
dlls=[os.add_dll_directory(str(p)) for p in (modo,extra)]
from PySide2 import QtGui
from moonray_modo import rdla,native
runtime=Path(native.default_runtime()); folder=root/'test-results/regions'
folder.mkdir(parents=True,exist_ok=True)
scene={'camera':{'matrix':rdla.IDENTITY,'focal_mm':35,'film_mm':36},
       'materials':{'':{'color':[0]*3,'emission':[.5,.25,.1]}},
       'meshes':[{'name':'board','vertices':[[-10,-10,-3],[10,-10,-3],[10,10,-3],[-10,10,-3]],'faces':[[0,1,2,3]]}]}
images={}
for key,region in [('full',None),('top-left',[0,0,.5,.5]),('lower',[.25,.5,.75,1])]:
    scene['region']=region
    source,output=folder/(key+'.rdla'),folder/(key+'.png')
    source.write_text(rdla.scene_text(scene,96,64,2,0))
    with (folder/(key+'.log')).open('w') as log:
        result=subprocess.run([str(runtime/'moonray.exe')]+native.arguments(source,output,2),
            env=native.environment(runtime),stdout=log,stderr=subprocess.STDOUT,timeout=90,
            creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode==0,key
    pic=QtGui.QImage(str(output)); assert pic.width()==96 and pic.height()==64
    images[key]=pic
reference=images['full'].pixelColor(16,16).getRgb()
assert images['top-left'].pixelColor(16,16).getRgb()==reference
assert images['top-left'].pixelColor(70,16).red()==0
assert images['top-left'].pixelColor(16,48).red()==0
assert images['lower'].pixelColor(48,48).getRgb()==reference
assert images['lower'].pixelColor(48,16).red()==0
for invalid in ([.5,0,.25,1],[0,0,0,1],[-.1,0,1,1],[0,0,float('nan'),1]):
    scene['region']=invalid
    try: rdla.scene_text(scene)
    except ValueError: pass
    else: raise AssertionError('Invalid region accepted: '+str(invalid))
(folder/'report.json').write_text(json.dumps({'passed':True,'orientation':True,'unchanged_inside':True,'full_frame':True},indent=2))
print('Render region checks passed')
