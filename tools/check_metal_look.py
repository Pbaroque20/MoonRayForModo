"""A DwaMetalMaterial as car paint, on the MoonRay Widget's model, in MoonRay, XPU2 and MoonLightIPR with the same lights: for a
report that it looks like plastic in MoonRay and like metal in MoonLightIPR. check_metal_look.py writes
test-results/metal-look/<case>-<renderer>.png, and prints what each renderer's lights and environment make of it."""
import json
import os
import pickle
import struct
import subprocess
import sys
import time
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
import compare_moonlightipr as compare
from moonray_modo import native, options, persistent, rdla
from moonray_modo.material_preview import snapshot
from moonray_modo.preferences import Preferences

out = ROOT / 'test-results/metal-look'
out.mkdir(parents=True, exist_ok=True)
env = native.environment(runtime)
W, H = 400, 400
compare.WIDTH, compare.HEIGHT = W, H
compare.fixture.WIDTH, compare.fixture.HEIGHT = W, H
FLAKES = r'C:\Users\Raphael Tobar\Downloads\Lamborghini(1)\imported_images\JP-FlakeNORM_2K.png'
PAINT = {'metallic_color': [0.7680719, 0.4884318, 0.0706326], 'metallic_edge_color': [1.0, 0.0, 0.0], 'show_clearcoat': True, 'specular_model': 0}


def paint(image):
    """The Lamborghini's paint as the scene stores it, its flake normal at this path; None, no normal map."""
    nodes_ = {'surface': {'type': 'DwaMetalMaterial', 'parameters': dict(PAINT), 'inputs': {}, 'position': [680, -80]}}
    if image is not None:
        nodes_['uv'] = {'type': 'UVTransformMap', 'inputs': {}, 'position': [-360, -140], 'parameters': {
            'offset': [0.0, 0.0], 'rotation_angle': 0.0, 'rotation_axis': [0.0, 0.0, 1.0], 'rotation_center': [0.5, 0.5], 'scale': [5.0, 5.0], 'space': 6}}
        nodes_['flakes'] = {'type': 'image', 'inputs': {'texcoord': 'uv'}, 'position': [-40, 20], 'parameters': {
            'channel': 0, 'color_space': '', 'default': [0.0, 0.0, 0.0], 'file': image, 'filtertype': 'linear', 'scale': [1.0, 1.0], 'srgb': False,
            'texcoord': [0.0, 0.0, 0.0], 'uaddressmode': 'periodic', 'uv_map': '', 'vaddressmode': 'periodic'}}
        nodes_['normal'] = {'type': 'normalmap', 'inputs': {'in': 'flakes'}, 'position': [260, 80], 'parameters': {
            'basis_mode': 0, 'basis_offset': [0.0, 0.0], 'basis_rotation': 0.0, 'basis_scale': [1.0, 1.0], 'in': [0.5, 0.5, 1.0], 'scale': 1.0, 'uv_map': ''}}
        nodes_['surface']['inputs']['input_normal'] = 'normal'
    return {'version': 1, 'root': 'surface', 'overrides': [], 'nodes': nodes_}


CASES = {'flakes': paint(FLAKES), 'missing': paint('V:/-=Textures=-/JeffPatton/JP-FlakeNORM_2K.png'), 'none': paint(None)}


def varied(**parameters):
    graph = paint(None)
    graph['nodes']['surface']['parameters'].update(parameters)
    return graph


CASES.update({'white-edge': varied(metallic_edge_color=[1.0, 1.0, 1.0]), 'no-coat': varied(show_clearcoat=False),
              'rough-.2': varied(roughness=.2), 'ggx': varied(specular_model=1)})


def scene_of(graph):
    material = {'shader': 'DwaBaseMaterial', 'moonshine_override': True, 'native_shader': 'DwaMetalMaterial', 'native_parameters': dict(graph['nodes']['surface']['parameters']),
                'node_graph': graph, 'node_override': True, 'color': [.5, .5, .5], 'roughness': .3}
    scene = snapshot(material, {}, True)
    scene.update(width=W, height=H, aovs=['alpha'], custom_aovs=[], preview_buffer='beauty', _environment=.5)
    scene['render_settings'] = options.render_values({'sampling_mode': 0, 'pixel_samples': 8})
    return scene


def describe(values, w, h):
    # The ball's middle, where a metal has no diffuse of its own: how bright the darkest and brightest of its surface are.
    box = [sum(values[(y * w + x) * 3:(y * w + x) * 3 + 3]) / 3 for y in range(int(h * .4), int(h * .75)) for x in range(int(w * .35), int(w * .65))]
    box.sort()
    return 'ball: darkest tenth %.3f, middle %.3f, brightest tenth %.3f' % (box[len(box) // 10], box[len(box) // 2], box[-len(box) // 10])


def png(values, w, h, name):
    pfm = out / (name + '.pfm')
    pfm.write_bytes(('PF\n%d %d\n-1.0\n' % (w, h)).encode() + struct.pack('<%df' % (w * h * 3), *values))
    subprocess.run([str(runtime / 'oiiotool.exe'), str(pfm), '--colorconvert', 'linear', 'sRGB', '-d', 'uint8', '-o', str(out / (name + '.png'))], env=env, capture_output=True)


def moonray(scene, name):
    exr = out / (name + '.exr')
    text = rdla.scene_text(scene, W, H, 8, .5, str(exr))
    path = out / (name + '.rdla')
    path.write_text(text, encoding='utf-8')
    done = subprocess.run([str(runtime / 'moonray.exe')] + native.arguments(path, exr, 0, 'vectorized'), env=env, cwd=str(out), capture_output=True, text=True)
    pfm = out / (name + '.pfm')
    subprocess.run([str(runtime / 'oiiotool.exe'), str(exr), '--ch', 'R,G,B', '-d', 'float', '--flip', '-o', str(pfm)], env=env, capture_output=True)
    head, size, scale, data = pfm.read_bytes().split(b'\n', 3)
    w, h = map(int, size.split())
    subprocess.run([str(runtime / 'oiiotool.exe'), str(exr), '--ch', 'R,G,B', '--colorconvert', 'linear', 'sRGB', '-d', 'uint8', '-o', str(out / (name + '.png'))], env=env, capture_output=True)
    return struct.unpack('<%df' % (w * h * 3), data), w, h, text


def xpu2(text):
    store = Preferences().store
    store.setValue('xpu2/renderer', 'xpu2')
    store.sync()
    session = persistent.Session()
    last, finished = {}, []
    session.memory_image.connect(lambda p: last.__setitem__(p[1], p))
    session.ready.connect(lambda g: finished.append(g))
    session.failed.connect(lambda m: (print('  failed', m[:200]), finished.append(-1)))
    session.submit(text, runtime, 0, 'xpu', 1)
    deadline = time.time() + 120
    while not finished and time.time() < deadline:
        app.processEvents()
        time.sleep(.02)
    active = getattr(session, 'xpu2_active', None), getattr(session, 'xpu2_refused', None)
    session.close()
    for _ in range(50):
        app.processEvents()
        time.sleep(.02)
    store.remove('xpu2/renderer')
    return last.get('beauty'), active


light = compare.fixture.Session(out)
light.runtime = runtime
try:
    for case, graph in CASES.items():
        scene = scene_of(graph)
        values, w, h, text = moonray(scene, case + '-moonray')
        print('%-8s MoonRay       %s | scene warnings %s | black into a normal: %s' % (case, describe(values, w, h), scene.get('warnings'), 'ConstantColorMap' in text and '"color_value"] = Rgb(0, 0, 0)' in text), flush=True)
        preview, warnings = compare.moonlightipr(scene, light, case)
        print('%-8s MoonLightIPR  %s %s' % (case, describe(preview, W, H), warnings), flush=True)
        png(preview, W, H, case + '-moonlightipr')
    light.process.stdin.write(b'quit\n')
    light.process.stdin.flush()
    light.process.wait(timeout=10)
finally:
    if light.process.poll() is None:
        light.process.kill()
