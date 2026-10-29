"""A polygon's triangles as MoonRay makes them (geom/TriMesh.cc, TriMesh::splitNGons): a face of more than four corners
that is flat and has some area is ear-clipped, so that a concave one (an L, a C) is filled where it is and not across
its notch; any other face is a fan (0, 1, 2), (0, 2, 3) ... MoonLightIPR and the simplified meshes of MoonRay's realtime
were fanned throughout, a concave n-gon drawn over its own outline. The same tests as MoonRay's, in its order: its
unitNormal, calculateConcaveNGonArea, calculateConcaveNGonNormal, isPlanar and pointInTriangle.

With the MoonRay Source Override "N-gons triangulated cleanly" (native.ngon_ears, on by default) the tests are
cleaner ones, and MoonRay is handed the triangles they make (cut_mesh): MoonRay's own fans a face whose first three corners turn
against it (its area then comes out below zero) or whose area is under a millionth of a square unit, as a CAD
outline's often is, and fans it over itself. Changed, the area is the size of the corners' summed cross products,
whichever way they turn, set against the face's own size, and the face is flat within a ten-thousandth of it."""
import math

# Whether a pack follows the override (follow, set from native.ngon_ears as a scene is packed: read once, not per face).
_RULES = {'clean': True}


def follow(clean):
    """Set which rules faces are cut by until set again: the override's (clean) or MoonRay's own."""
    _RULES['clean'] = bool(clean)


def rules():
    """The rules in force, for what is kept of a mesh cut by them (moonlightipr_scene's packed meshes)."""
    return 'clean' if _RULES['clean'] else 'moonray'


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


def _clean_normal(points):
    """The face's normal by its corners' summed cross products, turned as its corners go round, where it has an area
    against its own size and is flat within a ten-thousandth of that size; else None (fanned)."""
    n = len(points)
    total = (0.0, 0.0, 0.0)
    for i in range(n):
        c = _cross(points[i], points[(i + 1) % n])
        total = (total[0] + c[0], total[1] + c[1], total[2] + c[2])
    length = math.sqrt(_dot(total, total))
    lo = [min(p[k] for p in points) for k in range(3)]
    hi = [max(p[k] for p in points) for k in range(3)]
    extent = math.sqrt(sum((b - a) ** 2 for a, b in zip(lo, hi)))
    if not (math.isfinite(length) and extent > 0 and length / 2 > 1e-10 * extent * extent):
        return None
    normal = (total[0] / length, total[1] / length, total[2] / length)
    if any(abs(_dot(_sub(p, points[0]), normal)) > 1e-4 * extent for p in points[1:]):
        return None
    return normal


def ear_clip(points, clean=None):
    """A flat polygon of more than four corners (points, each three numbers) as triangles of its corners' places,
    flat, as MoonRay ear-clips it; None where MoonRay fans it instead (four corners or fewer, no area, not flat, or no
    ear to be found). clean: by the override's tests (module notes), as set by follow where None."""
    n = len(points)
    if n <= 4:
        return None
    clean = _RULES['clean'] if clean is None else clean
    if clean:
        normal = _clean_normal(points)
        if normal is None:
            return None
        # A corner at the place of one of the ear's own is not in it: an outline with a hole joined by a seam passes
        # each end of the seam twice, and MoonRay's own test, by the corner's number alone, found no ear past them.
        lo = [min(p[k] for p in points) for k in range(3)]
        hi = [max(p[k] for p in points) for k in range(3)]
        near = (1e-7 * math.sqrt(sum((b - a) ** 2 for a, b in zip(lo, hi)))) ** 2
    else:
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
            if any(_inside(points[l], vb, va, vc) for l in local if l not in (ia, ib, ic)
                   and not (clean and min(_dot(d, d) for d in (_sub(points[l], va), _sub(points[l], vb), _sub(points[l], vc))) <= near)):
                continue
            out.extend((ib, ia, ic))
            del local[i]
            break
        else:
            return None
    out.extend(local)
    return tuple(out)


def cut_mesh(mesh):
    """A polygon mesh of the snapshot with its faces of more than four corners cut into the triangles corners gives
    (by the rules in force), each corner's normal, UVs and maps carried to its place in them and each face's material
    to its triangles; the mesh itself where it has no such face. MoonRay is handed these, so that both
    engines draw one set of triangles: MoonRay's own cut, even taught MoonLightIPR's rules, left a triangle wrong on a
    tester's CAD profile."""
    from .rows import counts as face_counts
    faces = mesh['faces']
    sizes = face_counts(faces)
    sizes = list(sizes) if sizes is not None else [len(face) for face in faces]
    if not sizes or max(sizes) <= 4:
        return mesh
    vertices = mesh['vertices']
    faces = [list(face) for face in faces]
    # Where each new face's corners come from among the old corners, and which old face each is of.
    kept_faces, from_corner, from_face = [], [], []
    start = 0
    for index, face in enumerate(faces):
        size = len(face)
        cut = corners(face, vertices) if size > 4 else None
        if cut is None:
            kept_faces.append(face)
            from_corner.extend(range(start, start + size))
            from_face.append(index)
        else:
            for k in range(0, len(cut), 3):
                kept_faces.append([face[t] for t in cut[k:k + 3]])
                from_corner.extend(start + t for t in cut[k:k + 3])
                from_face.append(index)
        start += size
    total = start
    out = dict(mesh, faces=kept_faces)

    def by_corner(values):
        return [values[i] for i in from_corner] if values is not None and len(values) == total else values

    def by_face(values):
        return [values[i] for i in from_face] if values is not None and len(values) == len(faces) else values
    for key in ('normals', 'uvs'):
        if mesh.get(key):
            out[key] = by_corner(list(mesh[key]))
    if mesh.get('uv_sets'):
        out['uv_sets'] = {name: by_corner(list(values)) for name, values in mesh['uv_sets'].items()}
    if mesh.get('corner_attributes'):
        out['corner_attributes'] = {name: dict(held, values=by_corner(list(held['values']))) for name, held in mesh['corner_attributes'].items()}
    if mesh.get('face_materials') is not None:
        out['face_materials'] = by_face(list(mesh['face_materials']))
    return out


def corners(face, vertices):
    """A face's triangles as its corners' places in it, flat (three a triangle): MoonRay's, an n-gon ear-clipped."""
    size = len(face)
    if size > 4:
        clipped = ear_clip([tuple(vertices[v]) for v in face])
        if clipped is not None:
            return clipped
    return fan(size)
