"""Baking what MoonRay renders on a mesh into a picture laid out by the mesh's UVs.

MoonRay bakes through its BakeCamera, which looks at every point of one mesh from just above it and puts what it sees
where that point's UVs say. A scene is baked by rendering it through such a camera, with a square picture."""
IDENTITY = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
SIZES = (512, 1024, 2048, 4096, 8192)
# How the bake camera looks at the surface: MoonRay's own numbering.
MODES = (('From above the surface, down its normal', 3), ('From the camera', 0), ('From the surface, out along its normal', 1),
         ('From the surface, along the reflection of the camera', 2))


def scene(snapshot, mesh, size, udim=1001, mode=3):
    """The snapshot as it is baked: rendered through a bake camera on the mesh named, which is a Modo item's name or
    identity, into a square picture size across. No other camera is the render camera, and no region is cut out."""
    if int(size) not in SIZES:
        raise ValueError('A baked picture is %s pixels across' % ', '.join(str(v) for v in SIZES))
    if not 1001 <= int(udim) <= 1999:
        raise ValueError('A UDIM tile is numbered from 1001')
    entities = [dict(entity, parameters={key: value for key, value in entity['parameters'].items() if key != 'modo_render_camera'})
                for entity in snapshot.get('entities', [])]
    entities.append({'identity': 'modo_bake_camera', 'name': 'Bake Camera', 'class': 'BakeCamera', 'matrix': list(IDENTITY), 'attributes': {},
                     'parameters': {'geometry': str(mesh), 'udim': int(udim), 'mode': int(mode), 'modo_render_camera': True}})
    # MoonRay stops dead baking along the normals of a mesh that brings none, as one with flat faces does not: give
    # such a mesh the normals of its faces.
    meshes = []
    for held in snapshot.get('meshes', []):
        named = str(mesh) in (held.get('name'), held.get('source_item'), str(held.get('identity', '')).split('|')[0])
        if named and not held.get('normals') and not held.get('subdivision'):
            held = dict(held, normals=flat_normals(held['vertices'], held['faces']), smooth=True)
        meshes.append(held)
    made = dict(snapshot, entities=entities, width=int(size), height=int(size), meshes=meshes)
    made.pop('region', None)
    return made


def flat_normals(vertices, faces):
    """A normal for every corner of every face: the face's own (Newell's method, which a face that is not flat survives)."""
    made = []
    for face in faces:
        x = y = z = 0.0
        for index, vertex in enumerate(face):
            a, b = vertices[vertex], vertices[face[(index + 1) % len(face)]]
            x += (a[1] - b[1]) * (a[2] + b[2])
            y += (a[2] - b[2]) * (a[0] + b[0])
            z += (a[0] - b[0]) * (a[1] + b[1])
        length = (x * x + y * y + z * z) ** .5
        normal = [x / length, y / length, z / length] if length > 1e-20 else [0.0, 1.0, 0.0]
        made += [normal] * len(face)
    return made


def placeholder(name):
    """What stands in the scene's text for a Modo mesh, until the meshes have been written and it is known which."""
    return '@@MODO_MESH(%s)@@' % name


def resolve(text_lines, meshes):
    """Put the mesh each placeholder names in its place: meshes are the scene's as written, in order."""
    for at, line in enumerate(text_lines):
        if '@@MODO_MESH(' not in line:
            continue
        name = line.split('@@MODO_MESH(', 1)[1].split(')@@', 1)[0]
        found = [index for index, mesh in enumerate(meshes)
                 if name in (mesh.get('name'), mesh.get('source_item'), str(mesh.get('identity', '')).split('|')[0])]
        if not found:
            raise ValueError('The bake camera needs a Modo mesh that renders; %s is not one' % (name or 'no mesh'))
        if len(found) > 1:
            raise ValueError('The bake camera needs one mesh; %s is the name of %d, or a mesh of several parts' % (name, len(found)))
        if not meshes[found[0]].get('uvs') and not meshes[found[0]].get('uv_sets'):
            # MoonRay stops dead on a mesh with nowhere to bake to.
            raise ValueError('%s has no UV map to bake into; give it one first' % (meshes[found[0]].get('name') or name))
        text_lines[at] = line.replace(placeholder(name), 'RdlMeshGeometry("/modo/mesh/%d")' % found[0])
