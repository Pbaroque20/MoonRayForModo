"""Modo's Gradient on Texture U and V in MoonRay and MoonLightIPR against Modo's own render: probe_gui_gradient_uv.py's
plane as the kit captured each case, rendered by each, and U or V read back from the glow (through the probe's ramp)
along a row and a column, beside Modo's. check_gradient_uv.py <runtime folder> [moonray|moonlightipr]..."""
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
W, H = 384, 256
compare.WIDTH, compare.HEIGHT = W, H
compare.fixture.WIDTH, compare.fixture.HEIGHT = W, H
compare.os.environ['MOONRAY_MODO_RUNTIME'] = str(runtime)
folder = ROOT / 'test-results/gradient-uv'
env = native.environment(runtime)
report = json.loads((folder / 'report.json').read_text())
curve = report['curve']
WIDE, HIGH = 7.2, 4.8
YS = [c[1] for c in curve]


def value_of(glow, side=None):
    """The input the probe's ramp (rising through its keys at -20, 0 and 20) gives this glow for."""
    i = min(max(bisect.bisect_left(YS, glow), 1), len(YS) - 1)
    (x0, y0), (x1, y1) = curve[i - 1], curve[i]
    return x0 + (glow - y0) * (x1 - x0) / ((y1 - y0) or 1)


def modo(case):
    exr = next(folder.glob('modo_%s.*exr' % case))
    pfm = folder / ('modo_%s_check.pfm' % case)
    subprocess.run([str(runtime / 'oiiotool.exe'), str(exr), '--ch', 'R,G,B', '-d', 'float', '-o', str(pfm)], env=env, capture_output=True)
    return struct.unpack('<%df' % (W * H * 3), pfm.read_bytes().split(b'\n', 3)[3][:W * H * 12])


def glow(values, x, y):
    return values[(int((y / HIGH + .5) * H) * W + int((x / WIDE + .5) * W)) * 3]


# Where each case is read, and what U or V is there.
PLACES = [(x, .6) for x in (-1.6, -1.1, -.6, -.1, .1, .6, 1.1, 1.6)] + [(.6, y) for y in (-1.6, -.6, .4, 1.4)]
EXPECTED = {'u_default': lambda x, y: x, 'v_default': lambda x, y: y, 'u_moved': lambda x, y: (x - 1) / 2,
            'u_uv': lambda x, y: (x + 2) / 4, 'v_uv': lambda x, y: (y + 2) / 4,
            'u_planar_z': lambda x, y: (x + .5) % 1.0, 'v_planar_z': lambda x, y: (y + .5) % 1.0}
session = None
try:
    if 'moonlightipr' in engines:
        session = compare.fixture.Session(folder)
        session.runtime = runtime
    for case, truth in EXPECTED.items():
        scene = dict(pickle.loads((folder / ('%s.pickle' % case)).read_bytes()), _flat_out=True)
        pictures = {'Modo': modo(case)}
        for engine in engines:
            pictures[engine] = (compare.moonray(scene, runtime, folder, 'uv_' + case) if engine == 'moonray'
                                else compare.moonlightipr(scene, session, 'uv_' + case)[0])
        print('== %s (true value: %s)' % (case, ' '.join('%.3f' % truth(x, y) for x, y in PLACES)))
        rows = {label: [value_of(glow(p, x, y), truth(x, y)) for x, y in PLACES] for label, p in pictures.items()}
        for label, line in rows.items():
            off = '' if label == 'Modo' else '  (largest off %.3f)' % max(abs(a - b) for a, b in zip(line, rows['Modo']))
            print('   %-12s %s%s' % (label, ' '.join('%6.3f' % v for v in line), off), flush=True)
finally:
    if session is not None and session.process.poll() is None:
        session.process.kill()
