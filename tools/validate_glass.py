"""Real scalar/AVX tests: closed glass sphere against an emissive striped board."""
import copy
import hashlib
import json
import math
import os
import re
from pathlib import Path
import subprocess
import sys
root = Path(__file__).resolve().parents[1]
modo = Path(r'C:\Program Files\Modo16.1v9\modo')
extra = modo / 'resrc/python3kit/extra64'
sys.path.insert(0, str(extra/'Python/Scripts'))
dll_paths = [os.add_dll_directory(str(p)) for p in (modo, extra)]
from PySide2 import QtGui
sys.path.insert(0, str(root/'kit/MoonRayForModo/python'))
from moonray_modo import rdla, native
folder = root/'test-results/glass'
folder.mkdir(parents=True, exist_ok=True)
runtime = root/'runtime/native-avx'
vertices, normals, faces = [], [], []
segments, rings = 48, 24
vertices.append([0, .85, -3])
for ring in range(1, rings):
    theta = math.pi*ring/rings
    for segment in range(segments):
        phi = math.tau*segment/segments
        vertices.append([.85*math.sin(theta)*math.cos(phi), .85*math.cos(theta),
                         -3+.85*math.sin(theta)*math.sin(phi)])
bottom = len(vertices)
vertices.append([0, -.85, -3])
for segment in range(segments):
    a, b = 1+segment, 1+(segment+1)%segments
    faces.append([0, b, a])
    for ring in range(rings-2):
        x, y = a+ring*segments, b+ring*segments
        faces.append([x, y, y+segments, x+segments])
    faces.append([bottom, a+(rings-2)*segments, b+(rings-2)*segments])
# Reorient explicitly against the sphere center, independent of parameterization.
for face in faces:
    p, q, r = (vertices[i] for i in face[:3])
    u, v = [q[k]-p[k] for k in range(3)], [r[k]-p[k] for k in range(3)]
    n = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]]
    if sum(n[k]*(p[k]+(3 if k==2 else 0)) for k in range(3)) < 0:
        face.reverse()
    normals.extend([[vertices[i][0]/.85,vertices[i][1]/.85,(vertices[i][2]+3)/.85] for i in face])
scene = {'camera': {'matrix': rdla.IDENTITY, 'focal_mm': 35, 'film_mm': 36},
         'materials': {'glass': {'color':[.4,.4,.4], 'transmission':1, 'ior':1.5,
                               'roughness':0, 'refraction_roughness':0}},
         'meshes': [{'name':'closed glass sphere', 'material':'glass',
                     'vertices':vertices, 'faces':faces, 'normals':normals}],
         'render_settings': {'max_depth':12, 'max_mirror_depth':12, 'max_glossy_depth':8}}
for i in range(20):
    x = -4+i*.4
    color = [1,1,1] if i%2 else [.02,.02,.02]
    tag = 'stripe%d' % i
    scene['materials'][tag] = {'color':[0,0,0], 'emission':color, 'roughness':1}
    scene['meshes'].append({'name':tag,'material':tag,'vertices':[[x,-4,-5],[x+.4,-4,-5],[x+.4,4,-5],[x,4,-5]],
                            'faces':[[0,1,2,3]]})
report = {'passed':False,'renders':{}}
(folder/'scene.json').write_text(json.dumps(scene))
images = {}
cases = [('clear',{}),('no_bending',{'ior':1}),('green',{'transmission_color':[.12,.95,.12]}),
         ('frosted',{'refraction_roughness':.4}),('partial',{'transmission':.4}),('dissolved',{'presence':0})]
for name, values in cases:
    current = copy.deepcopy(scene)
    current['materials']['glass'].update(values)
    for mode in (('scalar','vectorized') if name in ('clear','frosted') else ('vectorized',)):
        key = name+'-'+mode
        source, image = folder/(key+'.rdla'), folder/(key+'.png')
        source.write_text(rdla.scene_text(current, 128, 128, 4, 0))
        with (folder/(key+'.log')).open('w') as log:
            result = subprocess.run([str(runtime/'moonray.exe')]+native.arguments(source,image,2,mode),
                env=native.environment(runtime),stdout=log,stderr=subprocess.STDOUT,
                timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode==0, key+' failed'
        decoded = QtGui.QImage(str(image))
        assert not decoded.isNull(), key+' has no image'
        pixels = [decoded.pixelColor(x,y).getRgb()[:3] for y in range(40,88) for x in range(40,88)]
        images[key] = pixels
        report['renders'][key] = {'image':str(image),'sha256':hashlib.sha256(image.read_bytes()).hexdigest()}
def difference(a,b):
    return sum(abs(x-y) for p,q in zip(images[a],images[b]) for x,y in zip(p,q))/(len(images[a])*3)
def block_difference(a,b):
    # Rough scattering consumes different random samples in scalar and SIMD.
    # Compare spatial averages rather than treating Monte Carlo noise as a bug.
    differences = []
    for y in range(0,48,8):
        for x in range(0,48,8):
            for channel in range(3):
                means = [sum(images[key][j*48+i][channel] for j in range(y,y+8)
                             for i in range(x,x+8))/64 for key in (a,b)]
                differences.append(abs(means[0]-means[1]))
    return sum(differences)/len(differences)
assert difference('clear-scalar','clear-vectorized') < 3, 'Scalar/AVX glass differ'
frost_error = block_difference('frosted-scalar','frosted-vectorized')
assert frost_error < 3, 'Scalar/AVX rough glass block means differ: %s' % frost_error
assert difference('clear-vectorized','no_bending-vectorized') > 5, 'IOR did not bend background rays'
assert difference('clear-vectorized','frosted-vectorized') > 5, 'Rough refraction did not alter image'
assert difference('clear-vectorized','partial-vectorized') > 5, 'Transmission amount had no effect'
assert difference('no_bending-vectorized','dissolved-vectorized') < 3, 'Presence is not independent of glass'
green = images['green-vectorized']
assert sum(p[1] for p in green) > 1.3*sum(p[0] for p in green), 'Glass tint not transmitted'
scene['aovs'] = ['transmission']
exr = folder/'transmission.exr'
source = folder/'transmission.rdla'
source.write_text(rdla.scene_text(scene,64,64,2,0,str(exr)))
with (folder/'transmission.log').open('w') as log:
    result = subprocess.run([str(runtime/'moonray.exe')]+native.arguments(source,exr,2),
        env=native.environment(runtime),stdout=log,stderr=subprocess.STDOUT,
        timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
assert result.returncode == 0
info = subprocess.check_output([str(root/'toolchain/msys64/ucrt64/bin/oiiotool.exe'),
    '--info','-v','--stats',str(exr)], env=native.environment(runtime),text=True,
    creationflags=subprocess.CREATE_NO_WINDOW)
(folder/'transmission-stats.txt').write_text(info)
assert 'transmission.R' in info
maximum = re.search(r'Stats Max: (.*?) \(float\)',info).group(1).split()
assert all(float(v)>0 for v in maximum[-3:]), 'Transmission AOV is black'
for kind in ('NanCount','InfCount'):
    assert not any(int(v) for v in re.search(r'Stats '+kind+r': ([0-9 ]+)',info).group(1).split())
report['binaries'] = {name:hashlib.sha256((runtime/name).read_bytes()).hexdigest()
                      for name in ('ModoGlassMaterial.so','ModoGlassMaterial.so.proxy')}
report.update(passed=True, transmission_aov=True, frosted_scalar_avx_block_error=frost_error,
              scalar_avx_mean_error=difference('clear-scalar','clear-vectorized'),
              ior_pixel_difference=difference('clear-vectorized','no_bending-vectorized'))
(folder/'report.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
