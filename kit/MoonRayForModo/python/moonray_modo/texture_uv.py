"""Modo's Gradient on Texture U or V: the layer's UV map at each corner of each polygon, handed to MoonRay, XPU2 and
MoonLightIPR as a weight (scaled from the span the gradient's keys change over to 0..1), which the gradient reads as a
Weight Map Texture does (gradients.capture). Followed with a UV map projection; the UV map is the one the mesh's
material reads (the layer names it, as an image's does), else a notice.
"""
PREFIX = '__modo_texture_uv'


def map_name(axis, uv_map, low, high):
    """The weight map a Gradient on Texture U (axis 0) or V (1) of this UV map and span reads."""
    return '%s_%s_%s_%s_%s' % (PREFIX, 'uv'[axis], uv_map, repr(float(low)), repr(float(high)))


def wanted(materials):
    """{map name: (axis, uv map, low, high)} for every Gradient on Texture U or V, and the material tags holding each."""
    found, holders = {}, {}

    def walk(value, tag):
        if isinstance(value, dict):
            settings = value.get('texture')
            if isinstance(settings, dict) and value.get('vmap') and 'axis' in settings:
                found[value['vmap']] = (int(settings['axis']), str(settings['uv_map']), float(settings['low']), float(settings['high']))
                holders.setdefault(value['vmap'], set()).add(tag)
            for inner in value.values():
                walk(inner, tag)
        elif isinstance(value, (list, tuple)):
            for inner in value:
                walk(inner, tag)

    for tag, material in (materials or {}).items():
        walk(material, tag)
    return found, holders


def apply(snapshot, warnings):
    """Add each Texture U or V weight to the meshes whose material reads it (corner_attributes)."""
    found, holders = wanted(snapshot.get('materials'))
    if not found:
        return
    for mesh in snapshot.get('meshes', []):
        faces, uvs = mesh.get('faces'), mesh.get('uvs')
        if not faces:
            continue
        worn = set(mesh.get('face_materials') or []) | {mesh.get('material', '')}
        corners = sum(len(faces[i]) for i in range(len(faces)))
        read_map = str(mesh.get('identity', '')).split('|')[2] if str(mesh.get('identity', '')).count('|') >= 2 else None
        for name, (axis, uv_map, low, high) in found.items():
            if not worn & holders.get(name, set()) or name in (mesh.get('corner_attributes') or {}):
                continue
            if not uvs or len(uvs) != corners or (read_map is not None and read_map != uv_map):
                warnings.append('Gradient on Texture %s on %s: its UV map %s is not the one the mesh is read with; it reads 0.'
                                % ('UV'[axis], mesh.get('name'), uv_map))
                values = [[0.0]] * corners
            else:
                span = (high - low) or 1.0
                values = [[min(1.0, max(0.0, (float(uvs[i][axis]) - low) / span))] for i in range(corners)]
            mesh.setdefault('corner_attributes', {})[name] = {'kind': 'float', 'values': values}
