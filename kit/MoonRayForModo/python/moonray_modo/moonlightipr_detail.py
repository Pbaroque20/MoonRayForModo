"""How finely MoonLightIPR, and MoonRay's realtime previews, cut subdivided, displaced and dense meshes: by how
large they are on screen.

A subdivision surface was subdivided to Modo's own level wherever it stood, and a displaced mesh split until it held
400,000 triangles, a speck in the distance as finely as what fills the frame. Here each mesh is cut so that its
edges come to about a pixel of the preview (FINE_PIXELS), or two (COARSE_PIXELS) while the scene is being edited,
and never finer than Modo's level or the displacement budget: as far as it shows, the same surface, with a small
part of the triangles for what is small on screen. How large a mesh is on screen is taken at the nearest of its
placements, by its distance and not by whether the camera sees it, so that what is reflected or casts a shadow
keeps its detail. A mesh keeps its level until the level it wants is half a level off, so that a small move of the
camera does not cut it anew. And where the scene would still hold more than a budget of triangles, every mesh is cut
a little coarser alike."""
import math

COARSE_PIXELS, FINE_PIXELS = 2.0, 1.0
# The triangles the subdivided and displaced meshes may come to, while editing and at rest.
BUDGET = {'coarse': 3000000, 'fine': 8000000}
MAX_SPLITS = 8
# A polygon mesh of at least this many triangles, finer on screen than the target, is simplified (simplify.py), in steps
# of a quarter of its triangles, never below MIN_TRIANGLES.
SIMPLIFY_FROM, MIN_TRIANGLES = 20000, 256
# Each mesh's level as last chosen, by its identity and the detail it was chosen for (the hysteresis).
_HELD = {}
# A mesh's extent and edge length, by the content of its lists.
_EXTENT = {}


def _flat(values, axis):
    """One axis of a list of points, as fast as its kind allows."""
    data = getattr(values, 'data', None)
    if data is not None and getattr(values, 'width', 0) == 3:
        return data[axis::3]
    return [v[axis] for v in values]


def extent(mesh):
    """The mesh's middle and radius in its own space, and the mean length of its faces' edges: (centre, radius,
    edge). Kept by the content of its points and faces."""
    from .scene_digest import content
    vertices, faces = mesh['vertices'], mesh['faces']
    key = (content(vertices), content(faces))
    held = _EXTENT.get(key)
    if held is not None:
        return held
    lows, highs = [], []
    for axis in range(3):
        values = _flat(vertices, axis)
        lows.append(min(values))
        highs.append(max(values))
    centre = [(a + b) / 2 for a, b in zip(lows, highs)]
    radius = math.sqrt(sum((b - a) ** 2 for a, b in zip(lows, highs))) / 2
    # The mean edge, from up to 256 faces spread over the mesh (more took seconds over a car's 334 meshes, for the same
    # level to within a fraction of a halving).
    total, count = 0.0, 0
    step = max(1, len(faces) // 256)
    for index in range(0, len(faces), step):
        face = faces[index]
        for a, b in zip(face, list(face[1:]) + [face[0]]):
            p, q = vertices[a], vertices[b]
            total += math.sqrt((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2)
            count += 1
    held = _EXTENT[key] = (centre, radius, total / count if count else radius)
    if len(_EXTENT) > 4096:
        _EXTENT.clear()
    return held


def _scale(matrix):
    """The largest scale of a 4x4 row-vector matrix's three axes."""
    return max(math.sqrt(matrix[4 * r] ** 2 + matrix[4 * r + 1] ** 2 + matrix[4 * r + 2] ** 2) for r in range(3))


def _place(point, matrix):
    return [sum(point[k] * matrix[4 * k + c] for k in range(3)) + matrix[12 + c] for c in range(3)]


def pixels_per_unit(camera, width, centre, radius):
    """How many of the preview's pixels a unit of the scene covers at the nearest point of a sphere: perspective by its
    distance from the camera, orthographic the same everywhere."""
    if camera.get('projection', 'persp') == 'ortho':
        return width / max(1e-9, float(camera.get('ortho_width', 1.0)))
    eye = (camera.get('matrix') or [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])[12:15]
    distance = math.sqrt(sum((c - e) ** 2 for c, e in zip(centre, eye))) - radius
    # Inside the sphere, or touching it: as near as a hundredth of its size.
    distance = max(distance, radius * 0.01, 1e-6)
    return width * float(camera.get('focal_mm', 50.0)) / (max(1e-9, float(camera.get('film_mm', 36.0))) * distance)


def edge_pixels(mesh, camera, width, across=False):
    """The mesh's mean edge in the preview's pixels at the nearest of its placements; with across, also its size
    across in pixels there."""
    centre, radius, edge = extent(mesh)
    placements = mesh['instances'] if 'instances' in mesh else [mesh.get('matrix') or [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]]
    most, size = 0.0, 0.0
    for matrix in placements:
        scale = _scale(matrix)
        unit = scale * pixels_per_unit(camera, width, _place(centre, matrix), radius * scale)
        if edge * unit > most:
            most, size = edge * unit, 2 * radius * unit
    return (most, size) if across else most


def level(want, held):
    """The level to cut at, for the continuous level wanted, keeping the one held while it is at most half a level too
    coarse and a level and a half too fine."""
    needed = max(0, math.ceil(want - 1e-9))
    if held is not None and want - 0.5 <= held <= want + 1.5:
        return held
    return needed


def plan(meshes, camera, width, detail='fine', displaces=lambda mesh: False):
    """Each mesh's cut, by its id(): {'subdivision': level (a subdivision surface, at most Modo's), 'splits': at most
    this many splittings for its displacement}; and whether the coarse cut leaves any mesh coarser than the fine one
    would (a refinement at rest would change the picture). displaces(mesh) says whether its materials displace it."""
    pixels = COARSE_PIXELS if detail == 'coarse' else FINE_PIXELS
    entries = []
    for mesh in meshes:
        try:
            if not mesh.get('faces') or not mesh.get('vertices'):
                continue
            # log2 of the mesh's edge over the target: how many halvings its edges need.
            size, across = edge_pixels(mesh, camera, width, True)
            faces = mesh['faces']
            counts = getattr(faces, 'counts', None)
            triangles = (len(faces.data) - 2 * len(faces)) if counts is not None else sum(len(f) - 2 for f in faces)
            entries.append((mesh, math.log2(max(size, 1e-9)), bool(displaces(mesh)), triangles, across))
        except (TypeError, ValueError, IndexError, KeyError, ZeroDivisionError):
            continue

    def cut(target, keep):
        chosen, triangles = {}, 0
        for mesh, logsize, displaced, count, across in entries:
            want = logsize - math.log2(target)
            identity = (str(mesh.get('identity', mesh.get('name'))), detail)
            faces = len(mesh['faces'])
            if mesh.get('subdivision'):
                modo = max(0, min(6, int(mesh.get('subdivision_level', 3))))
                sub = min(modo, level(want, _HELD.get(identity + ('s',)) if keep else None))
                if keep:
                    _HELD[identity + ('s',)] = sub
                base = faces * 4 ** max(0, sub - 1) * 2 if sub else faces
            else:
                sub, base = 0, faces
            splits = min(MAX_SPLITS, level(want - sub, _HELD.get(identity + ('d',)) if keep else None))
            if keep:
                _HELD[identity + ('d',)] = splits
            # A dense polygon mesh finer than the fine target: as many quarterings of its triangles as its edges are
            # halvings too fine, within an error of the target over its size across. The fine target whatever the cut:
            # simplified coarser while editing, it was simplified again at rest, every dense mesh (a car's 26 s, Modo
            # held meanwhile), for a few triangles the preview cannot show.
            simplified = None
            fine_want = logsize - math.log2(FINE_PIXELS)
            lasting = (identity[0], 'simplify')
            if not mesh.get('subdivision') and not displaced and count >= SIMPLIFY_FROM and fine_want < 0:
                # Rounded down, its edges never coarser than the target; kept while at most half a step too coarse
                # and a step and a half too fine.
                quarter = max(0, math.floor(-fine_want + 1e-9))
                held_quarter = _HELD.get(lasting + ('q',)) if keep else None
                if held_quarter is not None and -fine_want - 1.5 <= held_quarter <= -fine_want + 0.5:
                    quarter = held_quarter
                quarter = min(quarter, max(0, int(math.log(max(1, count / MIN_TRIANGLES), 4))))
                # Its error too is held with the step: an error worked out anew at each move of the camera would make
                # the mesh anew each time, to be built again.
                error = min(1.0, FINE_PIXELS / max(across, 1e-9))
                if keep:
                    held_error = _HELD.get(lasting + ('e',))
                    if quarter == held_quarter and held_error is not None:
                        error = held_error
                    _HELD[lasting + ('q',)] = quarter
                    _HELD[lasting + ('e',)] = error
                if quarter:
                    simplified = {'quarters': quarter, 'triangles': max(MIN_TRIANGLES, count // 4 ** quarter), 'error': error}
                    base = simplified['triangles']
            chosen[id(mesh)] = {'subdivision': sub, 'splits': splits, 'simplify': simplified, 'pixels': target}
            triangles += base * 4 ** splits if displaced else base
        return chosen, triangles

    chosen, triangles = cut(pixels, False)
    budget = BUDGET.get(detail, BUDGET['fine'])
    if triangles > budget:
        # Coarser alike: the triangles go as the square of the edge.
        pixels *= math.sqrt(triangles / budget)
    chosen, _ = cut(pixels, True)
    refinable = False
    if detail == 'coarse':
        fine, _ = cut(FINE_PIXELS, False)
        # Only what the cut changes counts: a displacement's splits where it displaces, a subdivision's level.
        moved = {id(mesh): displaced for mesh, _, displaced, _, _ in entries}
        refinable = any(fine[k]['subdivision'] != chosen[k]['subdivision'] or (moved[k] and fine[k]['splits'] != chosen[k]['splits'])
                        or (fine[k]['simplify'] or {}).get('quarters') != (chosen[k]['simplify'] or {}).get('quarters') for k in chosen)
    if len(_HELD) > 16384:
        _HELD.clear()
    return chosen, refinable


# The camera a realtime MoonRay preview's meshes are cut for (its dicing camera), held while the view moves little.
_DICING = {'camera': None}


def _eye(camera):
    return (camera.get('matrix') or [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])[12:15]


def _looking(camera):
    m = camera.get('matrix') or [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    v = [-m[8], -m[9], -m[10]]
    length = math.sqrt(sum(c * c for c in v)) or 1.0
    return [c / length for c in v]


def moved(held, camera, meshes, way=0.1, turn=20.0):
    """Whether the view has moved enough from the camera held to cut the meshes anew: another projection or a lens
    over a tenth longer or shorter, a move of over a tenth (way) of the way to the meshes (their middle distance), or a
    turn of over 20 degrees (turn)."""
    if held.get('projection', 'persp') != camera.get('projection', 'persp'):
        return True
    for key in ('focal_mm', 'ortho_width', 'film_mm'):
        a, b = float(held.get(key, 1.0) or 1.0), float(camera.get(key, 1.0) or 1.0)
        if abs(a - b) > 0.1 * max(abs(a), 1e-9):
            return True
    eye, then = _eye(camera), _eye(held)
    distances = []
    for mesh in meshes[:: max(1, len(meshes) // 200)]:
        try:
            centre, _, _ = extent(mesh)
            matrix = mesh.get('matrix') or [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
            distances.append(math.sqrt(sum((c - e) ** 2 for c, e in zip(_place(centre, matrix), then))))
        except (TypeError, ValueError, IndexError, KeyError):
            continue
    reference = sorted(distances)[len(distances) // 2] if distances else 1.0
    if math.sqrt(sum((a - b) ** 2 for a, b in zip(eye, then))) > way * reference:
        return True
    facing = sum(a * b for a, b in zip(_looking(camera), _looking(held)))
    return facing < math.cos(math.radians(turn))


def held_dicing(camera, meshes, keep=False):
    """The camera to cut a realtime preview's meshes for: the one held, while the view has not moved enough (moved),
    else this one, held from now. A small move of the camera then leaves the meshes as they were cut. keep: the one held
    whatever the view (MoonRay's realtime through a move of the camera: cut anew, every mesh is a reload, until rested)."""
    held = _DICING['camera']
    if held is None or (not keep and moved(held, camera, meshes)):
        held = _DICING['camera'] = {k: v for k, v in camera.items() if k in ('matrix', 'projection', 'ortho_width', 'film_offset',
                                                                             'pixel_aspect', 'focal_mm', 'film_mm')}
    return held


def _middle(eye, meshes):
    """The middle distance from a point to the meshes' middles (from at most 200 of them)."""
    distances = []
    for mesh in meshes[:: max(1, len(meshes) // 200)]:
        try:
            centre, _, _ = extent(mesh)
            matrix = mesh.get('matrix') or [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
            distances.append(math.sqrt(sum((c - e) ** 2 for c, e in zip(_place(centre, matrix), eye))))
        except (TypeError, ValueError, IndexError, KeyError):
            continue
    return sorted(distances)[len(distances) // 2] if distances else 1.0


def rested(camera, meshes, turn=None):
    """Whether a view at rest has come far enough from the camera held through its moves (held_dicing's keep) to cut
    its meshes anew, once: another projection or a lens over a tenth longer or shorter, or the meshes a quarter nearer
    or farther, which is what their size on screen goes by; and, with turn (MoonRay's realtime, whose tessellation goes
    by what is in view), a turn of over that many degrees. Going round the scene at the same distance cut every mesh
    anew at each step (a car's 15 s for one of them). Less is left as it was cut, for no reload."""
    held = _DICING['camera']
    if held is None:
        return False
    if held.get('projection', 'persp') != camera.get('projection', 'persp'):
        return True
    for key in ('focal_mm', 'ortho_width', 'film_mm'):
        a, b = float(held.get(key, 1.0) or 1.0), float(camera.get(key, 1.0) or 1.0)
        if abs(a - b) > 0.1 * max(abs(a), 1e-9):
            return True
    then, now = _middle(_eye(held), meshes), _middle(_eye(camera), meshes)
    if abs(now - then) > 0.25 * max(then, 1e-9):
        return True
    if turn is None:
        return False
    facing = sum(a * b for a, b in zip(_looking(camera), _looking(held)))
    return facing < math.cos(math.radians(turn))
