# python
"""Command line: Modo's Python's math.dist against Python copies of candidate forms of CPython's vector_norm, to find
the one curves.cpp must follow. Writes test-results/dist-parts.json."""
import json
import math
import random
result = {}
T27 = 134217729.0


def add(state, x):
    csum, frac = state
    old = csum
    csum += x
    frac += (old - csum) + x
    return csum, frac


def norm(diffs, split_terms, correct):
    top = max(diffs)
    if top == 0.0:
        return top
    e = math.frexp(top)[1]
    scale = math.ldexp(1.0, -e)
    state = (1.0, 0.0)
    for x in diffs:
        x *= scale
        if split_terms:
            t = x * T27
            hi = t - (t - x)
            lo = x - hi
            state = add(state, hi * hi)
            state = add(state, 2.0 * hi * lo)
            state = add(state, lo * lo)
        else:
            state = add(state, x * x)
    h = math.sqrt(state[0] - 1.0 + state[1])
    if not correct:
        return h / scale
    x = h
    t = x * T27
    hi = t - (t - x)
    lo = x - hi
    state = add(state, -hi * hi)
    state = add(state, -2.0 * hi * lo)
    state = add(state, -lo * lo)
    x = state[0] - 1.0 + state[1]
    return (h + x / (2.0 * h)) / scale


chance = random.Random(3)
pairs = [([chance.uniform(-1, 1) * 10 ** chance.randint(-6, 3) for _ in range(3)], [chance.uniform(-1, 1) for _ in range(3)]) for _ in range(50000)]
for split in (False, True):
    for correct in (False, True):
        result['split=%s correct=%s' % (split, correct)] = sum(math.dist(p, q) != norm([abs(a - b) for a, b in zip(p, q)], split, correct) for p, q in pairs)
def by_max(diffs):
    top = max(diffs)
    if top == 0.0:
        return top
    state = (1.0, 0.0)
    for x in diffs:
        x /= top
        state = add(state, x * x)
    return top * math.sqrt(state[0] - 1.0 + state[1])


result['by_max'] = sum(math.dist(p, q) != by_max([abs(a - b) for a, b in zip(p, q)]) for p, q in pairs)
json.dump(result, open(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\dist-parts.json', 'w'), indent=1)
