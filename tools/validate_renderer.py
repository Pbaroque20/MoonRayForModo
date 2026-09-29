"""Render a real exported scene before allowing installation into Modo."""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'kit/MoonRayForModo/python'))
from moonray_modo import rdla, native

runtime = root / 'runtime/native-avx'
results = root / 'test-results/native-render'
results.mkdir(parents=True, exist_ok=True)
scene = {
    'camera': {'matrix': rdla.IDENTITY, 'focal_mm': 35, 'film_mm': 36},
    'materials': {'red': {'color': [0.8, 0.06, 0.025], 'roughness': 0.5, 'metallic': 0}},
    'meshes': [{'name': 'AVX triangle', 'vertices': [[-1, -1, -3], [1, -1, -3], [0, 1, -3]],
                'faces': [[0, 1, 2]], 'material': 'red'}],
    'lights': []}
source = results / 'triangle.rdla'
source.write_text(rdla.scene_text(scene, 64, 64, 2, 1.0), encoding='utf-8')
environment = native.environment(runtime)
reports = []
for mode in (('scalar',) if '--scalar-only' in sys.argv else ('scalar', 'vectorized')):
    output = results / ('triangle-' + mode + '.png')
    if output.exists():
        output.unlink()
    command = [str(runtime / 'moonray.exe')] + native.arguments(source, output, 2, mode)
    with (results / (mode + '.log')).open('w', encoding='utf-8') as log:
        result = subprocess.run(command, env=environment, cwd=results, stdout=log, stderr=subprocess.STDOUT,
                                timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode or not output.is_file() or output.stat().st_size < 100:
        raise SystemExit('Native ' + mode + ' render failed; see ' + str(results / (mode + '.log')))
    if output.read_bytes()[:8] != b'\x89PNG\r\n\x1a\n':
        raise SystemExit('Renderer output is not a PNG image.')
    inspection_env = dict(environment)
    inspection_env['PATH'] = str(root / 'toolchain/msys64/ucrt64/bin') + os.pathsep + inspection_env['PATH']
    info = subprocess.check_output([str(root / 'toolchain/msys64/ucrt64/bin/oiiotool.exe'),
        '--info', '-v', '--stats', str(output)], env=inspection_env, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW)
    (results / (mode + '-image-stats.txt')).write_text(info, encoding='utf-8')
    match = re.search(r'Stats StdDev:\s*([^\r\n]+)', info)
    if not match or not any(float(x) > 0.001 for x in re.findall(r'[\d.]+', match.group(1))[:3]):
        raise SystemExit('Rendered image did not contain varying color values: ' + str(output))
    reports.append({'mode': mode, 'image': str(output), 'sha256': hashlib.sha256(output.read_bytes()).hexdigest()})
# A failed output request must report an error and release worker threads, rather
# than hanging during Windows DLL shutdown. The directory itself is not a file.
with (results / 'invalid-output.log').open('w', encoding='utf-8') as log:
    failure = subprocess.run([str(runtime / 'moonray.exe')] + native.arguments(source, results, 2),
        env=environment, cwd=results, stdout=log, stderr=subprocess.STDOUT,
        timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
if failure.returncode == 0:
    raise SystemExit('The renderer incorrectly accepted a directory as its output image.')
report = {'executable_sha256': hashlib.sha256((runtime / 'moonray.exe').read_bytes()).hexdigest(),
          'renders': reports, 'scene': str(source), 'failed_render_exits_cleanly': True}
marker = (results / 'validated-scalar.json') if '--scalar-only' in sys.argv else (runtime / 'validated-render.json')
marker.write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report, indent=2))
