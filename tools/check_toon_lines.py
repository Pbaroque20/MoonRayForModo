"""The Toon display filter on the MoonRay Widget's model, outside Modo: each Output Mode, and each edge detector's ink, for
gaps down the middle of its lines. check_toon_lines.py [runtime folder]. Writes test-results/toon-lines/."""
import json
import os
import struct
import subprocess
import sys
from pathlib import Path
os.environ['MOONRAY_MODO_PREFERENCES'] = 'TestPreview'
for folder in (r'C:\Program Files\Modo16.1v9\modo', r'C:\Program Files\Modo16.1v9\modo\resrc\python3kit\extra64'):
    os.add_dll_directory(folder)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
runtime = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'dist/personal-kit/Luxology/Kits/MoonRayForModo/runtime'
os.environ['MOONRAY_MODO_RUNTIME'] = str(runtime)
from PySide2 import QtCore
app = QtCore.QCoreApplication([])
from moonray_modo import entities, native, options, rdla
from moonray_modo.material_preview import snapshot

out = ROOT / 'test-results/toon-lines' / runtime.name
out.mkdir(parents=True, exist_ok=True)
env = native.environment(runtime)
W, H = 512, 512


def render(tag, **parameters):
    scene = snapshot({'color': [.7, .65, .4], 'roughness': .5}, {}, True)
    scene.update(width=W, height=H, aovs=['alpha'], custom_aovs=[], preview_buffer='beauty')
    scene['render_settings'] = options.render_values({'sampling_mode': 0, 'pixel_samples': 8})
    toon = {'identity': 'toon', 'name': 'Toon', 'class': 'ToonDisplayFilter',
            'parameters': dict({'input_diffuse': 'Direct diffuse', 'input_glossy': 'Direct glossy', 'input_albedo': 'Albedo', 'input_depth': 'Camera depth', 'input_normal': 'Shading normal', 'num_cels': 4, 'ink_depth_threshold': .01, 'ink_normal_threshold': .1, 'ink_normal_scale': 1.0}, **parameters)}
    scene['entities'] = [toon]
    exr = out / (tag + '.exr')
    text = rdla.scene_text(scene, W, H, 8, .2, str(exr))
    path = out / (tag + '.rdla')
    path.write_text(text, encoding='utf-8')
    done = subprocess.run([str(runtime / 'moonray.exe')] + native.arguments(path, exr, 0, 'vectorized'), env=env, cwd=str(out), capture_output=True, text=True)
    files = [exr]
    if done.returncode:
        print(tag, 'failed', done.stdout[-500:])
        return None
    warned = [l.strip()[:140] for l in done.stdout.splitlines() if 'output_mode' in l or 'edge_detector' in l or 'Toon' in l and ('warn' in l.lower() or 'error' in l.lower())]
    return files, warned, text


def pixels(path):
    pfm = path.with_suffix('.pfm')
    subprocess.run([str(runtime / 'oiiotool.exe'), str(path), '--ch', 'R=Toon.R,G=Toon.G,B=Toon.B', '-d', 'float', '--flip', '-o', str(pfm)], env=env, capture_output=True)
    head, size, scale, data = pfm.read_bytes().split(b'\n', 3)
    w, h = map(int, size.split())
    subprocess.run([str(runtime / 'oiiotool.exe'), str(path), '--ch', 'R=Toon.R,G=Toon.G,B=Toon.B', '--colorconvert', 'linear', 'sRGB', '-d', 'uint8', '-o', str(path.with_suffix('.png'))], env=env, capture_output=True)
    values = struct.unpack('<%df' % (w * h * 3), data)
    return [[values[(y * w + x) * 3] for x in range(w)] for y in range(h)], w, h


def gaps(rows, w, h):
    """Pixels free of ink with ink either side, along a row, a column or a diagonal: a thin gap in a line. Lines only: ink
    is white."""
    count = ink = 0
    for y in range(2, h - 2):
        for x in range(2, w - 2):
            if rows[y][x] > .5:
                ink += 1
                continue
            for a, b in ((1, 0), (0, 1), (1, 1), (1, -1)):
                if rows[y + b][x + a] > .5 and rows[y - b][x - a] > .5:
                    count += 1
                    break
    return count, ink


def timed(tag, **parameters):
    import time
    start = time.time()
    result = render(tag, **parameters)
    return result, time.time() - start


for mode, name in ((0, 'shading and lines'), (1, 'lines only'), (2, 'shading only')):
    result, took = timed('mode%d' % mode, edge_detector=3, output_mode=mode, close_line_gaps=True)
    if result:
        rows, w, h = pixels(result[0][0])
        flat = [v for row in rows for v in row]
        print('Output Mode %-18s Toon channel mean %.3f' % (name, sum(flat) / len(flat)), flush=True)
for detector, name in ((1, 'Sobel'), (2, 'Laplacian'), (3, 'Laplacian of Gaussian')):
    for closing in (False, True):
        tag = 'edges%d-%s' % (detector, 'closed' if closing else 'open')
        result, took = timed(tag, edge_detector=detector, output_mode=1, close_line_gaps=closing)
        if result:
            rows, w, h = pixels(result[0][0])
            found, ink = gaps(rows, w, h)
            print('%-22s %-6s ink %6d  one-pixel gaps %5d  %.1f s %s' % (name, 'closed' if closing else 'open', ink, found, took, result[1][:1]), flush=True)
