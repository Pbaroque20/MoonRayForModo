"""Where an engine run's error lies: signed error maps and the error by region class.

class_errors.py <run_rhea output> <reference.rgba>

Writes err-recon.png, err-final.png and err-phase2.png (red: brighter than the reference, blue: darker, 10x) and prints,
for each region class, its pixels, phase 1's mean signed error there and its share of the final image's relative MSE."""
import json
import sys
from collections import defaultdict
from pathlib import Path

from images import read_rgba, write_png_rgb

# rhea_engine.cc's palette, in rhea::State order.
CLASSES = {(0.1, 0.1, 0.1): 'background', (0.2, 0.8, 0.3): 'trusted', (0.2, 0.5, 1.0): 'gap', (0.0, 0.8, 0.8): 'crease',
           (0.9, 0.2, 0.2): 'disconnected', (1.0, 1.0, 1.0): 'boundary', (0.8, 0.2, 0.9): 'occluded', (1.0, 0.5, 0.1): 'edge',
           (0.9, 0.8, 0.2): 'miss', (0.5, 0.5, 0.5): 'truncated'}


def main():
    d, ref = Path(sys.argv[1]), Path(sys.argv[2])
    rep = json.loads((d / 'report.json').read_text(encoding='utf-8'))
    w, h = rep['width'], rep['height']
    r = read_rgba(ref, w, h)
    for name in ('recon', 'final', 'phase2'):
        a = read_rgba(d / f'{name}.rgba', w, h)
        out = []
        for i in range(w * h):
            e = sum(a[i * 4 + c] - r[i * 4 + c] for c in range(3)) / 3 * 10
            out += [max(e, 0), 0, max(-e, 0)]
        write_png_rgb(d / f'err-{name}.png', out, w, h)
    cls = read_rgba(d / 'classes.rgba', w, h)
    a, f = read_rgba(d / 'recon.rgba', w, h), read_rgba(d / 'final.rgba', w, h)
    acc = defaultdict(lambda: [0.0, 0.0, 0])
    for i in range(w * h):
        s = acc[CLASSES.get(tuple(round(cls[i * 4 + c], 1) for c in range(3)), '?')]
        s[0] += sum(a[i * 4 + c] - r[i * 4 + c] for c in range(3)) / 3
        s[1] += sum((f[i * 4 + c] - r[i * 4 + c]) ** 2 / (r[i * 4 + c] ** 2 + 0.01) for c in range(3)) / 3
        s[2] += 1
    for k, (bias, rm, n) in sorted(acc.items(), key=lambda kv: -kv[1][1]):
        print(f'{k:11s} pixels {n:6d}  phase 1 mean signed error {bias / n:+.5f}  final relative MSE share {rm / (w * h):.2e}')


if __name__ == '__main__':
    main()
