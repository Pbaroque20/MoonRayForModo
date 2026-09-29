"""Render a small actual MoonRay image; never substitutes a mock renderer."""
import json
import pathlib
import subprocess
import sys

root = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'kit/MoonRayForModo/python'))
from moonray_modo import rdla, native

out = root / 'test-results'
out.mkdir(exist_ok=True)
scene = {
    'camera': {'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 4, 1],
               'focal_mm': 50, 'film_mm': 36},
    'materials': {'red': {'color': [0.7, 0.03, 0.02], 'roughness': 0.3}},
    'meshes': [{'name': 'Quad', 'vertices': [[-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]],
                'faces': [[0, 1, 2, 3]], 'material': 'red'}]}
scene_path = out / 'native-smoke.rdla'
scene_path.write_text(rdla.scene_text(scene, 128, 128, 2, 1), encoding='utf-8')
runtime = native.find_runtime(root / 'runtime')
with (out / 'native-smoke.log').open('w', encoding='utf-8') as log:
    proc = subprocess.run([str(runtime / 'moonray.exe')] + native.arguments(scene_path, out / 'native-smoke.png', 4),
                          env=native.environment(runtime), cwd=str(out), stdout=log, stderr=subprocess.STDOUT,
                          creationflags=subprocess.CREATE_NO_WINDOW, timeout=120)
image = out / 'native-smoke.png'
result = {'returncode': proc.returncode, 'exit_hex': '0x%08X' % (proc.returncode & 0xffffffff),
          'image_exists': image.is_file() and image.stat().st_size > 8}
(out / 'native-smoke.json').write_text(json.dumps(result, indent=2))
print(result)
print((out / 'native-smoke.log').read_text(encoding='utf-8')[-6000:])
sys.exit(0 if proc.returncode == 0 and result['image_exists'] else 1)
