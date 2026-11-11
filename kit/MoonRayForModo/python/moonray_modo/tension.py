"""Modo's Tension texture: how a deformed mesh has stretched or folded at each point from its base mesh, worked out from
the rest points (the base mesh, as host reads them for a mesh wearing the layer) and the points as rendered, and handed
to MoonRay, XPU2 and MoonLightIPR as a weight at each point, which the layer's gradient reads (procedurals.tension).

Both measures are fitted to Modo's own renders (tools/probe_gui_tension_layer.py, probe_gui_tension_angle.py):
- Area: the area of the faces about a point now, over their area at rest, less 1: 0 unchanged, 1 at twice the area,
  -0.5 at half; a shear that keeps the area gives 0. Exact on Modo's stretched squares.
- Angle: how far the surface has folded at a point. With a the angle between the point's normal and the faces about it
  (twice it, against its value at rest), the measure is |2 (1 - cos a) / (1 + 2 cos a)|: 0.5 at a fold of 60 degrees,
  2 at 90, 4 folded flat back; Modo's own values on folds of 15 to 179 degrees, on meshes of 2 to 8 polygons across.
Between points the value runs straight across each polygon, as Modo's does. A mesh whose base mesh has another number
of points (a deformer that adds or takes away points) has no rest points to compare with, and reads 0.
"""
import math

PREFIX = '__modo_tension'
REST = '_tension_rest'


def map_name(kind, low, high):
    """The weight map a Tension layer of this type and gradient span reads."""
    return '%s_%s_%s_%s' % (PREFIX, kind, repr(float(low)), repr(float(high)))


def wanted(materials):
    """{map name: (kind, low, high)} for every Tension layer the scene's materials hold, and the material tags that
    hold each."""
    found, holders = {}, {}

    def walk(value, tag):
        if isinstance(value, dict):
            settings = value.get('tension')
            if isinstance(settings, dict) and value.get('vmap'):
                found[value['vmap']] = (str(settings['kind']), float(settings['low']), float(settings['high']))
                holders.setdefault(value['vmap'], set()).add(tag)
            for inner in value.values():
                walk(inner, tag)
        elif isinstance(value, (list, tuple)):
            for inner in value:
                walk(inner, tag)

    for tag, material in (materials or {}).items():
        walk(material, tag)
    return found, holders


def _face_normals(points, faces):
    """Each face's normal, as long as its area is large (twice it), by the fan of its corners."""
    normals = []
    for face in faces:
        x = y = z = 0.0
        if len(face) >= 3:
            a = points[face[0]]
            for i in range(1, len(face) - 1):
                b, c = points[face[i]], points[face[i + 1]]
                u0, u1, u2 = b[0] - a[0], b[1] - a[1], b[2] - a[2]
                v0, v1, v2 = c[0] - a[0], c[1] - a[1], c[2] - a[2]
                x += u1 * v2 - u2 * v1
                y += u2 * v0 - u0 * v2
                z += u0 * v1 - u1 * v0
        normals.append((x, y, z))
    return normals


def _length(v):
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _bends(points, faces, normals):
    """At each point, twice the mean angle between its normal (its faces' normals summed, by area) and each face."""
    summed = [[0.0, 0.0, 0.0] for _ in points]
    about = [[] for _ in points]
    for index, face in enumerate(faces):
        n = normals[index]
        for p in face:
            held = summed[p]
            held[0] += n[0]
            held[1] += n[1]
            held[2] += n[2]
            about[p].append(index)
    bends = []
    for p, held in enumerate(summed):
        size = _length(held)
        angles = []
        for index in about[p]:
            n = normals[index]
            length = _length(n)
            if size > 1e-30 and length > 1e-30:
                angles.append(math.acos(max(-1.0, min(1.0, (held[0] * n[0] + held[1] * n[1] + held[2] * n[2]) / (size * length)))))
            elif length > 1e-30:
                angles.append(math.pi / 2)  # faces folded flat back on one another: no normal between them
        bends.append(2.0 * sum(angles) / len(angles) if angles else 0.0)
    return bends


def values(kind, rest, points, faces):
    """The Tension at each point: kind 'area' or 'angle'."""
    rest, points = [tuple(p) for p in rest], [tuple(p) for p in points]
    if kind == 'area':
        now = [_length(n) for n in _face_normals(points, faces)]
        before = [_length(n) for n in _face_normals(rest, faces)]
        total_now, total_before = [0.0] * len(points), [0.0] * len(points)
        for index, face in enumerate(faces):
            for p in face:
                total_now[p] += now[index]
                total_before[p] += before[index]
        return [(a / b - 1.0) if b > 1e-30 else 0.0 for a, b in zip(total_now, total_before)]
    bent_now = _bends(points, faces, _face_normals(points, faces))
    bent_before = _bends(rest, faces, _face_normals(rest, faces))
    found = []
    for a, b in zip(bent_now, bent_before):
        c = math.cos(max(0.0, a - b))
        below = 1.0 + 2.0 * c
        found.append(min(1000.0, abs(2.0 * (1.0 - c) / below)) if abs(below) > 1e-3 else 1000.0)
    return found


def apply(snapshot, warnings):
    """Add each Tension layer's weights to the meshes that wear it (point_attributes), and drop the rest points host
    read for them."""
    found, holders = wanted(snapshot.get('materials'))
    for mesh in snapshot.get('meshes', []):
        rest = mesh.pop(REST, None)
        if not found or not mesh.get('vertices') or not mesh.get('faces'):
            continue
        worn = set(mesh.get('face_materials') or []) | {mesh.get('material', '')}
        for name, (kind, low, high) in found.items():
            if not worn & holders.get(name, set()):
                continue
            if rest is None and name in (mesh.get('point_attributes') or {}):
                continue  # a mesh kept from the last read (unchanged), its weights with it
            if rest is None or len(rest) != len(mesh['vertices']):
                warnings.append('Tension on %s: its base mesh could not be compared with it, so it reads as unchanged.' % mesh.get('name'))
                measured = [0.0] * len(mesh['vertices'])
            else:
                measured = values(kind, rest, mesh['vertices'], mesh['faces'])
            span = high - low
            mesh.setdefault('point_attributes', {})[name] = {'kind': 'float', 'values': [[min(1.0, max(0.0, (v - low) / span))] for v in measured]}
