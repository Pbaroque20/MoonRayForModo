"""Modo's Weight Map Texture in MoonLightIPR: the slab of probe_gui_weight_layer.py read across its weights beside Modo's own
render, and the layer on a DwaBaseMaterial (probe_cl_weight_layer_dwa.py), each side of the sphere.
check_moonlightipr_weight.py <runtime folder>"""
import pathlib
import pickle
import struct
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'kit/MoonRayForModo/python')]
import compare_moonlightipr as compare
from moonray_modo import native

runtime = native.find_runtime(sys.argv[1])
W, H = 320, 180
compare.WIDTH, compare.HEIGHT = W, H
compare.fixture.WIDTH, compare.fixture.HEIGHT = W, H
compare.os.environ['MOONRAY_MODO_RUNTIME'] = str(runtime)
folder = ROOT / 'test-results/weight-layer'
env = native.environment(runtime)


def modo_row(case):
    exr = next(folder.glob('modo_%s*.exr' % case))
    pfm = folder / ('modo_%s.pfm' % case)
    subprocess.run([str(runtime / 'oiiotool.exe'), str(exr), '--ch', 'R,G,B', '-d', 'float', '--flip', '-o', str(pfm)], env=env, capture_output=True)
    head, size, scale, data = pfm.read_bytes().split(b'\n', 3)
    return struct.unpack('<%df' % (W * H * 3), data)


def at(values, x, y):
    return values[(y * W + x) * 3] if len(values) == W * H * 3 else values[y * W + x][0]


session = compare.fixture.Session(folder)
session.runtime = runtime
try:
    for case in ('plain', 'bent'):
        scene = pickle.loads((folder / (case + '.pickle')).read_bytes())
        preview, warnings = compare.moonlightipr(scene, session, 'weight_' + case)
        reference = modo_row(case)
        focal = float(scene['camera'].get('focal_mm', 50)) / float(scene['camera'].get('film_mm', 36))
        half = focal * W / 3.0
        print(case, 'warnings', warnings)
        for weight in (.1, .25, .4, .5, .6, .75, .9):
            x = int(W / 2 + (2 * weight - 1) * half)
            print('  %.2f  Modo %.4f  MoonLightIPR %.4f' % (weight, at(reference, x, H // 2), at(preview, x, H // 2)), flush=True)
    dwa = ROOT / 'test-results/weight-layer-dwa'
    for effect in ('specAmount', 'rough'):
        scene = pickle.loads((dwa / (effect + '.pickle')).read_bytes())
        preview, warnings = compare.moonlightipr(scene, session, 'weight_' + effect)
        # The session's picture runs from the bottom row up; the sphere stands low in the picture.
        band = range(int(H * .15), int(H * .38))
        left = [at(preview, x, y) for y in band for x in range(int(W * .42), int(W * .49))]
        right = [at(preview, x, y) for y in band for x in range(int(W * .51), int(W * .58))]
        print(effect, 'warnings', warnings, 'left %.3f right %.3f' % (sum(left) / len(left), sum(right) / len(right)), flush=True)
    session.process.stdin.write(b'quit\n')
    session.process.stdin.flush()
    session.process.wait(timeout=10)
finally:
    if session.process.poll() is None:
        session.process.kill()
