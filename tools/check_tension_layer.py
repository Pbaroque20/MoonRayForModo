"""Modo's Tension texture in MoonRay and MoonLightIPR against Modo's own render: the stretched, sheared and folded squares
of probe_gui_tension_layer.py as the kit captured them, rendered by each, and the tension read back from each square's
glow (through the layer's ramp, kept by the probe) along a row across it, beside Modo's.
check_tension_layer.py <runtime folder> [moonray|moonlightipr]..."""
import bisect
import json
import math
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
engines = sys.argv[2:] or ['moonray', 'moonlightipr']
W, H = 768, 512
compare.WIDTH, compare.HEIGHT = W, H
compare.fixture.WIDTH, compare.fixture.HEIGHT = W, H
compare.os.environ['MOONRAY_MODO_RUNTIME'] = str(runtime)
folder = ROOT / 'test-results/tension'
env = native.environment(runtime)
report = json.loads((folder / 'report.json').read_text())
curve = report['curve']
ys = [c[1] for c in curve]
Z = 30.0
WIDE, HIGH = 36 / 50.0 * Z, 24 / 50.0 * Z


def tension_of(glow):
    i = min(max(bisect.bisect_left(ys, glow), 1), len(ys) - 1)
    (x0, y0), (x1, y1) = curve[i - 1], curve[i]
    return x0 + (glow - y0) * (x1 - x0) / ((y1 - y0) or 1)


def modo(kind):
    exr = next(folder.glob('modo_%s.*exr' % kind))
    pfm = folder / ('modo_%s_check.pfm' % kind)
    subprocess.run([str(runtime / 'oiiotool.exe'), str(exr), '--ch', 'R,G,B', '-d', 'float', '-o', str(pfm)], env=env, capture_output=True)
    head = pfm.read_bytes().split(b'\n', 3)
    width, height = (int(v) for v in head[1].split())
    return struct.unpack('<%df' % (width * height * 3), head[3][:width * height * 12]), width, height


def at(picture, x, y):
    values, width, height = picture
    return values[(int((y / HIGH + .5) * height) * width + int((x / WIDE + .5) * width)) * 3]


session = None
try:
    if 'moonlightipr' in engines:
        session = compare.fixture.Session(folder)
        session.runtime = runtime
    for kind in ('area', 'angle'):
        scene = dict(pickle.loads((folder / ('%s.pickle' % kind)).read_bytes()), _flat_out=True)
        pictures = {'Modo': modo(kind)}
        for engine in engines:
            if engine == 'moonray':
                pictures[engine] = (compare.moonray(scene, runtime, folder, 'tension_' + kind), W, H)
            else:
                pictures[engine] = (compare.moonlightipr(scene, session, 'tension_' + kind)[0], W, H)
        print('== %s' % kind)
        for (cx, cy), (sx, sy, k, fold, half) in report['bands']:
            print('  %s' % str((sx, sy, k, fold, half)))
            places = []
            for t in (-.4, -.3, -.2, -.1, -.03, .1, .2, .3, .4):
                x = t * (sx if not half else (1 if t < 0 else sx))
                if fold and t > 0:
                    x = t * math.cos(math.radians(fold))
                places.append((cx + x, cy + .1 * sy))
            rows = {label: [tension_of(at(p, x, y)) for x, y in places] for label, p in pictures.items()}
            for label, line in rows.items():
                off = '' if label == 'Modo' else '  (largest off %.3f)' % max(abs(a - b) for a, b in zip(line, rows['Modo']))
                print('     %-12s %s%s' % (label, ' '.join('%6.3f' % v for v in line), off), flush=True)
finally:
    if session is not None and session.process.poll() is None:
        session.process.kill()
