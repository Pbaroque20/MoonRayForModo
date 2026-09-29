"""Compare MoonRay's terminator correction on a captured plugin scene."""
from pathlib import Path
import json
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'kit/MoonRayForModo/python'))
from moonray_modo import native

source = Path(sys.argv[1]).read_text(encoding='utf-8')
results = root / 'test-results/shadow-terminator'
results.mkdir(parents=True, exist_ok=True)
runtime = root / 'runtime/native-avx'
reports = []
cases = [('vectorized', 0, 'original'), ('vectorized', 1, 'corrected'), ('scalar', 1, 'scalar')]
if '--surface' in sys.argv:
    cases = [('vectorized', 1, 'flat'), ('vectorized', 1, 'subdivided'), ('vectorized', 1, 'offset')]
for mode, correction, name in cases:
    rdla = results / (name + '.rdla')
    image = results / (name + '.png')
    scene = source.replace('SceneVariables {',
        'SceneVariables {\n  ["shadow_terminator_fix"] = %d,' % correction)
    if name == 'flat':
        scene = scene.replace('["smooth_normal"] = true', '["smooth_normal"] = false')
    elif name == 'subdivided':
        scene = scene.replace('["is_subd"] = false', '["is_subd"] = true, ["mesh_resolution"] = 8')
    elif name == 'offset':
        scene = scene.replace('["is_subd"] = false', '["is_subd"] = false, ["shadow_ray_epsilon"] = 0.01')
    rdla.write_text(scene, encoding='utf-8')
    with (results / (name + '.log')).open('w', encoding='utf-8') as log:
        result = subprocess.run([str(runtime / 'moonray.exe')] + native.arguments(rdla, image, 4, mode),
            env=native.environment(runtime), cwd=results, stdout=log, stderr=subprocess.STDOUT,
            timeout=90, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode or not image.is_file() or image.stat().st_size < 100:
        raise SystemExit('Render failed: ' + name)
    reports.append({'mode': mode, 'correction': correction, 'image': str(image)})
(results / 'report.json').write_text(json.dumps(reports, indent=2), encoding='utf-8')
print(json.dumps(reports, indent=2))
