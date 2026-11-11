"""Modo's Variation Texture by Particle in MoonRay and MoonLightIPR: probe_cl_variation_particle.py's replicated cube (or
probe_gui_variation_particle.py's) as the kit captured it, rendered by each. The glow (a ramp from 0 to 1) is each
replica's number: the distinct glows each engine shows must be the numbers the kit gave the replicas, and the two
engines must agree pixel by pixel. check_variation_particle.py <runtime folder> [result folder]"""
import bisect
import json
import pathlib
import pickle
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'kit/MoonRayForModo/python')]
import compare_moonlightipr as compare
from moonray_modo import native

runtime = native.find_runtime(sys.argv[1])
folder = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / 'test-results/variation-particle'
W, H = 320, 96
compare.WIDTH, compare.HEIGHT = W, H
compare.fixture.WIDTH, compare.fixture.HEIGHT = W, H
compare.os.environ['MOONRAY_MODO_RUNTIME'] = str(runtime)
scene = dict(pickle.loads((folder / 'particle.pickle').read_bytes()), _flat_out=True)
given = [n for mesh in scene['meshes'] for n in mesh.get('instance_variation') or []]
# Through the probe's ramp (keyed 0 and 1, which Modo eases between): the glow each number should give.
curve = json.loads((folder / 'report.json').read_text())['curve']


def through(x):
    i = min(max(bisect.bisect_left([c[0] for c in curve], x), 1), len(curve) - 1)
    (x0, y0), (x1, y1) = curve[i - 1], curve[i]
    return y0 + (x - x0) * (y1 - y0) / ((x1 - x0) or 1)


numbers = [through(n) for n in given]
print('numbers given: %s' % ' '.join('%.3f' % n for n in sorted(given)))
print('glows due:     %s' % ' '.join('%.3f' % n for n in sorted(numbers)))
session = compare.fixture.Session(folder)
session.runtime = runtime
try:
    pictures = {'moonray': compare.moonray(scene, runtime, folder, 'particle'),
                'moonlightipr': compare.moonlightipr(scene, session, 'particle')[0]}
finally:
    if session.process.poll() is None:
        session.process.kill()
worst = 0.0
for label, picture in pictures.items():
    glows = [picture[i * 3] for i in range(W * H)]
    # A glow held over a run of pixels along a row (a replica's face), away from the background.
    held = {}
    for y in range(H):
        row = glows[y * W:(y + 1) * W]
        background = row[0]
        for x in range(2, W - 2):
            if abs(row[x] - background) > 0.02 and max(row[x - 2:x + 3]) - min(row[x - 2:x + 3]) < 1e-3:
                held[round(row[x], 3)] = held.get(round(row[x], 3), 0) + 1
    shown = sorted(g for g, count in held.items() if count >= 20)
    off = [min(abs(g - n) for n in numbers) for g in shown]
    worst = max([worst] + off)
    print('%-12s shows %s  (largest off a given number %.3f)' % (label, ' '.join('%.3f' % g for g in shown), max(off or [0])))
difference = max(abs(a - b) for a, b in zip(pictures['moonray'], pictures['moonlightipr']))
mean = sum(abs(a - b) for a, b in zip(pictures['moonray'], pictures['moonlightipr'])) / len(pictures['moonray'])
print('MoonRay against MoonLightIPR: mean %.4f, largest %.3f (edges)' % (mean, difference))
print('largest glow off its number: %.3f' % worst)
