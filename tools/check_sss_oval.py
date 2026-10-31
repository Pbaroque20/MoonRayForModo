"""The dark oval at the base of the teapot's spout in SSS_moonlight.lxo, which MoonLightIPR draws and MoonRay does not: the scene read by
probe_cl_snapshot_scene.py, its material changed one thing at a time. check_sss_oval.py [case ...] writes
test-results/sss-teapot/cases/<case>-<renderer>.png, and -spout.png, the spout enlarged."""
import copy
import os
import pickle
import struct
import subprocess
import sys
from pathlib import Path
os.environ['MOONRAY_MODO_PREFERENCES'] = 'TestPreview'
for folder in (r'C:\Program Files\Modo16.1v9\modo', r'C:\Program Files\Modo16.1v9\modo\resrc\python3kit\extra64'):
    os.add_dll_directory(folder)
ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / 'dist/personal-kit/Luxology/Kits/MoonRayForModo'
sys.path[:0] = [str(ROOT / 'tools'), str(KIT / 'python')]
runtime = KIT / 'runtime'
os.environ['MOONRAY_MODO_RUNTIME'] = str(runtime)
from PySide2 import QtCore
app = QtCore.QCoreApplication([])
from moonray_modo import native, options, rdla
import compare_moonlightipr as compare

source = ROOT / 'test-results/sss-teapot'
out = source / 'cases'
out.mkdir(parents=True, exist_ok=True)
env = native.environment(runtime)
W, H, SAMPLES = 500, 500, 4
base = pickle.loads((source / 'snapshot.pickle').read_bytes())
base.update(width=W, height=H, aovs=['alpha'], custom_aovs=[], preview_buffer='beauty')
base['render_settings'] = options.render_values(dict(base.get('render_settings') or {}, sampling_mode=0, pixel_samples=SAMPLES))
CASES = {'saved': ({}, ('moonlightipr',)),
         'diffusion': ({'bssrdf': 0}, ('moonlightipr',)),
         'no-scattering': ({'show_diffuse': True, 'scattering_radius': 0.0}, ('moonlightipr',)),
         'small-radius': ({'scattering_radius': 0.05}, ('moonlightipr',)),
         'resolve-on': ({'resolve_self_intersections': True}, ('moonray',)),
         'diffusion-moonray': ({'bssrdf': 0}, ('moonray',))}


def scene_for(changes):
    scene = dict(base)
    scene['materials'] = copy.deepcopy(base['materials'])
    found = 0
    for material in scene['materials'].values():
        for layer in [material] + list(material.get('material_stack') or []):
            if layer.get('native_shader') == 'DwaSkinMaterial':
                layer['native_parameters'] = dict(layer.get('native_parameters') or {}, **changes)
                if layer.get('node_graph'):
                    graph = layer['node_graph']
                    node = graph['nodes'][graph['root']]
                    node['parameters'] = dict(node.get('parameters') or {}, **changes)
                found += 1
    assert found
    return scene


def picture(image, name):
    subprocess.run([str(runtime / 'oiiotool.exe'), str(image)] + (['--ch', 'R,G,B'] if str(image).endswith('.exr') else []) +
                   ['--colorconvert', 'linear', 'sRGB', '-d', 'uint8', '-o', str(out / (name + '.png'))], env=env, capture_output=True)
    subprocess.run([str(runtime / 'oiiotool.exe'), str(out / (name + '.png')), '--crop', '100x90+90+250', '--fullpixels', '--resize', '400x360', '-o', str(out / (name + '-spout.png'))],
                   env=env, capture_output=True)


light = None
wanted = sys.argv[1:] or list(CASES)
for case in wanted:
    changes, renderers = CASES[case]
    scene = scene_for(changes)
    for renderer in renderers:
        name = '%s-%s' % (case, renderer)
        if renderer == 'moonray':
            exr = out / (name + '.exr')
            path = out / (name + '.rdla')
            path.write_text(rdla.scene_text(scene, W, H, SAMPLES, 0, str(exr)), encoding='utf-8')
            done = subprocess.run([str(runtime / 'moonray.exe')] + native.arguments(path, exr, 0, 'vectorized'), env=env, cwd=str(out), capture_output=True, text=True)
            print(name, 'rc', done.returncode, flush=True)
            picture(exr, name)
        else:
            compare.WIDTH, compare.HEIGHT = W, H
            compare.fixture.WIDTH, compare.fixture.HEIGHT = W, H
            if light is None:
                light = compare.fixture.Session(out)
                light.runtime = runtime
            preview, warnings = compare.moonlightipr(dict(scene, _environment=0), light, name)
            pfm = out / (name + '.pfm')
            pfm.write_bytes(('PF\n%d %d\n-1.0\n' % (W, H)).encode() + struct.pack('<%df' % (W * H * 3), *preview))
            print(name, warnings, flush=True)
            picture(pfm, name)
if light is not None:
    light.process.stdin.write(b'quit\n')
    light.process.stdin.flush()
    light.process.wait(timeout=10)
