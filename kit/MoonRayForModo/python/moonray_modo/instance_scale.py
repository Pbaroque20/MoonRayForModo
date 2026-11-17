"""Instanced seas' scale in their mesh's points (seas alone: meshes wearing an Ocean node, ocean.ocean_tags).

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


def _single(mesh):
    """A sea placed alone, its transform's even scale in its points (and in its points and transform at the shutter's
    close), or None where it has none to move or cannot be moved so."""
    if mesh.get('point_attributes'):
        return None
    own = mesh.get('matrix')
    scale = _scale(own)
    if scale is None or abs(scale - 1.0) <= TOLERANCE:
        return None
    close = mesh.get('matrix_close')
    if close is not None and (_scale(close) is None or abs(_scale(close) - scale) > TOLERANCE * scale):
        return None
    value = dict(mesh, vertices=_points(mesh['vertices'], scale), matrix=_unscaled(own, scale), baked_instance_scale=scale)
    if close is not None:
        value['matrix_close'] = _unscaled(close, scale)
    if mesh.get('vertices_close'):
        value['vertices_close'] = _points(mesh['vertices_close'], scale)
    if mesh.get('velocities'):
        value['velocities'] = [[c * scale for c in v] for v in mesh['velocities']]
    return value


def baked(scene, single=False):
    """The scene with each instanced sea's even scale in its points (a copy where any is changed). A sea is a mesh
    wearing an Ocean node's displacement (ocean.ocean_tags); no other mesh is touched: given to every displaced
    instancer, other instanced parts (a car's) were changed with it. single: a sea placed alone too, for MoonLightIPR,
    which displaces a mesh in its own space before its transform (MoonRay and XPU2 displace one where it stands): the
    1 m plane of a tester's dragon scene, scaled 27.31 as a sea of its own, was blown out over the whole picture in
    MoonLightIPR alone."""
    from .ocean import ocean_tags, wears_ocean
    materials = scene.get('materials')
    seas = ocean_tags(materials)
    if not seas:
        return scene
    meshes = scene.get('meshes') or []
    changed = []
    for index, mesh in enumerate(meshes):
        instances = mesh.get('instances')
        if not (instances or (single and mesh.get('vertices'))) or not wears_ocean(mesh, materials, seas):
            continue
        if not instances:
            value = _single(mesh)
            if value is not None:
                changed.append((index, value))
            continue
        if mesh.get('instance_transform_motion') or mesh.get('point_attributes'):
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
