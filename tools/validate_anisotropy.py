"""Check the MoonShine anisotropic highlight shape in scalar and AVX modes."""
import json
import os
from pathlib import Path
import subprocess
import sys
root=Path(__file__).resolve().parents[1]
modo=Path(r'C:\Program Files\Modo16.1v9\modo')
extra=modo/'resrc/python3kit/extra64'
sys.path[:0]=[str(root/'kit/MoonRayForModo/python'),str(extra/'Python/Scripts')]
dlls=[os.add_dll_directory(str(p)) for p in (modo,extra)]
from PySide2 import QtGui
from moonray_modo import rdla,native
runtime=Path(native.default_runtime())
folder=root/'test-results/anisotropy'; folder.mkdir(parents=True,exist_ok=True)
scene={'camera':{'matrix':rdla.IDENTITY,'focal_mm':35,'film_mm':36},
 'materials':{'':{'shader':'DwaBaseMaterial','color':[.8]*3,'metallic':1,'roughness':.35},
              'board':{'color':[0]*3,'emission':[1]*3}},
 'meshes':[{'name':'surface','vertices':[[-2,-2,-3],[2,-2,-3],[2,2,-3],[-2,2,-3]],
            'faces':[[0,1,2,3]],'uvs':[[0,0],[1,0],[1,1],[0,1]]},
           {'name':'board','material':'board','vertices':[[-.25,-.25,1],[-.25,.25,1],[.25,.25,1],[.25,-.25,1]],
            'faces':[[0,1,2,3]]}]}
images={}
for name,amount in [('round',0),('stretched',.85),('reversed',-.85)]:
    scene['materials']['']['anisotropy']=amount
    for mode in ('scalar','vectorized'):
        key=name+'-'+mode
        source,output=folder/(key+'.rdla'),folder/(key+'.png')
        source.write_text(rdla.scene_text(scene,96,96,12,0))
        with (folder/(key+'.log')).open('w') as log:
            result=subprocess.run([str(runtime/'moonray.exe')]+native.arguments(source,output,2,mode),
                env=native.environment(runtime),stdout=log,stderr=subprocess.STDOUT,timeout=120,
                creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode==0,key
        pic=QtGui.QImage(str(output)); assert not pic.isNull()
        images[key]=pic
        print('Rendered',key,flush=True)
def ratio(pic):
    xx=yy=0
    for y in range(16,80):
        for x in range(16,80):
            weight=pic.pixelColor(x,y).red()
            xx+=weight*(x-47.5)**2; yy+=weight*(y-47.5)**2
    return xx/max(1,yy)
ratios={key:ratio(pic) for key,pic in images.items()}
assert .75<ratios['round-vectorized']<1.25,ratios
a,b=ratios['stretched-vectorized'],ratios['reversed-vectorized']
assert max(a,b)>1.7 and min(a,b)<.6,ratios
for name in ('round','stretched','reversed'):
    a,b=images[name+'-scalar'],images[name+'-vectorized']
    delta=sum(abs(a.pixelColor(x,y).red()-b.pixelColor(x,y).red()) for y in range(16,80) for x in range(16,80))/4096
    assert delta<4,(name,delta)
(folder/'report.json').write_text(json.dumps({'passed':True,'highlight_width_ratios':ratios},indent=2))
print('Anisotropy shape and CPU parity checks passed')
