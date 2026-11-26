"""The density inside a Modo Sprite's puff, worked out from Modo's own renders (tools/probe_cl_blob_field.py, experiments
sprites and sprites2: one puff each, Radius 1, Density 1, Falloff 0, 0.1, 0.25, 0.5, 0.75 and 0.9, seen square on by an
orthographic camera, 100 pixels a metre).

Each puff's alpha a at a distance b from its centre is a line of fog through it: -ln(1 - a) is its depth (tau), the
density summed along the line. A Sprite's depth was found to grow with its Radius and its Density and not with its
Slices; its shape changes with Falloff. Taking the puff as a ball whose density depends only on the distance from its
centre, the density in shells from the outside in is what leaves each line's depth (onion peeling): the table printed,
for particles.SPRITE_TABLES, is that density (per metre, at Density 1) at 0, 1/(N-1) ... 1 of the radius, per falloff.

fit_sprite_profile.py <folder with sprites.Final Color Output.0001.exr and sprites2...> [samples, default 33]"""
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from measure_blob_field import alpha, SCALE, CX, CY  # noqa: E402

# (experiment, slot) of each falloff, every puff Radius 1, Density 1.
SLOTS = {0.0: ('sprites', 0), 0.1: ('sprites2', 0), 0.25: ('sprites2', 1), 0.5: ('sprites', 1), 0.75: ('sprites2', 2), 0.9: ('sprites2', 3)}
X = (-6, -3, 0, 3, 6)


def depths(a, slot):
    """tau at b = 0, 0.01 ... 1.0: the four directions from the centre averaged."""
    cx, found = CX + X[slot] * SCALE, []
    for step in range(101):
        values = [a[CY][int(cx + step)], a[CY][int(cx - step)], a[CY + step][int(cx)], a[CY - step][int(cx)]]
        mean = sum(values) / 4.0
        found.append(-math.log(max(1e-6, 1.0 - min(mean, 0.999999))))
    return found


def peeled(tau, shells):
    """The density in each of shells rings of a unit ball whose lines through it have depths tau (at b = i / 100)."""
    def depth(b):
        k = b * 100.0
        i = min(int(k), 99)
        t = k - i
        return tau[i] * (1 - t) + tau[i + 1] * t
    edges = [i / shells for i in range(shells + 1)]
    sigma = [0.0] * shells
    for j in reversed(range(shells)):
        b = edges[j]
        # The chord at b through shell m (m >= j): 2 (sqrt(r_{m+1}^2 - b^2) - sqrt(r_m^2 - b^2)).
        known = sum(sigma[m] * 2 * (math.sqrt(edges[m + 1] ** 2 - b * b) - math.sqrt(max(0.0, edges[m] ** 2 - b * b))) for m in range(j + 1, shells))
        own = 2 * (math.sqrt(edges[j + 1] ** 2 - b * b) - math.sqrt(max(0.0, edges[j] ** 2 - b * b)))
        sigma[j] = max(0.0, (depth(b) - known) / own) if own > 0 else 0.0
    return sigma


def table(sigma, samples):
    """The shells' densities at samples points from the centre to the edge (each shell's value at its middle)."""
    shells = len(sigma)
    mids = [(i + 0.5) / shells for i in range(shells)]
    out = []
    for k in range(samples):
        r = k / (samples - 1)
        if r <= mids[0]:
            out.append(sigma[0])
        elif r >= mids[-1]:
            # Out to nothing at the edge.
            out.append(sigma[-1] * max(0.0, (1.0 - r) / (1.0 - mids[-1])))
        else:
            i = max(m for m in range(shells) if mids[m] <= r)
            t = (r - mids[i]) / (mids[i + 1] - mids[i])
            out.append(sigma[i] * (1 - t) + sigma[i + 1] * t)
    return out


def main():
    folder = Path(sys.argv[1])
    samples = int(sys.argv[2]) if len(sys.argv) > 2 else 33
    pictures = {}
    tables = {}
    for falloff, (name, slot) in sorted(SLOTS.items()):
        if name not in pictures:
            pictures[name] = alpha(folder / (name + '.Final Color Output.0001.exr'))[0]
        tau = depths(pictures[name], slot)
        sigma = peeled(tau, 50)
        tables[falloff] = [round(v, 4) for v in table(sigma, samples)]
    print(json.dumps({str(k): v for k, v in tables.items()}))


if __name__ == '__main__':
    main()
