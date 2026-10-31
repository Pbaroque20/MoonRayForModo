"""The material of a user's metaltest.lxo on the MoonRay Widget's model in MoonRay, outside Modo: with its glitter as it was, off, and at
smaller flake sizes. check_metal_glitter.py [case ...] writes test-results/metal-glitter/<case>.png."""
import os
import subprocess
import sys
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
from moonray_modo import native, options, rdla
from moonray_modo.material_preview import snapshot

out = ROOT / 'test-results/metal-glitter'
out.mkdir(parents=True, exist_ok=True)
env = native.environment(runtime)
W, H = 480, 480
HDRI = ROOT / 'test-results/car-paint/studio_2k.exr'
GOLD = {'metallic_color': [.604, .357, .071], 'metallic_edge_color': [1.0, .698, .396], 'show_clearcoat': True}
THEIRS = dict(GOLD, show_glitter=True, glitter_color_A=[.322, 1.0, .075], glitter_color_B=[.153, 1.0, .929])
CASES = {'1-as-saved': THEIRS,
         '2-glitter-off': GOLD,
         '3-white-flakes-default-size': dict(GOLD, show_glitter=True),
         '4-size-0.1': dict(THEIRS, glitter_size_A=.1, glitter_size_B=.1),
         '5-size-0.01': dict(THEIRS, glitter_size_A=.01, glitter_size_B=.01),
         '6-white-size-0.01': dict(GOLD, show_glitter=True, glitter_size_A=.01, glitter_size_B=.01),
         '7-white-0.015-additive': dict(GOLD, show_glitter=True, glitter_size_A=.015, glitter_size_B=.015, glitter_layering_mode=1),
         '8-white-0.03-additive': dict(GOLD, show_glitter=True, glitter_size_A=.03, glitter_size_B=.03, glitter_layering_mode=1),
         '9-white-0.03': dict(GOLD, show_glitter=True, glitter_size_A=.03, glitter_size_B=.03),
         '10-white-0.03-object': dict(GOLD, show_glitter=True, glitter_size_A=.03, glitter_size_B=.03, glitter_space=4)}


def render(case, parameters):
    material = {'shader': 'DwaBaseMaterial', 'moonshine_override': True, 'native_shader': 'DwaMetalMaterial', 'native_parameters': parameters,
                'color': [.5, .5, .5], 'roughness': .3}
    scene = snapshot(material, {}, True)
    scene['lights'] = []
    scene.update(width=W, height=H, aovs=['alpha'], custom_aovs=[], preview_buffer='beauty')
    scene['render_settings'] = options.render_values({'sampling_mode': 0, 'pixel_samples': 8})
    exr = out / (case + '.exr')
    text = rdla.scene_text(scene, W, H, 8, 1.0, str(exr))
    held = 'EnvLight("/modo/environment") {'
    assert text.count(held) == 1
    text = text.replace(held, held + ' ["texture"] = %s,' % rdla.string(str(HDRI)))
    path = out / (case + '.rdla')
    path.write_text(text, encoding='utf-8')
    done = subprocess.run([str(runtime / 'moonray.exe')] + native.arguments(path, exr, 0, 'vectorized'), env=env, cwd=str(out), capture_output=True, text=True)
    subprocess.run([str(runtime / 'oiiotool.exe'), str(exr), '--ch', 'R,G,B', '--colorconvert', 'linear', 'sRGB', '-d', 'uint8', '-o', str(out / (case + '.png'))], env=env, capture_output=True)
    print(case, 'rc', done.returncode, flush=True)


for case, parameters in CASES.items():
    if len(sys.argv) < 2 or case in sys.argv[1:]:
        render(case, parameters)
