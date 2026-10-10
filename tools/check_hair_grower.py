"""Check that the runtime's hair grower grows the hair moonray_modo/hair.py grows, and time the two.

Usage: check_hair_grower.py <runtime folder>
Hair is grown both ways on a dome and on a ball, around guides and between them, with guides on the surface, on its
corners where triangles tie for nearest, off it and with no scalp at all; every point of every strand must agree to
within a millionth of a millimetre. Then a head of thirty thousand strands is grown both ways and timed."""
import math
import random
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for name in ('modo', 'lx', 'lxifc', 'lxu'):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.path[:0] = [str(ROOT / 'tests'), str(ROOT / 'kit/MoonRayForModo/python')]
from moonray_modo import hair, hair_native  # noqa: E402
import test_hair  # noqa: E402


def ball(rings=48, around=96, radius=.5):
    """A ball as triangles, with a pole at the top where many triangles meet at one point."""
    def at(i, j):
        a, b = math.pi * i / rings, 2 * math.pi * j / around
        return (radius * math.sin(a) * math.cos(b), radius * math.cos(a), radius * math.sin(a) * math.sin(b))
    made = []
    for i in range(rings):
        for j in range(around):
            p, q, r, s = at(i, j), at(i + 1, j), at(i + 1, j + 1), at(i, j + 1)
            made += [(p, q, r), (p, r, s)]
    return made


def fur(count, radius=.5, length=.2, seed=5):
    chance = random.Random(seed)
    guides = []
    for _ in range(count):
        a, b = chance.uniform(.05, 3.0), chance.uniform(0, 2 * math.pi)
        n = (math.sin(a) * math.cos(b), math.cos(a), math.sin(a) * math.sin(b))
        guides.append([(n[0] * (radius + length * j / 6), n[1] * (radius + length * j / 6) - .06 * (j / 6) ** 2, n[2] * (radius + length * j / 6)) for j in range(7)])
    return guides


def main():
    runtime = Path(sys.argv[1]).resolve()
    if hair_native.program(runtime) is None:
        raise SystemExit('This runtime has no ' + hair_native.PROGRAM)
    failed = []
    dome, round_ball = test_hair.dome(), ball(16, 24)
    held = hair.Scalp(round_ball)
    cases = {
        'on a dome': (test_hair.guides(), dome),
        'on the corners of a ball': ([[tuple(t[0][k] * (1 + .1 * j) for k in range(3)) for j in range(4)] for t in held.triangles[::5]], round_ball),
        'off the scalp': ([[(5.0, 5.0 + .1 * j, 5.0) for j in range(4)]] + test_hair.guides()[:3], dome),
        'with no scalp': (test_hair.guides(), None),
        'with one guide': (test_hair.guides()[:1], dome),
    }
    back = [.5, 0, .1, 0, 0, 2, 0, 0, -.1, 0, 1, 0, .3, -.2, .7, 1]
    for name, (guides, triangles) in cases.items():
        for mode in (hair.CLUSTERS, hair.BETWEEN):
            for seed in (1, 77, 9000000000):
                slow, adrift = hair.grow(guides, hair.Scalp(triangles) if triangles is not None else None, mode, 12, .06, .4, .2, seed)
                slow = [[[p[0] * back[0] + p[1] * back[4] + p[2] * back[8] + back[12], p[0] * back[1] + p[1] * back[5] + p[2] * back[9] + back[13],
                          p[0] * back[2] + p[1] * back[6] + p[2] * back[10] + back[14]] for p in strand] for strand in slow]
                fast = hair_native.grow(guides, triangles, mode, 12, .06, .4, .2, seed, back, runtime)
                if fast is None:
                    failed.append('%s, mode %d: the program gave nothing' % (name, mode))
                    continue
                same = len(fast[0]) == len(slow) and all(len(a) == len(b) for a, b in zip(fast[0], slow)) and fast[1] == adrift
                worst = max((abs(x - y) for a, b in zip(fast[0], slow) for p, q in zip(a, b) for x, y in zip(p, q)), default=0.0) if same else float('inf')
                if not same or worst > 1e-9:
                    failed.append('%s, mode %d, seed %d: differs by %g (adrift %s and %s)' % (name, mode, seed, worst, fast[1], adrift))
        print('%-28s %s' % (name, 'FAILED' if any(f.startswith(name) for f in failed) else 'the same hair'), flush=True)
    guides, triangles = fur(300), ball()
    started = time.time()
    fast = hair_native.grow(guides, triangles, hair.CLUSTERS, 100, .0165, .3, .1, 1, None, runtime)
    quick = time.time() - started
    started = time.time()
    slow = hair.grow(guides, hair.Scalp(triangles), hair.CLUSTERS, 100, .0165, .3, .1, 1)
    print('%d strands on %d triangles: %.2f s by the program, %.2f s in Python' % (len(slow[0]), len(triangles), quick, time.time() - started))
    worst = max(abs(x - y) for a, b in zip(fast[0], slow[0]) for p, q in zip(a, b) for x, y in zip(p, q))
    if worst > 1e-9 or fast[1] != slow[1]:
        failed.append('the large head differs by %g' % worst)
    if failed:
        raise SystemExit('\n'.join(failed))
    print('Hair grower check passed')


if __name__ == '__main__':
    main()
