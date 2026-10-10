"""Hair grown from guide curves.

A few curves drawn on a mesh stand for a head of hair: each is a guide, and many strands are grown
from it when the scene is rendered. There are two ways to grow them. Around each guide, the strands
follow that guide alone and gather toward it along their length, which gives locks. Between guides,
each strand takes its shape from the guides nearest its root, which fills the space between them as
fur does.

Every strand's root is put on the scalp, the mesh the artist names, by the nearest point on its
surface, so that no strand floats above it or starts inside it. A root that can find no surface
within reach stays on its guide's root instead and is counted. What is random about a strand comes
from its guide's place in the mesh and the seed alone, so the same hair grows on every frame and
follows its guide when the guide or the scalp moves.
"""
import math
import random

CLUSTERS, BETWEEN = 0, 1
# How far a root may be moved to reach the scalp, as a multiple of the cluster's width.
REACH = 4.0


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def scaled(a, k):
    return (a[0] * k, a[1] * k, a[2] * k)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def unit(a, fallback=(0.0, 1.0, 0.0)):
    length = math.sqrt(dot(a, a))
    return scaled(a, 1.0 / length) if length > 1e-12 else fallback


def on_triangle(p, a, b, c):
    """The point of a triangle nearest p (Ericson, Real-Time Collision Detection). Written out number by number: it is
    run for every strand of hair against every triangle near it."""
    ax, ay, az = a
    px, py, pz = p
    abx, aby, abz = b[0] - ax, b[1] - ay, b[2] - az
    acx, acy, acz = c[0] - ax, c[1] - ay, c[2] - az
    apx, apy, apz = px - ax, py - ay, pz - az
    d1, d2 = abx * apx + aby * apy + abz * apz, acx * apx + acy * apy + acz * apz
    if d1 <= 0 and d2 <= 0:
        return a
    bpx, bpy, bpz = px - b[0], py - b[1], pz - b[2]
    d3, d4 = abx * bpx + aby * bpy + abz * bpz, acx * bpx + acy * bpy + acz * bpz
    if d3 >= 0 and d4 <= d3:
        return b
    vc = d1 * d4 - d3 * d2
    if vc <= 0 and d1 >= 0 and d3 <= 0:
        k = d1 / (d1 - d3)
        return (ax + abx * k, ay + aby * k, az + abz * k)
    cpx, cpy, cpz = px - c[0], py - c[1], pz - c[2]
    d5, d6 = abx * cpx + aby * cpy + abz * cpz, acx * cpx + acy * cpy + acz * cpz
    if d6 >= 0 and d5 <= d6:
        return c
    vb = d5 * d2 - d1 * d6
    if vb <= 0 and d2 >= 0 and d6 <= 0:
        k = d2 / (d2 - d6)
        return (ax + acx * k, ay + acy * k, az + acz * k)
    va = d3 * d6 - d5 * d4
    if va <= 0 and (d4 - d3) >= 0 and (d5 - d6) >= 0:
        k = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        return (b[0] + (c[0] - b[0]) * k, b[1] + (c[1] - b[1]) * k, b[2] + (c[2] - b[2]) * k)
    denominator = 1.0 / (va + vb + vc)
    v, w = vb * denominator, vc * denominator
    return (ax + (abx * v + acx * w), ay + (aby * v + acy * w), az + (abz * v + acz * w))


class Scalp:
    """A mesh's triangles, kept in a grid of cells so that the nearest point on the surface is found
    by looking at the few triangles around a point rather than at all of them."""

    def __init__(self, triangles):
        self.triangles = [tuple(tuple(float(v) for v in corner) for corner in triangle) for triangle in triangles]
        # A triangle with no area has no nearest point worth the name, and no normal.
        self.triangles = [(a, b, c) for a, b, c in self.triangles if dot(cross(sub(b, a), sub(c, a)), cross(sub(b, a), sub(c, a))) > 1e-24]
        self.cells = {}
        # Each triangle's middle and how far its corners are from it: a quick way to pass over the far ones.
        self.middles = [tuple((a[k] + b[k] + c[k]) / 3.0 for k in range(3)) for a, b, c in self.triangles]
        self.reaches = [max(math.sqrt(dot(sub(corner, middle), sub(corner, middle))) for corner in triangle)
                        for triangle, middle in zip(self.triangles, self.middles)]
        self.widest = max(self.reaches) if self.reaches else 0.0
        if not self.triangles:
            self.size = 1.0
            return
        low = [min(corner[k] for triangle in self.triangles for corner in triangle) for k in range(3)]
        high = [max(corner[k] for triangle in self.triangles for corner in triangle) for k in range(3)]
        extent = max(high[k] - low[k] for k in range(3)) or 1.0
        # About two triangles to a cell across the mesh.
        self.size = max(extent / max(2.0, (len(self.triangles) / 2.0) ** (1 / 3.0) * 2), 1e-9)
        for index, triangle in enumerate(self.triangles):
            lower = [int(math.floor(min(corner[k] for corner in triangle) / self.size)) for k in range(3)]
            upper = [int(math.floor(max(corner[k] for corner in triangle) / self.size)) for k in range(3)]
            for x in range(lower[0], upper[0] + 1):
                for y in range(lower[1], upper[1] + 1):
                    for z in range(lower[2], upper[2] + 1):
                        self.cells.setdefault((x, y, z), []).append(index)

    def around(self, point, reach):
        """The triangles that may come within reach of a point: those in the cells that far around it."""
        if not self.triangles:
            return [], [], point
        low = [int(math.floor((point[k] - reach) / self.size)) for k in range(3)]
        high = [int(math.floor((point[k] + reach) / self.size)) for k in range(3)]
        found = set()
        for x in range(low[0], high[0] + 1):
            for y in range(low[1], high[1] + 1):
                for z in range(low[2], high[2] + 1):
                    found.update(self.cells.get((x, y, z), ()))
        # Nearest first, with how far each is, so that a search from close by can stop early.
        distances = {index: math.sqrt(dot(sub(self.middles[index], point), sub(self.middles[index], point))) for index in found}
        ordered = sorted(found, key=distances.__getitem__)
        return ordered, [distances[index] for index in ordered], point

    def nearest_among(self, point, patch, reach):
        """As nearest, looking only at a patch from around: the many strands of one guide share it."""
        candidates, distances, origin = patch
        best, found = reach, None
        px, py, pz = point
        moved = math.sqrt((px - origin[0]) ** 2 + (py - origin[1]) ** 2 + (pz - origin[2]) ** 2)
        middles, reaches, triangles, widest, root = self.middles, self.reaches, self.triangles, self.widest, math.sqrt
        near = []
        for place, (index, far) in enumerate(zip(candidates, distances)):
            # The patch is in order of distance from its own middle; past this, none can be nearer.
            if far - moved - widest > best:
                break
            mx, my, mz = middles[index]
            # Nothing of this triangle can be nearer than its middle less its size.
            gap = root((px - mx) * (px - mx) + (py - my) * (py - my) + (pz - mz) * (pz - mz)) - reaches[index]
            if gap <= best:
                near.append((gap, place, index))
        # The likeliest first: once one is found close by, most of the others cannot be nearer and are not worked out.
        # Of triangles equally near, the one furthest along the patch is kept, as it was when they were taken in order.
        near.sort()
        last = -1
        for gap, place, index in near:
            if gap > best:
                break
            a, b, c = triangles[index]
            q = on_triangle(point, a, b, c)
            distance = root((px - q[0]) ** 2 + (py - q[1]) ** 2 + (pz - q[2]) ** 2)
            if distance < best or (distance == best and place > last):
                best, found, last = distance, (q, index), place
        if found is None:
            return None
        a, b, c = self.triangles[found[1]]
        return found[0], unit(cross(sub(b, a), sub(c, a)))

    def nearest(self, point, reach):
        """(point on the surface, its normal), or None if the surface is further off than reach."""
        if not self.triangles:
            return None
        centre = [int(math.floor(point[k] / self.size)) for k in range(3)]
        rings = max(1, int(math.ceil(reach / self.size)))
        best, found, seen = reach * reach, None, set()
        for ring in range(rings + 1):
            # Once a triangle is found, one more ring settles it: nothing beyond can be nearer.
            if found is not None and (ring - 1) * self.size > math.sqrt(best):
                break
            for x in range(centre[0] - ring, centre[0] + ring + 1):
                for y in range(centre[1] - ring, centre[1] + ring + 1):
                    for z in range(centre[2] - ring, centre[2] + ring + 1):
                        if max(abs(x - centre[0]), abs(y - centre[1]), abs(z - centre[2])) != ring:
                            continue
                        for index in self.cells.get((x, y, z), ()):
                            if index in seen:
                                continue
                            seen.add(index)
                            a, b, c = self.triangles[index]
                            q = on_triangle(point, a, b, c)
                            offset = sub(point, q)
                            distance = dot(offset, offset)
                            if distance <= best:
                                best, found = distance, (q, index)
        if found is None:
            return None
        a, b, c = self.triangles[found[1]]
        return found[0], unit(cross(sub(b, a), sub(c, a)))


def resampled(strand, count):
    """A strand as count points evenly along its length."""
    if len(strand) == count:
        return [tuple(p) for p in strand]
    lengths = [0.0]
    for a, b in zip(strand, strand[1:]):
        lengths.append(lengths[-1] + math.sqrt(dot(sub(b, a), sub(b, a))))
    total = lengths[-1]
    result, segment = [], 0
    for i in range(count):
        target = total * i / (count - 1)
        while segment < len(strand) - 2 and lengths[segment + 1] < target:
            segment += 1
        span = lengths[segment + 1] - lengths[segment]
        t = (target - lengths[segment]) / span if span > 1e-12 else 0.0
        result.append(add(strand[segment], scaled(sub(strand[segment + 1], strand[segment]), t)))
    return result


def neighbours(roots, count=2):
    """For each guide, the guides whose roots are nearest its own, found through a grid."""
    if len(roots) <= 1:
        return [[] for _ in roots]
    low = [min(r[k] for r in roots) for k in range(3)]
    high = [max(r[k] for r in roots) for k in range(3)]
    size = max(max(high[k] - low[k] for k in range(3)) / max(1.0, len(roots) ** (1 / 3.0)), 1e-9)
    cells = {}
    for index, root in enumerate(roots):
        cells.setdefault(tuple(int(math.floor(root[k] / size)) for k in range(3)), []).append(index)
    result = []
    for index, root in enumerate(roots):
        centre = tuple(int(math.floor(root[k] / size)) for k in range(3))
        found, ring = [], 0
        while len(found) < count and ring < 64:
            ring += 1
            found = [(dot(sub(roots[other], root), sub(roots[other], root)), other)
                     for x in range(centre[0] - ring, centre[0] + ring + 1) for y in range(centre[1] - ring, centre[1] + ring + 1)
                     for z in range(centre[2] - ring, centre[2] + ring + 1) for other in cells.get((x, y, z), ()) if other != index]
        result.append([other for _, other in sorted(found)[:count]])
    return result


def grow(guides, scalp, mode=CLUSTERS, count=20, width=.01, clump=.5, length_variation=.1, seed=1):
    """The strands that grow from a set of guides: (strands, how many guides start too far from the scalp to be put on it).

    guides are lists of points, root first, in the scalp's own space; width is the radius of a
    cluster at its root; clump is how far the strands of a cluster have closed on their guide by
    its tip, from 0 (they stay as far apart as at the root) to 1 (they meet it).
    """
    guides = [[tuple(float(v) for v in p) for p in guide] for guide in guides if len(guide) >= 2]
    count = max(1, int(count))
    clump = min(1.0, max(0.0, float(clump)))
    length_variation = min(.95, max(0.0, float(length_variation)))
    roots = [guide[0] for guide in guides]
    near = neighbours(roots) if mode == BETWEEN else None
    strands, adrift = [], 0
    for index, guide in enumerate(guides):
        chance = random.Random(int(seed) * 1000003 + index)
        root = guide[0]
        # The scalp around this guide, looked up once for all the strands that grow from it.
        span = width * (REACH + 1)
        if near and near[index]:
            span += max(math.sqrt(dot(sub(roots[other], root), sub(roots[other], root))) for other in near[index])
        patch = scalp.around(root, span) if scalp is not None else None
        placed = scalp.nearest_among(root, patch, width * REACH) if scalp is not None else None
        # A guide is adrift where its own root is off the scalp. A strand of a guide that is on it can still miss, at
        # the scalp's edge, and keeps its guide's root; that is not counted, there being nothing to put right.
        if scalp is not None and placed is None:
            adrift += 1
        normal = placed[1] if placed else unit(sub(guide[1], guide[0]))
        # How far the guide's own root is from the scalp. A strand that starts some way from the root has the scalp
        # no further off than that way and this together, so it need not look as far as it otherwise might.
        off = math.sqrt(dot(sub(placed[0], root), sub(placed[0], root))) if placed else None
        helper = (1.0, 0.0, 0.0) if abs(normal[0]) < .9 else (0.0, 1.0, 0.0)
        across = unit(cross(normal, helper))
        along = cross(normal, across)
        steps = len(guide) - 1
        others = [guides[other] for other in near[index]] if near else []
        # What is the same for every strand of this guide: its shape from its root, and its neighbours' shapes.
        own = [sub(p, root) for p in guide]
        shapes = [guide] + [resampled(other, len(guide)) for other in others]
        for _ in range(count):
            angle, distance = chance.uniform(0, 2 * math.pi), width * math.sqrt(chance.random())
            shorter = 1.0 - length_variation * chance.random()
            if others:
                # Somewhere in the patch of scalp between this guide and its neighbours, shaped by all of them.
                weights = [chance.random() for _ in range(len(others) + 1)]
                # The guide itself counts for most, so that its own shape is not lost among its neighbours'.
                weights[0] += 1.0
                total = sum(weights)
                weights = [w / total for w in weights]
                start = (0.0, 0.0, 0.0)
                for weight, shape in zip(weights, shapes):
                    start = add(start, scaled(shape[0], weight))
                body = []
                for j in range(len(guide)):
                    reach = (0.0, 0.0, 0.0)
                    for weight, shape in zip(weights, shapes):
                        reach = add(reach, scaled(sub(shape[j], shape[0]), weight))
                    body.append(reach)
                offset = scaled(add(scaled(across, math.cos(angle)), scaled(along, math.sin(angle))), distance * .25)
                start = add(start, offset)
                spread = (0.0, 0.0, 0.0)
                near_by = None
            else:
                spread = scaled(add(scaled(across, math.cos(angle)), scaled(along, math.sin(angle))), distance)
                start = add(root, spread)
                body = own
                near_by = None if off is None else min(width * REACH, (distance + off) * 1.0001 + 1e-9)
            landed = scalp.nearest_among(start, patch, near_by or width * REACH) if scalp is not None else None
            if landed is None:
                # No surface within reach: the strand keeps its guide's root rather than hang in the air.
                base, spread = root, (0.0, 0.0, 0.0)
                body = own
            else:
                base = landed[0]
            # In a cluster the strand starts apart from its guide and closes on it toward the tip.
            bx, by, bz = base
            sx, sy, sz = spread
            pull = 0.0 if others else -clump / steps
            strands.append([[bx + (reach[0] * shorter + sx * (pull * j)), by + (reach[1] * shorter + sy * (pull * j)), bz + (reach[2] * shorter + sz * (pull * j))]
                            for j, reach in enumerate(body)])
    return strands, adrift
