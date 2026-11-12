"""Modo's Occlusion texture: how open each point of a mesh is, worked out once by the runtime's modo_occlusion (Embree, on
every core) and handed to MoonRay, XPU2 and MoonLightIPR as a weight at each point, which the layer reads as a Weight
Map Texture does (procedurals.occlusion: from its Low to its High, as Bias and Gain bend the way).

The measure is fitted to Modo's own renders (tools/probe_gui_occlusion_layer.py, native-port/modo_occlusion.cpp):
within 0.031 of Modo across a floor meeting a wall, for five settings. It is measured at the mesh's points rather than at
each pixel as Modo does, so a mesh of few, large polygons shows it coarser; and every mesh in the scene blocks the rays.
A mesh placed more than once is measured where it is first placed.
"""
import hashlib
import math
import struct
import subprocess
from pathlib import Path

PREFIX = '__modo_occlusion'


def map_name(rays, distance, spread):
    """The weight map an Occlusion layer of these settings reads."""
    return '%s_r%d_d%s_s%s' % (PREFIX, int(rays), repr(float(distance)), repr(float(spread)))


def wanted(materials):
    """{map name: (rays, distance, spread)} for every Occlusion layer the scene's materials hold, and the material tags
    that hold each."""
    found, holders = {}, {}

    def walk(value, tag):
        if isinstance(value, dict):
            settings = value.get('occlusion')
            if isinstance(settings, dict) and value.get('vmap'):
                found[value['vmap']] = (int(settings['rays']), float(settings['distance']), float(settings['spread']))
                holders.setdefault(value['vmap'], set()).add(tag)
            for inner in value.values():
                walk(inner, tag)
        elif isinstance(value, (list, tuple)):
            for inner in value:
                walk(inner, tag)

    for tag, material in (materials or {}).items():
        walk(material, tag)
    return found, holders


def placed(matrix, point):
    m = [float(v) for v in matrix]
    return (point[0] * m[0] + point[1] * m[4] + point[2] * m[8] + m[12],
            point[0] * m[1] + point[1] * m[5] + point[2] * m[9] + m[13],
            point[0] * m[2] + point[1] * m[6] + point[2] * m[10] + m[14])


def turned(matrix, vector):
    m = [float(v) for v in matrix]
    return (vector[0] * m[0] + vector[1] * m[4] + vector[2] * m[8],
            vector[0] * m[1] + vector[1] * m[5] + vector[2] * m[9],
            vector[0] * m[2] + vector[1] * m[6] + vector[2] * m[10])


def placements(mesh):
    return mesh.get('instances') or [mesh.get('matrix') or [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]]


def point_normals(vertices, faces):
    """Each point's normal, from the faces about it, each by its area."""
    normals = [[0.0, 0.0, 0.0] for _ in vertices]
    for face in faces:
        if len(face) < 3:
            continue
        a = vertices[face[0]]
        for i in range(1, len(face) - 1):
            b, c = vertices[face[i]], vertices[face[i + 1]]
            u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
            v = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
            n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
            for index in face:
                held = normals[index]
                held[0] += n[0]
                held[1] += n[1]
                held[2] += n[2]
    return normals


def number(*words):
    """A random number from 0 to 1 for these words (an item's identity, a part's name), the same each render."""
    text = '|'.join(str(word) for word in words)
    return int(hashlib.sha256(text.encode('utf-8')).hexdigest()[:8], 16) / float(0xFFFFFFFF)


def reads(materials, name):
    """Whether any material reads the weight map of this name."""
    def walk(value):
        if isinstance(value, dict):
            return value.get('vmap') == name or any(walk(inner) for inner in value.values())
        if isinstance(value, (list, tuple)):
            return any(walk(inner) for inner in value)
        return False
    return walk(materials or {})


def part_numbers(identity, parts, ordinals, faces):
    """Variation by Mesh Part: at each corner of each face, its Part's number (from the item and the part's name).
    parts holds each surface polygon's Part tag, ordinals which surface polygon each face is."""
    held, values = {}, []
    for index, ordinal in enumerate(ordinals):
        part = parts[ordinal] if 0 <= ordinal < len(parts) else ''
        if part not in held:
            held[part] = [number(identity, part)]
        values.extend([held[part]] * len(faces[index]))
    return values


def variation(snapshot, warnings):
    """Modo's Variation Texture by Item: each mesh item's points given one random number of its own, from its identity
    (the same from one render to the next), under the map the layer reads (procedurals.VARIATION_MAP)."""
    from .procedurals import VARIATION_MAP
    found = []

    def walk(value):
        if isinstance(value, dict):
            if value.get('vmap') == VARIATION_MAP:
                found.append(True)
            for inner in value.values():
                walk(inner)
        elif isinstance(value, (list, tuple)):
            for inner in value:
                walk(inner)

    walk(snapshot.get('materials'))
    if not found:
        return
    for mesh in snapshot.get('meshes', []):
        if not mesh.get('vertices'):
            continue
        identity = str(mesh.get('identity') or mesh.get('name') or '').split('|')[0]
        value = int(hashlib.sha256(identity.encode('utf-8')).hexdigest()[:8], 16) / float(0xFFFFFFFF)
        mesh.setdefault('point_attributes', {})[VARIATION_MAP] = {'kind': 'float', 'values': [[value]] * len(mesh['vertices'])}
        if len(placements(mesh)) > 1:
            warnings.append('Variation by item on %s: its copies share one number.' % mesh.get('name'))


def replica(mesh):
    """Which replica a mesh that stands alone is: a Replicator's replica given its own mesh (evaluated, its identity the
    source item, the replica's number, the material and the piece) by the first two, any other mesh by its item."""
    words = str(mesh.get('identity') or mesh.get('name') or '').split('|')
    return '|'.join(words[:2]) if mesh.get('evaluated_geometry') and len(words) >= 4 else words[0]


def particles(snapshot):
    """Modo's Variation Texture by Particle: a random number for each replica, from its identity (the same from one
    render to the next), as instance_variation, one for each placement of each mesh. MoonRay reads it as an attribute of
    each instance (instance_attributes) or, where a mesh stands alone, of its points, under procedurals.
    VARIATION_PARTICLE_MAP; MoonLightIPR as a number of each instance (moonlightipr_scene)."""
    from .procedurals import VARIATION_PARTICLE_MAP
    if not reads(snapshot.get('materials'), VARIATION_PARTICLE_MAP):
        return
    for mesh in snapshot.get('meshes', []):
        if not mesh.get('vertices'):
            continue
        ids = mesh.get('instance_ids')
        if mesh.get('instances') and ids and len(ids) == len(mesh['instances']):
            values = [number(identity) for identity in ids]
            held = mesh.get('instance_attributes') or [[] for _ in ids]
            mesh['instance_attributes'] = [[entry for entry in row if entry.get('name') != VARIATION_PARTICLE_MAP]
                                           + [{'name': VARIATION_PARTICLE_MAP, 'type': 'float', 'value': value}]
                                           for row, value in zip(held, values)]
        else:
            values = [number(replica(mesh))] * len(placements(mesh))
            mesh.setdefault('point_attributes', {})[VARIATION_PARTICLE_MAP] = {'kind': 'float', 'values': [[values[0]]] * len(mesh['vertices'])}
        mesh['instance_variation'] = values


def apply(snapshot, warnings, runtime=None):
    """Add each Occlusion layer's weights to the meshes that wear it (point_attributes), and each item's Variation
    Texture number."""
    variation(snapshot, warnings)
    particles(snapshot)
    found, holders = wanted(snapshot.get('materials'))
    if not found:
        return
    meshes = [m for m in snapshot.get('meshes', []) if m.get('vertices') and m.get('faces')]
    # What blocks the rays: every mesh where it is placed, as triangles in the world.
    blockers = []
    for mesh in meshes:
        vertices, faces = mesh['vertices'], mesh['faces']
        for matrix in placements(mesh):
            world = [placed(matrix, p) for p in vertices]
            for face in faces:
                for i in range(1, len(face) - 1):
                    blockers.extend(world[face[0]] + world[face[i]] + world[face[i + 1]])
    blocking = struct.pack('<%df' % len(blockers), *blockers)
    from . import native
    tool = native.tool('modo_occlusion.exe', runtime)
    if not Path(tool).is_file():
        warnings.append('Occlusion textures are left out: this runtime has no modo_occlusion.')
        return
    from .cache_folder import root as cache_root
    folder = cache_root() / 'Occlusion'
    folder.mkdir(parents=True, exist_ok=True)
    for name, (rays, distance, spread) in found.items():
        tags = holders.get(name, set())
        for mesh in meshes:
            worn = set(mesh.get('face_materials') or []) | {mesh.get('material', '')}
            if not worn & tags:
                continue
            matrix = placements(mesh)[0]
            normals = point_normals(mesh['vertices'], mesh['faces'])
            points = []
            for p, n in zip(mesh['vertices'], normals):
                points.extend(placed(matrix, p) + turned(matrix, n))
            request = (b'MOC1' + struct.pack('<3I2f', len(blockers) // 9, len(mesh['vertices']), max(1, min(4096, rays)), distance, spread)
                       + blocking + struct.pack('<%df' % len(points), *points))
            key = hashlib.sha256(request).hexdigest()
            answer = folder / (key + '.bin')
            if not answer.is_file():
                asked = folder / (key + '.moc')
                asked.write_bytes(request)
                done = subprocess.run([str(tool), str(asked), str(answer)], env=native.environment(Path(tool).parent), capture_output=True,
                                      text=True, timeout=600, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                asked.unlink(missing_ok=True)
                if done.returncode or not answer.is_file():
                    warnings.append('Occlusion on %s could not be worked out (%s).' % (mesh.get('name'), (done.stderr or done.stdout)[-200:].strip()))
                    continue
            values = struct.unpack('<%df' % len(mesh['vertices']), answer.read_bytes())
            mesh.setdefault('point_attributes', {})[name] = {'kind': 'float', 'values': [[v] for v in values]}
            if len(placements(mesh)) > 1:
                warnings.append('Occlusion on %s is measured where it is first placed, for every place it stands.' % mesh.get('name'))
