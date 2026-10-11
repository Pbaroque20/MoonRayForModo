"""The draft picture: the scene as plain lines from the render camera, to draw a region on.

Nothing is rendered for it. Each mesh is shown by its own polygons where it is light, and where it is dense by its
outline alone: its open borders, the edges where it turns a corner, and its rim as the camera sees it, which is all
there is to a ball. A mesh too heavy for that is shown by the box it fits in. The lines are worked out once for a
mesh and kept until the mesh changes; the rim, each time the mesh or the camera moves.
"""
import math

from PySide2 import QtCore, QtGui

# The paper, from its head to its foot, and the ink.
PAPER = ('#f5f2ec', '#cfd0d4')
INK = '#a08467'
# A mesh of this many edges or fewer is drawn whole; past it, by its corners, of which this many at most.
WHOLE, MOST = 1500, 6000
# Past this many polygons a mesh is not read at all: it is its box.
READ = 400000
# Up to this many polygons a dense mesh is given its rim as well.
RIMMED = 60000
# The turn between two polygons, as a cosine, past which their edge is a corner (about 28 degrees).
CORNER = .88
IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]

_lines = {}


def _box(vertices):
    low = [min(v[a] for v in vertices) for a in range(3)]
    high = [max(v[a] for v in vertices) for a in range(3)]
    points = [[(low, high)[i >> a & 1][a] for a in range(3)] for i in range(8)]
    return points, [(i, i | 1 << a) for i in range(8) for a in range(3) if not i >> a & 1], None


def lines(mesh):
    """A mesh's lines in its own space: the points they join, the pairs of them joined, and for a dense mesh what
    its rim is found from: a point and the normal of each polygon, and the edges between two polygons as
    (point, point, polygon, polygon)."""
    vertices, faces = mesh.get('vertices') or [], mesh.get('faces') or []
    if not len(vertices) or not len(faces):
        return [], [], None
    key = (id(vertices), id(faces), len(vertices), len(faces))
    kept = _lines.get(key)
    # The lists themselves are held, so that their places in memory cannot pass to other lists while this is kept.
    if kept is not None and kept[0] is vertices and kept[1] is faces:
        return kept[2]
    if len(faces) > READ:
        made = _box(vertices)
    else:
        edges, anchors, normals = {}, [], []
        for number, face in enumerate(faces):
            count = len(face)
            anchors.append(vertices[face[0]] if count else (0.0, 0.0, 0.0))
            normals.append((0.0, 0.0, 0.0))
            if count < 3:
                continue
            a, b, c = vertices[face[0]], vertices[face[1]], vertices[face[2]]
            e, f = (b[0] - a[0], b[1] - a[1], b[2] - a[2]), (c[0] - a[0], c[1] - a[1], c[2] - a[2])
            normal = (e[1] * f[2] - e[2] * f[1], e[2] * f[0] - e[0] * f[2], e[0] * f[1] - e[1] * f[0])
            size = math.sqrt(normal[0] ** 2 + normal[1] ** 2 + normal[2] ** 2) or 1.0
            normals[number] = (normal[0] / size, normal[1] / size, normal[2] / size)
            for i in range(count):
                p, q = face[i], face[(i + 1) % count]
                edges.setdefault((p, q) if p < q else (q, p), []).append(number)
        pairs, smooth = list(edges), []
        if len(pairs) > WHOLE:
            def corner(sides):
                a, b = normals[sides[0]], normals[sides[1]]
                return a[0] * b[0] + a[1] * b[1] + a[2] * b[2] < CORNER
            pairs = [pair for pair, sides in edges.items() if len(sides) != 2 or corner(sides)]
            if len(pairs) > MOST:
                pairs = pairs[::-(-len(pairs) // MOST)]
            if len(faces) <= RIMMED:
                sharp = set(pairs)
                smooth = [(pair, sides) for pair, sides in edges.items() if len(sides) == 2 and pair not in sharp]
        if len(pairs) < 12 and not smooth:
            made = _box(vertices)
        else:
            # Only the points the lines join are kept and placed.
            used = {}
            for p, q in pairs + [pair for pair, _ in smooth]:
                used.setdefault(p, len(used))
                used.setdefault(q, len(used))
            rim = (anchors, normals, [(used[p], used[q], f, g) for (p, q), (f, g) in smooth]) if smooth else None
            made = [vertices[index] for index in used], [(used[p], used[q]) for p, q in pairs], rim
    if len(_lines) > 256:
        _lines.clear()
    _lines[key] = (vertices, faces, made)
    return made


def _unit(v):
    size = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / size for x in v]


def segments(scene, width, height):
    """Every line of the scene as the render camera sees it: (x, y, x, y) in pixels of the picture."""
    camera = scene['camera']
    m = [float(v) for v in camera.get('matrix', IDENTITY)]
    right, up, back, eye = _unit(m[0:3]), _unit(m[4:7]), _unit(m[8:11]), m[12:15]
    half = float(camera.get('film_mm', 36.0)) / (2 * max(1e-6, float(camera.get('focal_mm', 50.0))))
    across, down = .5 * width / half, .5 * width / half     # the same scale both ways: pixels are square
    near, found = 1e-3, []
    for mesh in scene.get('meshes', []):
        points, pairs, rim = lines(mesh)
        if not pairs and not rim:
            continue
        for t in (mesh['instances'] if 'instances' in mesh else [mesh.get('matrix', IDENTITY)]):
            seen = []
            for p in points:
                # Rows of the matrix are the basis vectors, as elsewhere in the snapshot.
                d = [p[0] * t[a] + p[1] * t[4 + a] + p[2] * t[8 + a] + t[12 + a] - eye[a] for a in range(3)]
                seen.append((d[0] * right[0] + d[1] * right[1] + d[2] * right[2], d[0] * up[0] + d[1] * up[1] + d[2] * up[2],
                             -(d[0] * back[0] + d[1] * back[1] + d[2] * back[2])))
            joined = pairs
            if rim:
                # The rim: the edges with a polygon turned to the camera on one side and one turned away on the other.
                anchors, normals, turning = rim
                facing = []
                for p, n in zip(anchors, normals):
                    facing.append((p[0] * t[0] + p[1] * t[4] + p[2] * t[8] + t[12] - eye[0]) * (n[0] * t[0] + n[1] * t[4] + n[2] * t[8])
                                  + (p[0] * t[1] + p[1] * t[5] + p[2] * t[9] + t[13] - eye[1]) * (n[0] * t[1] + n[1] * t[5] + n[2] * t[9])
                                  + (p[0] * t[2] + p[1] * t[6] + p[2] * t[10] + t[14] - eye[2]) * (n[0] * t[2] + n[1] * t[6] + n[2] * t[10]) < 0)
                joined = pairs + [(i, j) for i, j, f, g in turning if facing[f] != facing[g]]
            for i, j in joined:
                a, b = seen[i], seen[j]
                if a[2] < near and b[2] < near:
                    continue
                if a[2] < near or b[2] < near:
                    # Cut where it passes behind the camera.
                    s = (near - a[2]) / (b[2] - a[2])
                    cut = (a[0] + (b[0] - a[0]) * s, a[1] + (b[1] - a[1]) * s, near)
                    a, b = (cut, b) if a[2] < near else (a, cut)
                x0, y0 = .5 * width + across * a[0] / a[2], .5 * height - down * a[1] / a[2]
                x1, y1 = .5 * width + across * b[0] / b[2], .5 * height - down * b[1] / b[2]
                if max(x0, x1) < 0 or min(x0, x1) > width or max(y0, y1) < 0 or min(y0, y1) > height:
                    continue
                # A line running far out of the picture is drawn only as far as matters.
                limit = 8.0 * (width + height)
                if max(abs(x0), abs(y0), abs(x1), abs(y1)) > limit:
                    continue
                found.append((x0, y0, x1, y1))
    return found


def picture(scene, width, height):
    """The draft picture of a snapshot, of the size given."""
    image = QtGui.QImage(int(width), int(height), QtGui.QImage.Format_RGB32)
    painter = QtGui.QPainter(image)
    try:
        paper = QtGui.QLinearGradient(0, 0, 0, height)
        paper.setColorAt(0.0, QtGui.QColor(PAPER[0]))
        paper.setColorAt(1.0, QtGui.QColor(PAPER[1]))
        painter.fillRect(image.rect(), paper)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        pen = QtGui.QPen(QtGui.QColor(INK))
        pen.setWidthF(max(1.0, width / 900.0))
        painter.setPen(pen)
        painter.drawLines([QtCore.QLineF(*line) for line in segments(scene, width, height)])
    finally:
        painter.end()
    return image


def over(draft, rendered, region):
    """The draft picture with what was rendered laid on it inside the region (left, top, right, bottom as fractions)."""
    made = QtGui.QImage(draft)
    if rendered is None or rendered.isNull() or not region:
        return made
    left, top, right, bottom = region
    painter = QtGui.QPainter(made)
    try:
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        painter.drawImage(QtCore.QRectF(left * made.width(), top * made.height(), (right - left) * made.width(), (bottom - top) * made.height()), rendered,
                          QtCore.QRectF(left * rendered.width(), top * rendered.height(), (right - left) * rendered.width(), (bottom - top) * rendered.height()))
    finally:
        painter.end()
    return made
