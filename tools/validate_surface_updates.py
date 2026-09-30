"""Exercise native texture graphs, tangent normals, bump and shared instances."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
modo = Path(r'C:\Program Files\Modo16.1v9\modo')
extra = modo/'resrc/python3kit/extra64'
sys.path.insert(0, str(extra/'Python/Scripts'))
dll_paths = [os.add_dll_directory(str(p)) for p in (modo, extra)]
from PySide2 import QtGui
sys.path.insert(0, str(root/'kit/MoonRayForModo/python'))
from moonray_modo import rdla, native
folder = root/'test-results/surface-updates'
folder.mkdir(parents=True, exist_ok=True)
runtime = root/'runtime/native-avx'

def texture(name, color):
    image = QtGui.QImage(128,128,QtGui.QImage.Format_RGBA8888)
    for y in range(128):
        for x in range(128):
            image.setPixelColor(x,y,QtGui.QColor(*color(x,y)))
    path = folder/(name+'.png')
    assert image.save(str(path))
    return str(path)

neutral = texture('neutral',lambda x,y:(128,128,255,255))
tilted = texture('tilted',lambda x,y:(220,128,220,255))
ramp = texture('ramp',lambda x,y:(x*2,x*2,x*2,255))
flat = texture('flat',lambda x,y:(128,128,128,255))
alpha = texture('alpha',lambda x,y:(255,0,0,128))
scene = {'camera':{'matrix':rdla.IDENTITY,'focal_mm':35,'film_mm':36},
         'materials':{'':{'color':[.5,.5,.5],'roughness':1}},
         'meshes':[{'name':'plane','vertices':[[-1,-1,-3],[1,-1,-3],[1,1,-3],[-1,1,-3]],
                    'faces':[[0,1,2,3]],'uvs':[[0,0],[1,0],[1,1],[0,1]],'smooth':False}],
         'lights':[{'kind':'DistantLight','matrix':[.707,0,-.707,0,0,1,0,0,.707,0,.707,0,0,0,0,1],
                    'intensity':2,'color':[1,1,1],'angle':.01}]}
images = {}
def render(name, data, mode='vectorized', environment=0):
    path, output = folder/(name+'.rdla'), folder/(name+'.png')
    path.write_text(rdla.scene_text(data,96,96,3,environment))
    with (folder/(name+'.log')).open('w') as log:
        result = subprocess.run([str(runtime/'moonray.exe')]+native.arguments(path,output,2,mode),
            env=native.environment(runtime),stdout=log,stderr=subprocess.STDOUT,timeout=90,
            creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode==0, name+' render failed; inspect log'
    assert 'Warning (lib.render)' not in (folder/(name+'.log')).read_text(), name+' scene warning'
    image = QtGui.QImage(str(output))
    assert not image.isNull()
    images[name] = image
    print('Rendered',name,flush=True)
    return image

def difference(a,b,region=range(30,66)):
    return sum(abs(images[a].pixelColor(x,y).getRgb()[c]-images[b].pixelColor(x,y).getRgb()[c])
               for y in region for x in region for c in range(3))/(len(region)**2*3)

render('base',scene)
for name,effect,path,strength in [('neutral','normal',neutral,0),('normal','normal',tilted,0),
                                  ('flat','bump',flat,.8),('bump','bump',ramp,.8)]:
    data=copy.deepcopy(scene)
    data['materials'][''].update(bump_strength=strength,layers=[{'kind':'imageMap','effect':effect,'path':path,'repeat':False}])
    render(name,data)
    if name in ('normal','bump'):
        render(name+'-scalar',data,'scalar')
        assert difference(name,name+'-scalar')<3, name+' SIMD parity failed'
assert difference('base','neutral')<3, 'Neutral normal changes shading'
assert difference('base','flat')<1, 'Flat bump changes shading'
assert difference('base','normal')>8, 'Tangent normal has no lighting effect'
assert difference('base','bump')>8, 'Bump derivative has no lighting effect'
for name,path in [('dwa-neutral',neutral),('dwa-normal',tilted)]:
    data=copy.deepcopy(scene)
    data['materials'][''].update(shader='DwaBaseMaterial',layers=[{'kind':'imageMap','effect':'normal','path':path}])
    render(name,data)
    render(name+'-scalar',data,'scalar')
    assert difference(name,name+'-scalar')<3, 'Moonshine normal scalar/AVX mismatch'
assert difference('dwa-neutral','dwa-normal')>8, 'Moonshine normal input had no effect'

# Emission isolates layer math from lighting. Half-alpha red over blue is magenta.
data=copy.deepcopy(scene); data['lights']=[]
data['materials']['']={'color':[0,0,0],'emission':[0,0,1],
    'layers':[{'kind':'imageMap','effect':'lumiCol','path':alpha,'use_alpha':True}]}
pic=render('alpha-layer',data)
pixel=pic.pixelColor(48,48)
assert abs(pixel.red()-pixel.blue())<4 and pixel.green()<3, pixel.getRgb()
data['materials']['']['layers']=[{'kind':'constant','effect':'lumiCol','value':[1,0,0],'opacity':.5},
    {'kind':'constant','effect':'lumiCol','value':[.5,1,1],'blend':'multiply'}]
pic=render('ordered-layers',data); pixel=pic.pixelColor(48,48)
assert pixel.blue()>pixel.red()>pixel.green()+20, pixel.getRgb()
for kind in ('checker','noise'):
    data['materials']['']['layers']=[{'kind':kind,'effect':'lumiCol','color1':[0,0,0],
        'color2':[1,1,1],'scale':[3,3]}]
    pic=render(kind,data)
    render(kind+'-scalar',data,'scalar')
    assert difference(kind,kind+'-scalar')<2, kind+' SIMD parity failed'
    values=[pic.pixelColor(x,y).red() for y in range(26,70) for x in range(26,70)]
    assert max(values)-min(values)>30, kind+' did not vary'

# Compare one shared prototype (two transformed instances) to explicit copies.
data=copy.deepcopy(scene); data['lights']=[]
data['materials']['']={'color':[0,0,0],'emission':[.1,.8,.2]}
mesh=data['meshes'][0]
mesh['vertices']=[[-.35,-.4,0],[.35,-.4,0],[.35,.4,0],[-.35,.4,0]]
left=list(rdla.IDENTITY); left[12:15]=[-.65,0,-3]
right=list(rdla.IDENTITY); right[0]=.8; right[5]=1.2; right[12:15]=[.65,0,-3]
mesh['instances']=[left,right]
mesh['matrix']=list(rdla.IDENTITY); mesh['matrix'][12]=20
render('instances',data)
explicit=copy.deepcopy(data); prototype=explicit['meshes'].pop(); prototype.pop('instances')
for transform in (left,right):
    duplicate=copy.deepcopy(prototype); duplicate['matrix']=transform; explicit['meshes'].append(duplicate)
render('copies',explicit)
assert difference('instances','copies',range(16,80))<1, 'Instances differ from transformed meshes'
assert images['instances'].pixelColor(27,48).green()>50, 'Instances invisible'
for target in (data,explicit):
    target['materials']['red']={'color':[0,0,0],'emission':[1,0,0]}
    target['materials']['green']={'color':[0,0,0],'emission':[0,1,0]}
    for item in target['meshes']:
        item['vertices']=[[-.35,-.4,0],[0,-.4,0],[0,.4,0],[-.35,.4,0],[.35,-.4,0],[.35,.4,0]]
        item['faces']=[[0,1,2,3],[1,4,5,2]]
        item['face_materials']=['red','green']
        item['uvs']=[]
render('instance-parts',data); render('copy-parts',explicit)
assert difference('instance-parts','copy-parts',range(16,80))<1, 'Instance material parts differ'
report={'passed':True,'normal_maps':True,'bump_maps':True,'layer_alpha':True,
        'ordered_layers':True,'checker':True,'noise_approximation':True,'shared_instances':True,
        'scalar_avx_parity':True,'shader_sha256':{name:hashlib.sha256((runtime/name).read_bytes()).hexdigest()
            for name in ('ModoTextureMap.so','ModoTextureMap.so.proxy','ModoNormalMap.so','ModoNormalMap.so.proxy')}}
(folder/'report.json').write_text(json.dumps(report,indent=2))
print('Surface update render checks passed.')
