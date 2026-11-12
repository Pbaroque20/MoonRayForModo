"""Modo's Gradient on Bump Height, Displacement Height and Clip Distance in MoonRay and MoonLightIPR against Modo's own
render: probe_gui_gradient_heights.py's scenes as the kit captured each, rendered by each, and the input read back from
the glow (through the probe's ramp) at a few places on the surface, beside Modo's.
check_gradient_heights.py <runtime folder> [moonray|moonlightipr]..."""
import bisect
import json
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
W, H = 192, 128
compare.WIDTH, compare.HEIGHT = W, H
compare.fixture.WIDTH, compare.fixture.HEIGHT = W, H
compare.os.environ['MOONRAY_MODO_RUNTIME'] = str(runtime)
folder = ROOT / 'test-results/gradient-heights'
env = native.environment(runtime)
report = json.loads((folder / 'report.json').read_text())
curve = report['curve']
YS = [c[1] for c in curve]
# Pixels on the surface in every case (the planes fill the middle; the balls are centred).
PLACES = [(96, 64), (80, 56), (112, 72), (96, 80)]


def value_of(glow):
    i = min(max(bisect.bisect_left(YS, glow), 1), len(YS) - 1)
    (x0, y0), (x1, y1) = curve[i - 1], curve[i]
    return x0 + (glow - y0) * (x1 - x0) / ((y1 - y0) or 1)


def modo(case):
    exr = next(folder.glob('modo_%s.*exr' % case))
    pfm = folder / ('modo_%s_check.pfm' % case)
    subprocess.run([str(runtime / 'oiiotool.exe'), str(exr), '--ch', 'R,G,B', '-d', 'float', '-o', str(pfm)], env=env, capture_output=True)
    return struct.unpack('<%df' % (W * H * 3), pfm.read_bytes().split(b'\n', 3)[3][:W * H * 12])


session = None
worst = 0.0
try:
    if 'moonlightipr' in engines:
        session = compare.fixture.Session(folder)
        session.runtime = runtime
    for case in report['cases']:
        if not (folder / ('%s.pickle' % case)).is_file():
            continue
        scene = dict(pickle.loads((folder / ('%s.pickle' % case)).read_bytes()), _flat_out=True)
        pictures = {'Modo': modo(case)}
        for engine in engines:
            pictures[engine] = (compare.moonray(scene, runtime, folder, 'h_' + case) if engine == 'moonray'
                                else compare.moonlightipr(scene, session, 'h_' + case)[0])
        rows = {label: [value_of(p[(y * W + x) * 3]) for x, y in PLACES] for label, p in pictures.items()}
        print('== %s' % case)
        for label, line in rows.items():
            off = 0.0 if label == 'Modo' else max(abs(a - b) for a, b in zip(line, rows['Modo']))
            worst = max(worst, off)
            print('   %-12s %s%s' % (label, ' '.join('%6.3f' % v for v in line), '' if label == 'Modo' else '  (largest off %.3f)' % off), flush=True)
finally:
    if session is not None and session.process.poll() is None:
        session.process.kill()
print('largest difference from Modo: %.3f' % worst)
