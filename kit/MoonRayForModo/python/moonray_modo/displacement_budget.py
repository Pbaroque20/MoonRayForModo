"""How much geometry displacement is allowed to make, and how finely it is cut within that.

Modo cuts a displaced surface until its edges are its Displacement Rate in pixels (that times the Displacement Ratio
off screen), never shorter than its Minimum Edge Length. At Modo's defaults (1 pixel, 100 um) a 10 x 10 m ground seen
from eye height comes to about 11.5 million triangles at 1920 x 1080 (tools/probe_cl_displaced_plane.py): Modo's own
renderer holds that, but read through its render cache for MoonRay (Surfaces: Modo evaluated geometry, or a scene
read that way for its replicators, proxies or item masks) it took 22 GB in Modo and a 2.9 GB scene, and at a larger
picture more than XPU2 takes ("Geometry count budget") or the machine holds.

- modo_dicing: Modo's cut of the displaced surfaces of a reading, worked out from their undisplaced triangles and the
  camera (within about 10% of what Modo made for that ground: 12.8 M for 11.5 M, 1.4 M for 1.27 M at 3 pixels).
- MODO_DISPLACED_TRIANGLES: past it, Modo's cut is not read; MoonRay displaces the surfaces itself (host), as it does
  every mesh read as modeled.
- shared_resolution / adaptive_resolution: MoonRay (and XPU2, and MoonLightIPR within its own budget) cuts a displaced
  mesh by the screen at Modo's Displacement Rate, as Modo does, up to the resolution the displaced meshes' shared
  FALLBACK_TRIANGLES allows (never coarser than their level's). At the level's 8 alone the ground above, one polygon,
  came out flat; now about 4 M triangles at the most, 324 MB in MoonRay, 68 MB in XPU2.
- resolution: the mesh_resolution any mesh MoonRay tessellates is given: never finer than the Minimum Edge Length lets
  an edge be split (cut by the screen), nor than DISPLACED_TRIANGLES at the most it can make."""
import math

# Modo's displaced cut read from its render cache: at most this many triangles (estimated by modo_dicing).
MODO_DISPLACED_TRIANGLES = 4000000
# MoonRay's cut of the surfaces Modo's cut was refused for, all of them together, at the most it can make.
FALLBACK_TRIANGLES = 4000000
# Any one mesh MoonRay tessellates (displaced or subdivided): at most this many triangles at the most its resolution can
# make; XPU2 holds a displaced mesh of at most 16 M triangles.
DISPLACED_TRIANGLES = 16000000
# Triangles of a surface's cage looked at for the estimate; the rest counted as they are on average.
SAMPLED = 4096
# Modo's defaults: Displacement Rate (pixels), Displacement Ratio, Minimum Edge Length (metres).
RATE, RATIO, MIN_EDGE = 1.0, 4.0, 0.0001

# The verdicts given, by what they were given for (verdict).
_VERDICTS = {}
_TOKENS = __import__('itertools').count(1)


def next_token():
    """A number naming one sample (sample) in the verdicts' keys."""
    return next(_TOKENS)


def triangles(faces):
    """How many triangles a list of polygons makes (a polygon of n corners, n - 2)."""
    counts = getattr(faces, 'counts', None)
    if counts is not None:
        return len(faces.data) - 2 * len(faces)
    return sum(max(0, len(face) - 2) for face in faces)


class View:
    """The camera as the cut sees it: where it is, its axes, how many pixels a unit makes at unit distance."""

    def __init__(self, camera, width, height):
        m = camera.get('matrix') or [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
        self.eye = (m[12], m[13], m[14])
        self.right = _unit((m[0], m[1], m[2]))
        self.up = _unit((m[4], m[5], m[6]))
        self.forward = _unit((-m[8], -m[9], -m[10]))
        self.width, self.height = float(width), float(height)
        self.ortho = camera.get('projection', 'persp') == 'ortho'
        if self.ortho:
            self.pixel = max(1e-9, float(camera.get('ortho_width', 1.0))) / self.width
        else:
            self.focal = self.width * float(camera.get('focal_mm', 50.0)) / max(1e-9, float(camera.get('film_mm', 36.0)))

    def footprint(self, point):
        """(the length one pixel covers at point, whether point is in the picture, its distance from the eye)."""
        v = (point[0] - self.eye[0], point[1] - self.eye[1], point[2] - self.eye[2])
        distance = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
        depth = v[0] * self.forward[0] + v[1] * self.forward[1] + v[2] * self.forward[2]
        x = v[0] * self.right[0] + v[1] * self.right[1] + v[2] * self.right[2]
        y = v[0] * self.up[0] + v[1] * self.up[1] + v[2] * self.up[2]
        if self.ortho:
            seen = abs(x) <= self.width * self.pixel / 2 and abs(y) <= self.height * self.pixel / 2
            return self.pixel, seen, distance
        seen = depth > 1e-3 and abs(x / depth * self.focal) <= self.width / 2 and abs(y / depth * self.focal) <= self.height / 2
        # In the picture by its depth; off it (or behind the eye) by its distance.
        return (depth if seen else distance) / self.focal, seen, distance


def _unit(v):
    length = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return (v[0] / length, v[1] / length, v[2] / length) if length > 1e-20 else (0.0, 0.0, 0.0)


def _triangle(a, b, c, view, rate, ratio, min_edge, depth=0):
    """Modo's cut of one triangle: split while it is large beside its distance from the eye (its pixels change across
    it), then its area over the area of a triangle whose edges are the rate's pixels there (the ratio's off the
    picture), no shorter than min_edge."""
    centre = ((a[0] + b[0] + c[0]) / 3, (a[1] + b[1] + c[1]) / 3, (a[2] + b[2] + c[2]) / 3)
    pixel, seen, distance = view.footprint(centre)
    longest = max(math.dist(a, b), math.dist(b, c), math.dist(c, a))
    if not view.ortho and longest > 0.25 * distance and depth < 16:
        ab = tuple((a[i] + b[i]) / 2 for i in range(3))
        bc = tuple((b[i] + c[i]) / 2 for i in range(3))
        ca = tuple((c[i] + a[i]) / 2 for i in range(3))
        return sum(_triangle(*corners, view, rate, ratio, min_edge, depth + 1)
                   for corners in ((a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca)))
    u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    w = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    n = (u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0])
    area = 0.5 * math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2])
    edge = max(min_edge, rate * (1.0 if seen else ratio) * pixel, 1e-9)
    return max(1.0, 2.0 * area / (edge * edge))


def _place(point, matrix):
    if not matrix:
        return (point[0], point[1], point[2])
    return tuple(point[0] * matrix[c] + point[1] * matrix[4 + c] + point[2] * matrix[8 + c] + matrix[12 + c] for c in range(3))


def sampled(vertices, faces):
    """Up to SAMPLED of a mesh's polygons spread over it, fanned into triangles (in its own space), and how many
    polygons each stands for: (triangles, factor)."""
    count = len(faces)
    if not count:
        return [], 0.0
    step = max(1, count // SAMPLED)
    found, looked = [], 0
    for index in range(0, count, step):
        face = list(faces[index])
        if len(face) < 3:
            continue
        looked += 1
        corners = [(float(vertices[k][0]), float(vertices[k][1]), float(vertices[k][2])) for k in face]
        for k in range(1, len(corners) - 1):
            found.append((corners[0], corners[k], corners[k + 1]))
    return found, (float(count) / looked if looked else 0.0)


def diced(triangles, factor, matrix, view, rate=RATE, ratio=RATIO, min_edge=MIN_EDGE):
    """Modo's cut of sampled triangles (sampled) placed by matrix."""
    total = 0.0
    for a, b, c in triangles:
        total += _triangle(_place(a, matrix), _place(b, matrix), _place(c, matrix), view, rate, ratio, min_edge)
    return total * factor


def mesh_dicing(vertices, faces, matrix, view, rate=RATE, ratio=RATIO, min_edge=MIN_EDGE):
    """Modo's cut of one placed mesh (its polygons fanned into triangles), from up to SAMPLED of them spread over it."""
    triangles, factor = sampled(vertices, faces)
    return diced(triangles, factor, matrix, view, rate, ratio, min_edge)


# A prototype placed more times than this (a replicator's) is estimated from its placements nearest the camera alone.
NEAREST_PLACES = 8


def sample(data, surfaces=None):
    """What an estimate keeps of an undisplaced reading (evaluated.capture) for its displaced surfaces (surfaces: those
    of data['surfaces'] to count; all where None): for each prototype, its triangles sampled (sampled) and every place
    it stands. Modo's displaced reading holds a prototype once, however many surfaces place it (a replicator's copies,
    instances), so its cut is counted once: at the place where it is cut finest (modo_cut). A camera move is estimated
    from it again with nothing read."""
    prototypes = data.get('prototypes') or {}
    kept = {}
    for surface in (data.get('surfaces') or ()) if surfaces is None else surfaces:
        key = str(surface.get('source_id'))
        if key not in kept:
            prototype = prototypes.get(key) or {}
            parts = [sampled(segment['vertices'], segment['faces']) for segment in prototype.get('segments') or ()
                     if segment.get('faces') and segment.get('vertices')]
            points = [p for triangles, _ in parts for t in triangles for p in t]
            centre = tuple(sum(p[k] for p in points) / len(points) for k in range(3)) if points else (0.0, 0.0, 0.0)
            kept[key] = {'parts': parts, 'centre': centre, 'places': []}
        kept[key]['places'].append(tuple(surface.get('matrix') or ()) or None)
    return kept


def modo_cut(kept, view, rate=RATE, ratio=RATIO, min_edge=MIN_EDGE):
    """Modo's cut of what sample kept, seen by view: each prototype at the place it is cut finest (of its
    NEAREST_PLACES nearest the camera, where it stands at more)."""
    total = 0.0
    for held in kept.values():
        places = held['places']
        if len(places) > NEAREST_PLACES:
            eye = view.eye
            places = sorted(places, key=lambda m: sum((c - e) ** 2 for c, e in zip(_place(held['centre'], m), eye)))[:NEAREST_PLACES]
        total += max(sum(diced(triangles, factor, matrix, view, rate, ratio, min_edge) for triangles, factor in held['parts'])
                     for matrix in places) if places else 0.0
    return total


def modo_dicing(data, displaced_layers, camera, width, height, rate=RATE, ratio=RATIO, min_edge=MIN_EDGE):
    """Modo's cut of the surfaces of an undisplaced reading (evaluated.capture) that a Displacement layer applies to
    (displaced_layers: their item identities, matched against each surface's layers; every surface where None): about
    how many triangles Modo's displaced reading would hold."""
    surfaces = [surface for surface in data.get('surfaces') or ()
                if displaced_layers is None or set(surface.get('layers') or ()) & displaced_layers]
    return modo_cut(sample(data, surfaces), View(camera, width, height), rate, ratio, min_edge)


def verdict(key, estimate):
    """Modo's cut for key (what shapes it: the scene, its Displacement settings, the picture and camera) as estimate()
    gives it, worked out once; whether it is past MODO_DISPLACED_TRIANGLES is the caller's."""
    held = _VERDICTS.get(key)
    if held is None:
        held = _VERDICTS[key] = float(estimate())
        if len(_VERDICTS) > 256:
            _VERDICTS.pop(next(iter(_VERDICTS)))
    return held


def rate_for(estimate, rate):
    """The Displacement Rate at which Modo's cut comes within MODO_DISPLACED_TRIANGLES (its triangles go as the square
    of the rate), to a tenth of a pixel."""
    return math.ceil(rate * math.sqrt(estimate / MODO_DISPLACED_TRIANGLES) * 10.0) / 10.0


def fallback_resolution(total_triangles):
    """The resolution of the displaced surfaces MoonRay cuts by the screen, for all of their total_triangles together:
    as fine as FALLBACK_TRIANGLES allows at the most each could make (MoonRay cuts each to the rate's pixels within
    it, so most come to far fewer)."""
    return max(1, int(math.sqrt(FALLBACK_TRIANGLES / max(1.0, float(total_triangles)))))


def screen_cut(mesh, displaced, sea=lambda mesh: False):
    """Whether a mesh's displacement is cut by the screen with the shared budget (shared_resolution): displaced, not an
    instancer's reference (cut once for all its placements, evenly), with no resolution of its own, not a sea (whose
    budget is ocean.py's)."""
    return bool(mesh.get('faces')) and 'instances' not in mesh and 'mesh_resolution' not in mesh and displaced(mesh) \
        and not sea(mesh)


def shared_resolution(meshes, displaced, sea=lambda mesh: False):
    """The resolution every displaced mesh cut by the screen may reach (screen_cut), the budget shared by their
    triangles; None where there is none."""
    total = sum(triangles(mesh['faces']) for mesh in meshes if screen_cut(mesh, displaced, sea))
    return fallback_resolution(total) if total else None


def adaptive_resolution(mesh, level, shared, min_edge=0.0):
    """A displaced mesh's resolution when MoonRay cuts it by the screen at Modo's Displacement Rate, as Modo cuts it: as
    finely as the shared budget allows (never coarser than its level's), within Modo's Minimum Edge Length and
    DISPLACED_TRIANGLES (resolution)."""
    return resolution(max(level, shared or level), mesh, min_edge)


def resolution(held, mesh, min_edge=0.0, edge=None):
    """The mesh_resolution MoonRay is given for a mesh it tessellates (held: the one it would have): no finer than the
    Minimum Edge Length lets its edges (edge: its mean edge in the scene, worked out when not given) be split, nor
    than DISPLACED_TRIANGLES at the most it can make (its triangles times the resolution squared)."""
    result = held
    count = triangles(mesh['faces'])
    if count and count * result * result > DISPLACED_TRIANGLES:
        result = max(1, int(math.sqrt(DISPLACED_TRIANGLES / float(count))))
    if min_edge and min_edge > 0:
        if edge is None:
            edge = mean_edge(mesh)
        if edge is not None:
            result = min(result, max(1, int(math.ceil(edge / min_edge))))
    return result


def mean_edge(mesh):
    """The mesh's mean edge in the scene (its own mean edge by its largest scale), or None where it cannot be told."""
    from . import moonlightipr_detail
    try:
        _, _, edge = moonlightipr_detail.extent(mesh)
        return edge * moonlightipr_detail._scale(mesh.get('matrix') or [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])
    except (TypeError, ValueError, IndexError, KeyError, ZeroDivisionError):
        return None
