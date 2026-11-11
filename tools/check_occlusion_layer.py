"""Modo's Occlusion texture in MoonRay and MoonLightIPR against Modo's own render: the fine-floor scenes of
probe_cl_occlusion_scene.py rendered by each, and the floor's glow across the picture's middle row, near the wall,
beside Modo's render of the same floor (probe_gui_occlusion_layer.py). check_occlusion_layer.py <runtime folder>
[moonray|moonlightipr]..."""
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
W, H = 256, 64
compare.WIDTH, compare.HEIGHT = W, H
compare.fixture.WIDTH, compare.fixture.HEIGHT = W, H
compare.os.environ['MOONRAY_MODO_RUNTIME'] = str(runtime)
folder = ROOT / 'test-results/occlusion-layer'
env = native.environment(runtime)


def modo(case):
    exr = next(folder.glob('modo_%s.*exr' % case))
    pfm = folder / ('modo_%s_check.pfm' % case)
    subprocess.run([str(runtime / 'oiiotool.exe'), str(exr), '--ch', 'R,G,B', '-d', 'float', '-o', str(pfm)], env=env, capture_output=True)
    head = pfm.read_bytes().split(b'\n', 3)
    return struct.unpack('<%df' % (W * H * 3), head[3][:W * H * 12])


COLUMNS = [int(f * W) for f in (0.105, 0.11, 0.115, 0.12, 0.13, 0.14, 0.16, 0.18, 0.2, 0.3)]
session = None
try:
    if 'moonlightipr' in engines:
        session = compare.fixture.Session(folder)
        session.runtime = runtime
    for case in ('default', 'dist1'):
        scene = pickle.loads((folder / ('occ_%s.pickle' % case)).read_bytes())
        rows = {'Modo': modo(case)}
        for engine in engines:
            if engine == 'moonray':
                rows[engine] = compare.moonray(scene, runtime, folder, 'occ_' + case)
            else:
                rows[engine] = compare.moonlightipr(scene, session, 'occ_' + case)[0]
        print('== %s (distance from the wall: %s)' % (case, ' '.join('%.3f' % (5.0 * (x + .5) / W - .5) for x in COLUMNS)))
        for label, values in rows.items():
            line = [values[((H // 2) * W + x) * 3] for x in COLUMNS]
            off = '' if label == 'Modo' else '  (largest off %.3f)' % max(abs(a - values_m) for a, values_m in zip(line, [rows['Modo'][((H // 2) * W + x) * 3] for x in COLUMNS]))
            print('   %-12s %s%s' % (label, ' '.join('%6.3f' % v for v in line), off), flush=True)
finally:
    if session is not None and session.process.poll() is None:
        session.process.kill()
