"""Render Schlick F0, energy attenuation and roughness in scalar and AVX modes."""
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
modo = Path(r'C:\Program Files\Modo16.1v9\modo')
extra = modo/'resrc/python3kit/extra64'
sys.path[:0] = [str(root/'kit/MoonRayForModo/python'), str(extra/'Python/Scripts')]
dlls = [os.add_dll_directory(str(p)) for p in (modo, extra)]
from PySide2 import QtGui
from moonray_modo import rdla, native
runtime = Path(os.environ.get('MOONRAY_MODO_RUNTIME', str(root/'runtime/native-avx')))
folder = root/'test-results/specular'
folder.mkdir(parents=True, exist_ok=True)
scene = {'camera': {'matrix':rdla.IDENTITY, 'focal_mm':35, 'film_mm':36},
         'meshes':[{'name':'surface', 'vertices':[[-2,-2,-3],[2,-2,-3],[2,2,-3],[-2,2,-3]],
                    'faces':[[0,1,2,3]], 'smooth':False}], 'materials':{}}
report = {}

def render(name, material, environment=1):
    scene['materials'][''] = material
    pictures = []
    for mode in ('scalar','vectorized'):
        source, output = folder/(name+'-'+mode+'.rdla'), folder/(name+'-'+mode+'.png')
        source.write_text(rdla.scene_text(scene,96,96,8,environment))
        with (folder/(name+'-'+mode+'.log')).open('w') as log:
            process = subprocess.run([str(runtime/'moonray.exe')]+native.arguments(source,output,2,mode),
                env=native.environment(runtime), stdout=log, stderr=subprocess.STDOUT,
                timeout=120, creationflags=subprocess.CREATE_NO_WINDOW)
        assert process.returncode == 0, name
        picture = QtGui.QImage(str(output)); assert not picture.isNull(), name
        pictures.append(picture)
    difference = sum(abs(pictures[0].pixelColor(x,y).getRgb()[c]-pictures[1].pixelColor(x,y).getRgb()[c])
        for y in range(16,80) for x in range(16,80) for c in range(3))/(64*64*3)
    assert difference < 3, (name,difference)
    report[name] = {'center':pictures[1].pixelColor(48,48).getRgb(), 'scalar_avx_difference':difference}
    print('Passed',name,flush=True)
    return pictures[1]

def material(f0, roughness=0, diffuse=0):
    return {'color':[diffuse]*3, 'specular':f0, 'roughness':roughness}

off = render('off',material([0]*3))
low = render('low',material([.04]*3))
high = render('high',material([.5]*3))
colored = render('colored',material([.8,.08,.01]))
assert off.pixelColor(48,48).red() <= 1
assert 1 < low.pixelColor(48,48).red() < high.pixelColor(48,48).red()
c = colored.pixelColor(48,48)
assert c.red() > c.green()+30 and c.green() > c.blue()+15, c.getRgb()
# A white diffuse surface under a white furnace stays white when reflection
# consumes the corresponding diffuse energy, rather than adding extra energy.
base = render('furnace-diffuse',material([0]*3,diffuse=.4))
mixed = render('furnace-mixed',material([.5]*3,diffuse=.4))
mirror = render('furnace-mirror',material([1]*3,diffuse=.4))
assert base.pixelColor(48,48).red() < mixed.pixelColor(48,48).red() < mirror.pixelColor(48,48).red()

# A small bright board behind the camera is visible only by reflection.
scene['materials']['board'] = {'color':[0]*3,'emission':[1]*3}
scene['meshes'].append({'name':'emitter','material':'board',
    'vertices':[[-.35,-.35,1],[-.35,.35,1],[.35,.35,1],[.35,-.35,1]],'faces':[[0,1,2,3]]})
sharp = render('sharp-board',material([.8]*3),0)
rough = render('rough-board',material([.8]*3,.4),0)
assert sharp.pixelColor(48,48).red() > rough.pixelColor(48,48).red()+30
assert sum(rough.pixelColor(x,48).red() for x in range(28,38)) > sum(sharp.pixelColor(x,48).red() for x in range(28,38))+10
(folder/'report.json').write_text(json.dumps({'passed':True,'renders':report,
    'binaries':{name:hashlib.sha256((runtime/name).read_bytes()).hexdigest()
                for name in ('UsdPreviewSurface.so','UsdPreviewSurface.so.proxy','librendering_shading.dll')}},indent=2))
print('Standard specular CPU regressions passed')
