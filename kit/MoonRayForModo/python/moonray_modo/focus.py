"""Find how far from the camera the surface under a point of the preview is.

Works on a captured scene, the same one the preview was rendered from, so it sees instances
and evaluated geometry as rendered. Pure Python: one ray against every triangle, with a box
test per mesh placement first.
"""
import math

IDENTITY = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]


def ray(camera, width, height, u, v):
    """The eye and the direction through (u, v), 0..1 from the image's top left. The direction
    advances one unit along the view axis, so a distance along it is a depth from the camera."""
    matrix = [float(value) for value in camera.get('matrix', IDENTITY)]
    across = float(camera['film_mm']) / (2.0 * float(camera['focal_mm']))
    up = across * height / max(1, width)
    x, y = (2.0 * u - 1.0) * across, (1.0 - 2.0 * v) * up
    # Rows of the matrix are the basis vectors; the camera looks down its local -Z axis.
    return matrix[12:15], [x * matrix[a] + y * matrix[4 + a] - matrix[8 + a] for a in range(3)]


def inverse(m):
    """The inverse of the 3 x 3 part of a placement, or None if it is flat."""
    a, b, c, d, e, f, g, h, i = m[0], m[1], m[2], m[4], m[5], m[6], m[8], m[9], m[10]
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if abs(det) < 1e-18 or not math.isfinite(det):
        return None
    return [(e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det,
            (f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det,
            (d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det]


def box_hit(origin, direction, low, high, nearest):
    start, end = 0.0, nearest
    for k in range(3):
        if abs(direction[k]) < 1e-12:
            if origin[k] < low[k] or origin[k] > high[k]:
                return False
            continue
        one, two = (low[k] - origin[k]) / direction[k], (high[k] - origin[k]) / direction[k]
        if one > two:
            one, two = two, one
        start, end = max(start, one), min(end, two)
        if start > end:
            return False
    return True


def depth(scene, u, v):
    """Depth of the nearest surface under (u, v), or None where there is none."""
    eye, direction = ray(scene['camera'], scene['width'], scene['height'], u, v)
    nearest = math.inf
    for mesh in scene.get('meshes', []):
        vertices, faces = mesh.get('vertices') or [], mesh.get('faces') or []
        if not vertices or not faces:
            continue
        low = [min(p[k] for p in vertices) for k in range(3)]
        high = [max(p[k] for p in vertices) for k in range(3)]
        for placement in (mesh['instances'] if 'instances' in mesh else [mesh.get('matrix', IDENTITY)]):
            m = [float(value) for value in placement]
            back = inverse(m)
            if back is None:
                continue
            # A point is placed as p . R + T, so the ray goes into the mesh's own space by the inverse.
            moved = [eye[k] - m[12 + k] for k in range(3)]
            o = [moved[0] * back[k] + moved[1] * back[3 + k] + moved[2] * back[6 + k] for k in range(3)]
            d = [direction[0] * back[k] + direction[1] * back[3 + k] + direction[2] * back[6 + k] for k in range(3)]
            if not box_hit(o, d, low, high, nearest):
                continue
            ox, oy, oz = o
            dx, dy, dz = d
            for face in faces:
                a = vertices[face[0]]
                ax, ay, az = a[0], a[1], a[2]
                for n in range(1, len(face) - 1):
                    b, c = vertices[face[n]], vertices[face[n + 1]]
                    e1x, e1y, e1z = b[0] - ax, b[1] - ay, b[2] - az
                    e2x, e2y, e2z = c[0] - ax, c[1] - ay, c[2] - az
                    px, py, pz = dy * e2z - dz * e2y, dz * e2x - dx * e2z, dx * e2y - dy * e2x
                    det = e1x * px + e1y * py + e1z * pz
                    if -1e-14 < det < 1e-14:
                        continue
                    tx, ty, tz = ox - ax, oy - ay, oz - az
                    s = (tx * px + ty * py + tz * pz) / det
                    if s < 0.0 or s > 1.0:
                        continue
                    qx, qy, qz = ty * e1z - tz * e1y, tz * e1x - tx * e1z, tx * e1y - ty * e1x
                    w = (dx * qx + dy * qy + dz * qz) / det
                    if w < 0.0 or s + w > 1.0:
                        continue
                    t = (e2x * qx + e2y * qy + e2z * qz) / det
                    if 1e-6 < t < nearest:
                        nearest = t
    return nearest if math.isfinite(nearest) else None
