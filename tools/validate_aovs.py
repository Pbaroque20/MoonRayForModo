"""Render and inspect actual multilayer EXR channels from the serializer."""
from pathlib import Path
import json
import os
import re
import subprocess
import sys
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'kit/MoonRayForModo/python'))
from moonray_modo import rdla, native, options

results = root / 'test-results/aovs'
results.mkdir(parents=True, exist_ok=True)
output = results / 'passes.exr'
scene = {'camera': {'matrix': rdla.IDENTITY, 'focal_mm': 35, 'film_mm': 36},
         'materials': {'red': {'color': [.8, .05, .02], 'roughness': .4},
                       'green': {'color': [.05, .8, .02], 'roughness': .4}},
         'meshes': [{'name': 'two material mesh', 'vertices': [[-1,-1,-3],[1,-1,-3],[1,1,-3],[-1,1,-3]],
                     'faces': [[0,1,2],[0,2,3]], 'face_materials': ['red','green']}],
         'lights': [{'kind': 'SpotLight', 'matrix': rdla.IDENTITY,
                     'color': [1,1,1], 'intensity': 10, 'radius': .1, 'cone': 65, 'soft_edge': 5}],
         'aovs': list(options.AOVS), 'render_settings': {'max_depth': 3}}
source = results / 'passes.rdla'
source.write_text(rdla.scene_text(scene, 64, 64, 2, 0, str(output)), encoding='utf-8')
runtime = root / 'runtime/native-avx'
environment = native.environment(runtime)
with (results / 'renderer.log').open('w', encoding='utf-8') as log:
    result = subprocess.run([str(runtime/'moonray.exe')] + native.arguments(source, output, 2),
        env=environment, cwd=results, stdout=log, stderr=subprocess.STDOUT,
        timeout=90, creationflags=subprocess.CREATE_NO_WINDOW)
if result.returncode:
    raise SystemExit('AOV render failed; see test-results/aovs/renderer.log')
environment['PATH'] = str(root/'toolchain/msys64/ucrt64/bin') + os.pathsep + environment['PATH']
info = subprocess.check_output([str(root/'toolchain/msys64/ucrt64/bin/oiiotool.exe'),
    '--info', '-v', '--stats', str(output)], env=environment, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
(results/'channels.txt').write_text(info, encoding='utf-8')
for key, (_, _, channel) in options.AOVS.items():
    if channel not in info:
        raise SystemExit('Missing AOV: ' + key)
maximum = [float(v) for v in re.search(r'Stats Max: (.*?) \(float\)', info).group(1).split()]
if not all(v > 0 for v in maximum[:3]):
    raise SystemExit('Spotlight did not illuminate the beauty image')
for kind in ('NanCount', 'InfCount'):
    if any(int(v) for v in re.search(r'Stats ' + kind + r': ([0-9 ]+)', info).group(1).split()):
        raise SystemExit('Non-finite AOV values')
print(info[:2500])
(results/'report.json').write_text(json.dumps({'passed': True, 'aovs': list(options.AOVS),
                                              'image': str(output)}, indent=2), encoding='utf-8')
