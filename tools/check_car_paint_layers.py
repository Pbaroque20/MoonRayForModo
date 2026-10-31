"""The car paint scene in MoonRay outside Modo with the paint's layers changed one at a time, to find what hides the coat's sharp
reflections. Needs moonray.rdla from render_car_paint_scene.py. check_car_paint_layers.py [case ...] writes
test-results/car-paint-scene/layers/<case>.png."""
import os
import re
import subprocess
import sys
import time
from pathlib import Path
os.environ['MOONRAY_MODO_PREFERENCES'] = 'TestPreview'
for folder in (r'C:\Program Files\Modo16.1v9\modo', r'C:\Program Files\Modo16.1v9\modo\resrc\python3kit\extra64'):
    os.add_dll_directory(folder)
ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / 'dist/personal-kit/Luxology/Kits/MoonRayForModo'
sys.path.insert(0, str(KIT / 'python'))
runtime = KIT / 'runtime'
os.environ['MOONRAY_MODO_RUNTIME'] = str(runtime)
from PySide2 import QtCore
app = QtCore.QCoreApplication([])
from moonray_modo import native

source = ROOT / 'test-results/car-paint-scene'
out = source / 'layers'
out.mkdir(parents=True, exist_ok=True)
env = native.environment(runtime)
text = (source / 'moonray.rdla').read_text(encoding='utf-8')
BLOCK = re.compile(r'(DwaMetalMaterial\("/modo/native/stack/1002001"\) \{\n)(.*?)(\n\})', re.S)
assert BLOCK.search(text)
BLACK = {'metallic_color': 'Rgb(0, 0, 0)', 'metallic_edge_color': 'Rgb(0, 0, 0)'}
NO_GLITTER = {'show_glitter': 'false'}
NO_COAT = {'show_clearcoat': 'false'}
CASES = {'a-coat-on-black': dict(BLACK, **NO_GLITTER),
         'b-coat-no-flakes': NO_GLITTER,
         'c-no-coat-no-flakes': dict(NO_COAT, **NO_GLITTER),
         'd-flakes-layering-0': {'glitter_layering_mode': '0'},
         'e-flakes-layering-1': {},
         'f-coat-weak-flakes': {'glitter': '0.25'},
         'g-strong-coat-on-black': dict(BLACK, clearcoat_refractive_index='5', **NO_GLITTER),
         'h-no-coat-on-black': dict(BLACK, **NO_COAT, **NO_GLITTER)}


def changed(values):
    def edit(match):
        lines = match.group(2).split('\n')
        for name, value in values.items():
            lines = [l for l in lines if '["%s"]' % name not in l] + ['  ["%s"] = %s,' % (name, value)]
        return match.group(1) + '\n'.join(lines) + match.group(3)
    return BLOCK.sub(edit, text)


for case, values in CASES.items():
    if len(sys.argv) > 1 and case not in sys.argv[1:]:
        continue
    exr = out / (case + '.exr')
    path = out / (case + '.rdla')
    path.write_text(changed(values), encoding='utf-8')
    started = time.time()
    done = subprocess.run([str(runtime / 'moonray.exe')] + native.arguments(path, exr, 0, 'vectorized'), env=env, cwd=str(out), capture_output=True, text=True)
    subprocess.run([str(runtime / 'oiiotool.exe'), str(exr), '--ch', 'R,G,B', '--colorconvert', 'linear', 'sRGB', '-d', 'uint8', '-o', str(out / (case + '.png'))], env=env, capture_output=True)
    print(case, 'rc', done.returncode, '%.0f s' % (time.time() - started), [l.strip()[:130] for l in done.stdout.splitlines() if 'rror' in l][:2], flush=True)
