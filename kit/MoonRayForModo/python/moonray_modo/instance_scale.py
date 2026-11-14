"""Displaced instances' scale in their mesh's points.

MoonRay displaces a mesh handed over once and placed by an instancer (Modo's mesh instances) in the mesh's own space,
before each instance's transform: a sea of one 1 m plane instanced sixteen times at 27.31 had its waves 27 times as tall
as the same plane placed alone, which is displaced where it stands (a tester's scene, its sea blown out into spikes).
Where every instance, and the mesh, is scaled the same, evenly, that scale goes into the mesh's points and out of the
transforms: the same surfaces where they were, displaced by the metres the material says."""

TOLERANCE = 1e-4


def _scale(matrix):
    """A transform's even scale (row-vector 4x4, flat), or None where its axes are not scaled alike."""
    if not matrix or len(matrix) != 16:
        return None
    lengths = [sum(float(matrix[4 * r + c]) ** 2 for c in range(3)) ** 0.5 for r in range(3)]
    if min(lengths) <= 0 or max(lengths) - min(lengths) > TOLERANCE * max(lengths):
        return None
    return sum(lengths) / 3.0


def _unscaled(matrix, scale):
    """The transform with the scale taken out of its axes (applied to the points instead)."""
    return [float(v) / scale if i < 12 and i % 4 < 3 else float(v) for i, v in enumerate(matrix)]


# The points scaled, by the list they came from and the scale: the same list again for the same mesh, so what is kept
# by its lists (the realtime's readings, the binary geometry) is kept.
_POINTS = {}


def _points(vertices, scale):
    key = (id(vertices), scale)
    held = _POINTS.get(key)
    if held is not None and held[0] is vertices:
        return held[1]
    from .rows import numbers
    flat = numbers(vertices, 3)
    flat = list(flat) if flat is not None else [c for v in vertices for c in v]
    value = [[flat[i] * scale, flat[i + 1] * scale, flat[i + 2] * scale] for i in range(0, len(flat), 3)]
    if len(_POINTS) > 64:
        _POINTS.clear()
    _POINTS[key] = (vertices, value)
    return value


def displaced_tags(scene):
    """The material tags whose materials displace: a MoonShine graph's displacement, or Shader Tree displacement."""
    tags = set()
    for tag, material in (scene.get('materials') or {}).items():
        for row in material.get('material_stack') or [material]:
            layers = row.get('layers') or []
            if ((row.get('node_graph') or {}).get('displacement') or 'displace' in (row.get('textures') or {})
                    or any(layer.get('effect') == 'displace' for layer in layers if isinstance(layer, dict))):
                tags.add(tag)
                break
    return tags


def baked(scene):
    """The scene with each displaced, instanced mesh's even scale in its points (a copy where any is changed)."""
    meshes = scene.get('meshes') or []
    displaced = None
    changed = []
    for index, mesh in enumerate(meshes):
        instances = mesh.get('instances')
        if not instances or mesh.get('instance_transform_motion') or mesh.get('point_attributes'):
            continue
        if displaced is None:
            displaced = displaced_tags(scene)
        if not ({mesh.get('material', '')} | set(mesh.get('face_materials') or [])) & displaced:
            continue
        scales = [_scale(m) for m in instances]
        if any(s is None for s in scales):
            continue
        scale = scales[0]
        if abs(scale - 1.0) <= TOLERANCE or any(abs(s - scale) > TOLERANCE * scale for s in scales):
            continue
        own = mesh.get('matrix')
        if own is not None and len(own) == 16 and _scale(own) is None:
            continue
        value = dict(mesh, vertices=_points(mesh['vertices'], scale), instances=[_unscaled(m, scale) for m in instances], baked_instance_scale=scale)
        if own is not None and len(own) == 16:
            value['matrix'] = _unscaled(own, scale)
        if mesh.get('velocities'):
            value['velocities'] = [[c * scale for c in v] for v in mesh['velocities']]
        changed.append((index, value))
    if not changed:
        return scene
    meshes = list(meshes)
    for index, value in changed:
        meshes[index] = value
    return dict(scene, meshes=meshes)
