"""Modo's Process texture in MoonRay and MoonLightIPR against Modo's own render: each scene of probe_cl_process_scenes.py
rendered small by both, and the colour in the middle of each picture beside Modo's (test-results/process-layer/
measured.json, from probe_gui_process_layer.py). check_process_layer.py <runtime folder> [moonray|moonlightipr]..."""
import json
import pathlib
import pickle
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'kit/MoonRayForModo/python')]
import compare_moonlightipr as compare
from moonray_modo import native

runtime = native.find_runtime(sys.argv[1])
engines = sys.argv[2:] or ['moonray', 'moonlightipr']
W, H = 64, 36
compare.WIDTH, compare.HEIGHT = W, H
compare.fixture.WIDTH, compare.fixture.HEIGHT = W, H
compare.os.environ['MOONRAY_MODO_RUNTIME'] = str(runtime)
folder = ROOT / 'test-results/process-layer'
measured = json.loads((folder / 'measured.json').read_text())


def middle(values):
    i = ((H // 2) * W + W // 2) * 3
    return values[i:i + 3]


session = None
worst = {engine: 0.0 for engine in engines}
try:
    if 'moonlightipr' in engines:
        session = compare.fixture.Session(folder)
        session.runtime = runtime
    for pickled in sorted(folder.glob('*.pickle')):
        case = pickled.stem
        scene = pickle.loads(pickled.read_bytes())
        want = measured[case]
        line = '%-18s Modo %s' % (case, ' '.join('%.3f' % v for v in want))
        for engine in engines:
            if engine == 'moonray':
                got = middle(compare.moonray(scene, runtime, folder, 'process_' + case))
            else:
                got = middle(compare.moonlightipr(scene, session, 'process_' + case)[0])
            off = max(abs(a - b) for a, b in zip(got, want))
            worst[engine] = max(worst[engine], off)
            line += '   %s %s (off %.3f)' % (engine, ' '.join('%.3f' % v for v in got), off)
        print(line, flush=True)
    print('largest difference: ' + ', '.join('%s %.4f' % kv for kv in worst.items()))
finally:
    if session is not None and session.process.poll() is None:
        session.process.kill()
