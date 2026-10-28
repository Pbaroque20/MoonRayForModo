"""A polygon's triangles as MoonRay makes them (geom/TriMesh.cc, TriMesh::splitNGons): a face of more than four corners
that is flat and has some area is ear-clipped, so that a concave one (an L, a C) is filled where it is and not across
its notch; any other face is a fan (0, 1, 2), (0, 2, 3) ... MoonLightIPR and the simplified meshes of MoonRay's realtime
were fanned throughout, a concave n-gon drawn over its own outline. The same tests as MoonRay's, in its order: its
unitNormal, calculateConcaveNGonArea, calculateConcaveNGonNormal, isPlanar and pointInTriangle."""
import math


def fan(size, _held={}):
    """A polygon of size corners as a fan of triangles, each corner as its place in the polygon: (0, 1, 2, 0, 2, 3, ...)."""
    held = _held.get(size)
    if held is None:
        held = _held[size] = tuple(v for i in range(1, size - 1) for v in (0, i, i + 1))
    return held


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _unit(a):
    length = math.sqrt(_dot(a, a))
    return (a[0] / length, a[1] / length, a[2] / length) if length else (0.0, 0.0, 0.0)


def _unit_normal(a, b, c):
    def det(r0, r1, r2):
        return _dot(r0, _cross(r1, r2))
    x = det((1, a[1], a[2]), (1, b[1], b[2]), (1, c[1], c[2]))
    y = det((a[0], 1, a[2]), (b[0], 1, b[2]), (c[0], 1, c[2]))
    z = det((a[0], a[1], 1), (b[0], b[1], 1), (c[0], c[1], 1))
    m = max(1e-6, math.sqrt(x * x + y * y + z * z))
    return (x / m, y / m, z / m)


def _area(points):
    n = len(points)
    total = (0.0, 0.0, 0.0)
    for i in range(n):
        c = _cross(points[i], points[(i + 1) % n])
        total = (total[0] + c[0], total[1] + c[1], total[2] + c[2])
    return _dot(total, _unit_normal(points[0], points[1], points[2])) / 2.0


def _normal(points, area):
    n = len(points)
    total = (0.0, 0.0, 0.0)
    for i in range(n):
        c = _cross(points[i], points[(i + 1) % n])
        total = (total[0] + c[0], total[1] + c[1], total[2] + c[2])
    if area < 0.0:
        total = (-total[0], -total[1], -total[2])
    return _unit(total)


def _planar(points):
    a, b, c = points[0], points[1], points[2]
    normal = _cross(_sub(a, b), _sub(c, b))
    return all(abs(_dot(_unit(_sub(a, p)), normal)) <= 1e-6 for p in points[3:])


def _inside(p, a, b, c):
    v0, v1, v2 = _sub(b, a), _sub(c, a), _sub(p, a)
    d00, d01, d11, d20, d21 = _dot(v0, v0), _dot(v0, v1), _dot(v1, v1), _dot(v2, v0), _dot(v2, v1)
    den = d00 * d11 - d01 * d01
    if not den:
        return False
    y = (d11 * d20 - d01 * d21) / den
    w = (d00 * d21 - d01 * d20) / den
    return 1.0 - y - w >= 0 and y >= 0 and w >= 0


def ear_clip(points):
    """A flat polygon of more than four corners (points, each three numbers) as triangles of its corners' places,
    flat, as MoonRay ear-clips it; None where MoonRay fans it instead (four corners or fewer, no area, not flat, or no
    ear to be found)."""
    n = len(points)
    if n <= 4:
        return None
    area = _area(points)
    if math.isnan(area) or area < 1e-6 or not _planar(points):
        return None
    normal = _normal(points, area)
    local = list(range(n))
    out = []
    while len(local) > 3:
        m = len(local)
        for i in range(m - 1, -1, -1):
            ia, ib, ic = local[i], local[(i - 1) % m], local[(i + 1) % m]
            va, vb, vc = points[ia], points[ib], points[ic]
            # A corner turned against the face is no ear; nor is one whose triangle holds another corner.
            if _dot(_cross(_sub(vc, va), _sub(vb, va)), normal) < 0.0:
                continue
            if any(_inside(points[l], vb, va, vc) for l in local if l not in (ia, ib, ic)):
                continue
            out.extend((ib, ia, ic))
            del local[i]
            break
        else:
            return None
    out.extend(local)
    return tuple(out)


def corners(face, vertices):
    """A face's triangles as its corners' places in it, flat (three a triangle): MoonRay's, an n-gon ear-clipped."""
    size = len(face)
    if size > 4:
        clipped = ear_clip([tuple(vertices[v]) for v in face])
        if clipped is not None:
            return clipped
    return fan(size)
