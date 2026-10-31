"""Car paint as a DwaMetalMaterial, built up a layer at a time under a studio HDRI, on the MoonRay Widget's model, in MoonRay
outside Modo. check_car_paint.py [case ...] writes test-results/car-paint/<case>.png."""
import os
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
from moonray_modo import native, options, rdla, shader_library
from moonray_modo.material_preview import snapshot

out = ROOT / 'test-results/car-paint'
out.mkdir(parents=True, exist_ok=True)
env = native.environment(runtime)
W, H = 640, 640
SOURCE = ROOT.parent / 'Downloads/Lamborghini(1)/imported_images/studio_small_03_8k.exr'
HDRI = out / 'studio_2k.exr'
if not HDRI.exists():
    subprocess.run([str(runtime / 'oiiotool.exe'), str(SOURCE), '--ch', 'R,G,B', '--resize', '2048x1024', '-d', 'half', '-o', str(HDRI)], env=env, check=True, capture_output=True)

RED = {'metallic_color': [.45, .012, .02], 'metallic_edge_color': [.9, .25, .2]}
COAT = {'show_clearcoat': True, 'clearcoat': 1.0, 'clearcoat_roughness': .015, 'clearcoat_refractive_index': 1.5}
FLAKES = {'show_glitter': True, 'glitter': 1.0, 'glitter_color_A': [.95, .55, .5], 'glitter_size_A': .012, 'glitter_density': 1.0,
          'glitter_roughness_A': .12, 'glitter_randomness': .35, 'glitter_style_A_frequency': 1.0, 'glitter_space': 4}
CASES = {'1-plastic': ('DwaBaseMaterial', {'albedo': [.45, .012, .02], 'roughness': .3}),
         '2-as-the-car': ('DwaMetalMaterial', dict(RED, show_clearcoat=True, specular_model=0)),
         '3-metal': ('DwaMetalMaterial', dict(RED, roughness=.38)),
         '4-coat': ('DwaMetalMaterial', dict(RED, roughness=.38, **COAT)),
         '5-paint': ('DwaMetalMaterial', dict(RED, roughness=.38, **COAT, **FLAKES))}
CASES.update({
    '6-flakes-big': ('DwaMetalMaterial', dict(RED, roughness=.38, **COAT, **dict(FLAKES, glitter_size_A=.03, glitter_randomness=.6))),
    '7-flakes-bright': ('DwaMetalMaterial', dict(RED, roughness=.38, **COAT, **dict(FLAKES, glitter_size_A=.02, glitter_randomness=.8, glitter_roughness_A=.25, glitter_color_A=[1.0, .85, .8], glitter_layering_mode=1))),
    '8-flakes-dense': ('DwaMetalMaterial', dict(RED, roughness=.38, **COAT, **dict(FLAKES, glitter_size_A=.012, glitter_density=3.0, glitter_randomness=.9, glitter_roughness_A=.2, glitter_color_A=[1.0, .7, .65], glitter_layering_mode=1)))})


DARK = {'metallic_color': [.22, .004, .008], 'metallic_edge_color': [.7, .1, .08]}
CASES.update({
    '9-big': ('DwaMetalMaterial', dict(DARK, roughness=.4, **COAT, **dict(FLAKES, glitter_size_A=.06, glitter_randomness=1.0, glitter_roughness_A=.05, glitter_color_A=[1.0, .9, .85], glitter_layering_mode=1))),
    '10-fine': ('DwaMetalMaterial', dict(DARK, roughness=.4, **COAT, **dict(FLAKES, glitter_size_A=.015, glitter_randomness=1.0, glitter_roughness_A=.05, glitter_color_A=[1.0, .9, .85], glitter_layering_mode=1)))})


def render(case, shader, parameters):
    shader_library.validate(shader, parameters)
    material = {'shader': 'DwaBaseMaterial', 'moonshine_override': True, 'native_shader': shader, 'native_parameters': parameters,
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
    started = time.time()
    done = subprocess.run([str(runtime / 'moonray.exe')] + native.arguments(path, exr, 0, 'vectorized'), env=env, cwd=str(out), capture_output=True, text=True)
    subprocess.run([str(runtime / 'oiiotool.exe'), str(exr), '--ch', 'R,G,B', '--colorconvert', 'linear', 'sRGB', '-d', 'uint8', '-o', str(out / (case + '.png'))], env=env, capture_output=True)
    print(case, 'rc', done.returncode, '%.0f s' % (time.time() - started), [l.strip()[:120] for l in done.stdout.splitlines() if 'rror' in l][:2], flush=True)


for case, (shader, parameters) in CASES.items():
    if len(sys.argv) < 2 or case in sys.argv[1:]:
        render(case, shader, parameters)
