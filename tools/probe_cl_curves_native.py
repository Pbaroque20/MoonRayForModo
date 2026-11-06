# python
"""Command line: curves by the geometry adapter (curves.cpp) against the Python that worked them out, in Modo's own
Python: a batch's radii and UVs (extra_geometry.batches, whose lengths are Modo's math.dist), MoonLightIPR's packing of
the batch (moonlightipr_curves.payload) and the MoonRay scene text of it, the same numbers; and how long each took on
100,000 strands of 16 points. Writes test-results/curves-native.json."""
import json
import math
import pathlib
import random
import sys
import time
import traceback

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results')
result = {'python': sys.version}


def strands(seed, count, sizes):
    chance = random.Random(seed)
    made = []
    for s in range(count):
        n = chance.choice(sizes)
        x, y = chance.uniform(-1, 1), chance.uniform(-1, 1)
        made.append([[x + .01 * k * chance.uniform(.1, 3), y + chance.uniform(-.02, .02), .1 * k * chance.uniform(.5, 1.5)] for k in range(n)])
    return made


def timed(call):
    start = time.perf_counter()
    made = call()
    return made, round(time.perf_counter() - start, 3)


try:
    from moonray_modo import extra_geometry, moonlightipr_curves, rows, rdla
    result['adapter'] = rows._native() is not None and hasattr(rows._native(), 'MR_curve_shape')
    held_shape, held_built = extra_geometry._shaped_natively, moonlightipr_curves.built_natively
    for label, count, sizes in (('small', 300, (2, 3, 5, 8, 16)), ('heavy', 100000, (16,))):
        given = [(s, 'm%d' % (i % 2), None) for i, s in enumerate(strands(len(label), count, sizes))]
        shape = {'root': .004, 'tip': .0005, 'envelope': 1.7, 'uv': True, 'scales': [1 + (i % 7) * .03 for i in range(count)]}
        own = {}
        native, own['batches_native'] = timed(lambda: extra_geometry.batches('id', 'Hair', given, shape, '', [1.0] * 16))
        extra_geometry._shaped_natively = lambda *a: None
        try:
            python, own['batches_python'] = timed(lambda: extra_geometry.batches('id', 'Hair', given, shape, '', [1.0] * 16))
        finally:
            extra_geometry._shaped_natively = held_shape
        own['radii_same'] = all(list(a['radii']) == list(b['radii']) for a, b in zip(native, python))
        own['uvs_same'] = all([list(u) for u in a['uvs']] == [list(u) for u in b['uvs']] for a, b in zip(native, python))
        own['vertices_same'] = all(a['vertices'] == b['vertices'] and a['counts'] == b['counts'] for a, b in zip(native, python))
        if not own['radii_same']:
            a, b = native[0]['radii'], python[0]['radii']
            own['first_radius_difference'] = next(([i, repr(x), repr(y)] for i, (x, y) in enumerate(zip(a, b)) if x != y), None)
        entry = dict(native[0], round=True)
        for name in ('native', 'python'):
            if name == 'python':
                moonlightipr_curves.built_natively = lambda *a: None
            try:
                moonlightipr_curves.BUILT.clear(); moonlightipr_curves.SAME.clear()
                own['packed_' + name], own['packing_' + name] = timed(lambda: moonlightipr_curves.payload(entry, 1))
            finally:
                moonlightipr_curves.built_natively = held_built
        own['packed_same'] = own.pop('packed_native') == own.pop('packed_python')
        texts = []
        for made in (native, python):
            extra_geometry.WRITTEN.clear(); extra_geometry.SEEN.clear()
            lines = []
            extra_geometry.emit({'extra_geometry': made}, {'': {}, 'm0': {}, 'm1': {}}, lines)
            texts.append('\n'.join(lines))
        own['scene_text_same'] = texts[0] == texts[1]
        result[label] = own
except Exception:
    result['error'] = traceback.format_exc()
(root / 'curves-native.json').write_text(json.dumps(result, indent=1, default=str))
