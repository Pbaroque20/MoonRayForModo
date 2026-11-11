"""Modo's Gradient on its Sample and Surface Parameters in MoonRay and MoonLightIPR against Modo's own render: each sphere
scene of probe_gui_gradient_inputs.py rendered by each, and the value along the picture's middle row and column (away
from the sphere's edge) beside Modo's. check_gradient_inputs.py <runtime folder> [moonray|moonlightipr]... [-- input...]"""
import pathlib
import pickle
import struct
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'kit/MoonRayForModo/python')]
import compare_moonlightipr as compare
from moonray_modo import native

args = sys.argv[1:]
runtime = native.find_runtime(args[0])
rest = args[1:]
only = rest[rest.index('--') + 1:] if '--' in rest else []
engines = [a for a in (rest[:rest.index('--')] if '--' in rest else rest)] or ['moonray', 'moonlightipr']
W = H = 128
compare.WIDTH, compare.HEIGHT = W, H
compare.fixture.WIDTH, compare.fixture.HEIGHT = W, H
compare.os.environ['MOONRAY_MODO_RUNTIME'] = str(runtime)
folder = ROOT / 'test-results/gradient-inputs'
env = native.environment(runtime)


def modo(name):
    """Modo's render, scaled to W x H, bottom row first as the renderers' pictures are (PFM is written bottom up)."""
    exr = next(folder.glob('modo_%s.*exr' % name))
    pfm = folder / ('modo_%s_small.pfm' % name)
    subprocess.run([str(runtime / 'oiiotool.exe'), str(exr), '--ch', 'R,G,B', '--resize', '%dx%d' % (W, H), '-d', 'float', '-o', str(pfm)],
                   env=env, capture_output=True)
    head = pfm.read_bytes().split(b'\n', 3)
    return struct.unpack('<%df' % (W * H * 3), head[3][:W * H * 12])


def at(values, x, y):
    return values[(y * W + x) * 3]


# The sphere spans about 42% of the picture across its middle (probe_gui_gradient_inputs.py: radius 54 of 256 pixels).
PLACES = [(int(W * f), H // 2) for f in (.36, .42, .47, .5, .53, .58, .64)] + [(W // 2, int(H * f)) for f in (.36, .44, .56, .64)]
session = None
try:
    if 'moonlightipr' in engines:
        session = compare.fixture.Session(folder)
        session.runtime = runtime
    for pickled in sorted(folder.glob('*.pickle')):
        name = pickled.stem
        if only and name not in only:
            continue
        # Every sample, as a Render has them, before the session says it is done.
        scene = dict(pickle.loads(pickled.read_bytes()), _flat_out=True)
        layers = [l for m in scene['materials'].values() for l in (m.get('layers') or [])]
        if not any(l.get('kind') == 'gradient' for l in layers):
            print('%-16s not captured: %s' % (name, [w for w in scene.get('warnings', []) if 'radient' in w][:1]))
            continue
        reference = modo(name)
        rows = {'Modo': [at(reference, x, y) for x, y in PLACES]}
        for engine in engines:
            try:
                if engine == 'moonray':
                    values = compare.moonray(scene, runtime, folder, 'gradient_' + name)
                else:
                    values = compare.moonlightipr(scene, session, 'gradient_' + name)[0]
                rows[engine] = [at(values, x, y) for x, y in PLACES]
            except Exception as exc:
                rows[engine] = None
                print('%-16s %s failed: %s' % (name, engine, str(exc)[-300:]))
        print('== %s' % name)
        for label, values in rows.items():
            if values:
                off = '' if label == 'Modo' else '  (largest off %.3f)' % max(abs(a - b) for a, b in zip(values, rows['Modo']))
                print('   %-12s %s%s' % (label, ' '.join('%7.3f' % v for v in values), off), flush=True)
finally:
    if session is not None and session.process.poll() is None:
        session.process.kill()
