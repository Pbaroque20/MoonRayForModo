"""Why the teapot of SSS_moonlight.lxo is greener in MoonLightIPR than in MoonRay: the scene read by probe_cl_snapshot_scene.py with its
material changed one thing at a time, in both renderers, and the colour on the same spots. check_sss_colour.py [case ...]."""
import copy
import os
import pickle
import struct
import subprocess
import sys
import tempfile
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
out = source / 'colour'
out.mkdir(parents=True, exist_ok=True)
env = native.environment(runtime)
W, H, SAMPLES = 250, 250, 8
SPOTS = {'body': (120, 130, 45, 45), 'lid': (130, 85, 30, 15), 'spout': (30, 125, 20, 15)}
base = pickle.loads((source / 'snapshot.pickle').read_bytes())
base.update(width=W, height=H, aovs=['alpha'], custom_aovs=[], preview_buffer='beauty')
base['render_settings'] = options.render_values(dict(base.get('render_settings') or {}, sampling_mode=0, pixel_samples=SAMPLES))
NOTHING = [0.0, 0.0, 0.0]
CASES = {'saved': (None, {}),
         'no-diffuse-transmission': (None, {'diffuse_transmission_color': NOTHING}),
         'no-specular': (None, {'show_specular': False}),
         'no-transmission-no-specular': (None, {'diffuse_transmission_color': NOTHING, 'show_specular': False}),
         'no-diffuse-roughness': (None, {'diffuse_roughness': 0.0}),
         'base-material': ('DwaBaseMaterial', None),
         'bare-no-clamp': (None, {'diffuse_transmission_color': NOTHING, 'show_specular': False}, {'sample_clamping_value': 0.0}),
         'bare-no-bounces': (None, {'diffuse_transmission_color': NOTHING, 'show_specular': False}, {'max_diffuse_depth': 0, 'max_glossy_depth': 0, 'max_depth': 0}),
         'bare-many-subsurface': (None, {'diffuse_transmission_color': NOTHING, 'show_specular': False}, {'max_subsurface_per_path': 8}),
         'saved-no-bounces': (None, {}, {'max_diffuse_depth': 0, 'max_glossy_depth': 0, 'max_depth': 0}),
         'saved-many-subsurface': (None, {}, {'max_subsurface_per_path': 8}),
         'lambert-through': (None, {'scattering_radius': 0.0, 'show_specular': False}),
         'lambert-through-bright': (None, {'scattering_radius': 0.0, 'show_specular': False, 'diffuse_transmission_color': [0.8, 0.8, 0.8]}),
         'walk-through-no-limit': (None, {'show_specular': False}, {'max_subsurface_per_path': 8}),
         'walk-through-no-subsurface-bounce': (None, {'show_specular': False}, {'max_subsurface_per_path': 1}),
         'saved-resolve-on': (None, {'resolve_self_intersections': True}),
         'through-only-no-walk-bounce': (None, {'show_specular': False}, {'max_subsurface_per_path': 0}),
         'through-one-bounce': (None, {'show_specular': False}, {'max_diffuse_depth': 1}),
         'saved-no-specular-no-bounces': (None, {'show_specular': False}, {'max_diffuse_depth': 0, 'max_glossy_depth': 0, 'max_depth': 0})}
BASE_KEYS = ('albedo', 'bssrdf', 'scattering_color', 'scattering_radius', 'resolve_self_intersections')


def scene_for(shader, changes):
    scene = dict(base)
    scene['materials'] = copy.deepcopy(base['materials'])
    for material in scene['materials'].values():
        for layer in [material] + list(material.get('material_stack') or []):
            if layer.get('native_shader') != 'DwaSkinMaterial':
                continue
            held = layer.get('native_parameters') or {}
            parameters = {key: held[key] for key in BASE_KEYS if key in held} if shader else dict(held, **changes)
            layer['native_parameters'] = parameters
            if shader:
                layer['native_shader'] = shader
            if layer.get('node_graph'):
                graph = layer['node_graph']
                node = graph['nodes'][graph['root']]
                node['parameters'] = dict(parameters)
                if shader:
                    node['type'] = shader
    return scene


def pixels(path):
    with tempfile.TemporaryDirectory() as held:
        target = Path(held) / 'p.pfm'
        subprocess.run([str(runtime / 'oiiotool.exe'), str(path)] + (['--ch', 'R,G,B'] if str(path).endswith('.exr') else []) + ['-d', 'float', '-o', str(target)], env=env, capture_output=True)
        data = target.read_bytes()
    parts = data.split(b'\n', 3)
    w, h = (int(v) for v in parts[1].split())
    return w, h, struct.unpack('<%df' % (w * h * 3), parts[3][:w * h * 12])


def average(picture, x, y, width, height):
    w, h, values = picture
    total = [0.0, 0.0, 0.0]
    for row in range(y, y + height):
        start = (h - 1 - row) * w + x
        for column in range(width):
            for c in range(3):
                total[c] += values[3 * (start + column) + c]
    return [round(t / (width * height), 3) for t in total]


compare.WIDTH, compare.HEIGHT = W, H
compare.fixture.WIDTH, compare.fixture.HEIGHT = W, H
light = compare.fixture.Session(out)
light.runtime = runtime
try:
    for case in sys.argv[1:] or CASES:
        shader, changes, *settings = CASES[case]
        scene = scene_for(shader, changes)
        if settings:
            scene['render_settings'] = options.render_values(dict(scene['render_settings'], **settings[0]))
        exr = out / (case + '.exr')
        path = out / (case + '.rdla')
        path.write_text(rdla.scene_text(scene, W, H, SAMPLES, 0, str(exr)), encoding='utf-8')
        subprocess.run([str(runtime / 'moonray.exe')] + native.arguments(path, exr, 0, 'vectorized'), env=env, cwd=str(out), capture_output=True, text=True)
        preview, warnings = compare.moonlightipr(dict(scene, _environment=0), light, case)
        pfm = out / (case + '.pfm')
        pfm.write_bytes(('PF\n%d %d\n-1.0\n' % (W, H)).encode() + struct.pack('<%df' % (W * H * 3), *preview))
        mr, ml = pixels(exr), pixels(pfm)
        for name, spot in SPOTS.items():
            print('%-28s %-6s MoonRay %-24s MoonLightIPR %s' % (case, name, average(mr, *spot), average(ml, *spot)), flush=True)
    light.process.stdin.write(b'quit\n')
    light.process.stdin.flush()
    light.process.wait(timeout=10)
finally:
    if light.process.poll() is None:
        light.process.kill()
