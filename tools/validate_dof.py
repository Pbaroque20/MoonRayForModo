"""Verify focus plane preservation, defocus, f-stop and scalar/AVX agreement."""
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
runtime = Path(os.environ.get('MOONRAY_MODO_RUNTIME',str(root/'runtime/native-avx')))
folder = root/'test-results/camera-controls'
folder.mkdir(parents=True,exist_ok=True)
scene={'camera':{'matrix':rdla.IDENTITY,'focal_mm':100,'film_mm':36},'materials':{},'meshes':[]}
# Small scene scale deliberately gives a measurable blur circle at 96 pixels.
for i in range(24):
    x=-.25+i*.5/24
    color=[1]*3 if i%2 else [0]*3
    tag=str(i)
    scene['materials'][tag]={'color':[0]*3,'emission':color}
    scene['meshes'].append({'name':tag,'material':tag,
        'vertices':[[x,-.3,-1],[x+.5/24,-.3,-1],[x+.5/24,.3,-1],[x,.3,-1]],'faces':[[0,1,2,3]]})
images={}
for name,settings in [('pinhole',{}),('focused',{'dof':True,'focus_distance':1,'f_stop':1}),
                      ('blurred',{'dof':True,'focus_distance':.5,'f_stop':1}),
                      ('stopped',{'dof':True,'focus_distance':.5,'f_stop':16}),
                      ('polygon',{'dof':True,'focus_distance':.5,'f_stop':1,'iris_blades':6,'iris_rotation':.5})]:
    camera=dict(matrix=rdla.IDENTITY,focal_mm=100,film_mm=36,**settings)
    scene['camera']=camera
    for mode in (('scalar','vectorized') if name=='blurred' else ('vectorized',)):
        key=name+'-'+mode
        source,output=folder/(key+'.rdla'),folder/(key+'.png')
        source.write_text(rdla.scene_text(scene,96,96,12,0))
        with (folder/(key+'.log')).open('w') as log:
            process=subprocess.run([str(runtime/'moonray.exe')]+native.arguments(source,output,2,mode),
                env=native.environment(runtime),stdout=log,stderr=subprocess.STDOUT,timeout=120,
                creationflags=subprocess.CREATE_NO_WINDOW)
        assert process.returncode==0,key
        pic=QtGui.QImage(str(output)); assert not pic.isNull(),key
        images[key]=pic
        print('Rendered',key,flush=True)
def contrast(pic):
    return sum(abs(pic.pixelColor(x+1,y).red()-pic.pixelColor(x,y).red())
        for x in range(20,75) for y in range(35,61))/(55*26)
values={key:contrast(pic) for key,pic in images.items()}
assert abs(values['pinhole-vectorized']-values['focused-vectorized'])<1
assert values['blurred-vectorized'] < values['pinhole-vectorized']*.5
assert values['stopped-vectorized'] > values['blurred-vectorized']*2
a,b=images['blurred-scalar'],images['blurred-vectorized']
delta=sum(abs(a.pixelColor(x,y).red()-b.pixelColor(x,y).red()) for y in range(20,76) for x in range(20,76))/(56*56)
assert delta<4,delta
(folder/'dof.json').write_text(json.dumps({'passed':True,'edge_contrast':values,'scalar_avx_difference':delta},indent=2))
print('Depth-of-field render checks passed')
