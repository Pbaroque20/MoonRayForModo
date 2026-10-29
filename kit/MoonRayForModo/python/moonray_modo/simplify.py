"""A dense polygon mesh made lighter for a realtime preview, by the geometry adapter (bin/MoonRayGeometry.lx,
MR_simplify, meshoptimizer's simplifier): fewer triangles where it is small on screen, within an error the preview
cannot show (moonlightipr_detail says how far), its normals, texture coordinates and materials kept where they part and
its open edges where they are, its shading the full mesh's. For MoonLightIPR's packed meshes (arrays) and for the
polygon meshes the scene text gives MoonRay's realtime previews. Where the adapter has no MR_simplify, nothing is
simplified."""
import ctypes
import os
from array import array
from itertools import chain
from pathlib import Path

_LIBRARY = False
# Simplified meshes kept by what they were made from and how far: a mesh read again unchanged is not simplified again.
_KEPT = {}
# And polygon_mesh's whole result, its lists, by the same: the newest MESHES_KEPT, the oldest let go first.
from collections import OrderedDict
_MESHES = OrderedDict()
MESHES_KEPT = 256


def library():
    """The adapter with MR_simplify, or None: the one the plugin loads (rows.NATIVE), else the kit's own."""
    global _LIBRARY
    if _LIBRARY is False:
        _LIBRARY = None
        from . import rows
        held = rows.NATIVE
        if held is None:
            path = Path(os.environ.get('MOONRAY_MODO_GEOMETRY', '') or Path(__file__).resolve().parents[2] / 'bin/MoonRayGeometry.lx')
            try:
                held = ctypes.CDLL(str(path))
            except OSError:
                held = None
        try:
            if held is not None:
                held.MR_simplify.restype = ctypes.c_int
                held.MR_simplify.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p,
                                             ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_int, ctypes.c_uint32, ctypes.c_float,
                                             ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                             ctypes.c_void_p, ctypes.c_void_p]
                _LIBRARY = held
        except AttributeError:
            _LIBRARY = None
    return _LIBRARY


def _address(held):
    return held.buffer_info()[0] if len(held) else None


def arrays(positions, indices, normals=None, moved=None, uvs=(), materials=None, smooth=True, triangles=0, error=0.01, key=None):
    """A triangle mesh's arrays simplified to about triangles triangles, within error (relative to its size):
    positions and indices (3 a triangle), normals and moved (one a vertex, or none), uvs (each set 2 a triangle
    corner), materials (one a triangle, or none). Returns (positions, normals, moved, indices, uvs, materials, error):
    normals are the full mesh's, given where it had none and is smooth. None where it cannot be simplified. key, where
    given, keeps the result for the same mesh asked for again."""
    held = _KEPT.get(key) if key is not None else None
    if held is not None:
        return held
    # As the Scene cache kept it (cache_folder), the same mesh in the same cut.
    if key is not None:
        from . import cache_folder
        held = cache_folder.kept('Simplified', key)
        if held is not None:
            _KEPT[key] = held
            return held
    native = library()
    count = len(indices) // 3
    if native is None or count < 2 or len(uvs) > 8:
        return None
    corners = 3 * count
    positions = positions if positions.typecode == 'f' else array('f', positions)
    indices = indices if indices.typecode in ('I', 'L') and indices.itemsize == 4 else array('I', indices)
    normals = normals if normals else array('f')
    moved = moved if moved else array('f')
    materials = materials if materials else array('I')
    # The UV sets one after another, by their bytes (walked number by number, they held Python's lock).
    flat_uvs = array('f')
    for values in uvs:
        if isinstance(values, array) and values.typecode == 'f':
            flat_uvs.frombytes(values.tobytes())
        else:
            flat_uvs.extend(values)
    out_positions = array('f', bytes(4 * 3 * corners))
    out_normals = array('f', bytes(4 * 3 * corners)) if (normals or smooth) else array('f')
    out_moved = array('f', bytes(4 * 3 * corners)) if moved else array('f')
    out_indices = array('I', bytes(4 * corners))
    out_uvs = array('f', bytes(4 * 2 * corners * len(uvs))) if uvs else array('f')
    out_materials = array('I', bytes(4 * count)) if materials else array('I')
    vertices, reached = ctypes.c_uint32(0), ctypes.c_float(0)
    made = native.MR_simplify(_address(positions), len(positions) // 3, _address(indices), count, _address(normals), _address(moved),
                              _address(flat_uvs), len(uvs), _address(materials), 1 if smooth else 0, max(1, int(triangles)), float(error),
                              _address(out_positions), _address(out_normals), _address(out_moved), _address(out_indices),
                              _address(out_uvs), _address(out_materials), ctypes.byref(vertices), ctypes.byref(reached))
    if made < 1:
        return None
    v = vertices.value
    result = (out_positions[:3 * v], out_normals[:3 * v] if out_normals else array('f'), out_moved[:3 * v] if out_moved else array('f'),
              out_indices[:3 * made], [out_uvs[s * 2 * corners:s * 2 * corners + 6 * made] for s in range(len(uvs))],
              out_materials[:made] if out_materials else array('I'), reached.value)
    if key is not None:
        _KEPT[key] = result
        from . import cache_folder
        cache_folder.keep('Simplified', key, result)
        if len(_KEPT) > 256:
            _KEPT.pop(next(iter(_KEPT)))
    return result


def _gather(values, width, places):
    """values (width numbers to each) picked by places, flat: each one's bytes joined, not a step of Python a number."""
    size = 4 * width
    # By the adapter where it can: away from Python's lock.
    from .rows import gather
    gathered = gather(values, size, places)
    if gathered is not None:
        return gathered
    data = values.tobytes()
    pieces = [data[i:i + size] for i in range(0, len(data), size)]
    result = array(values.typecode)
    result.frombytes(b''.join(map(pieces.__getitem__, places)))
    return result


def polygon_mesh(mesh, triangles, error):
    """A polygon mesh as the scene text holds it (points, faces, face-varying normals and UVs, named UV sets, face
    materials) simplified to about triangles triangles: the same keys, its faces now triangles. None where it cannot be
    (curves, a mesh with other lists of its own, or no adapter)."""
    from .rows import Rows, Faces, numbers, corners as flat_corners, counts as flat_counts
    from .scene_digest import content
    from .polygons import rules as polygon_rules
    if any(mesh.get(key) for key in ('point_attributes', 'corner_attributes', 'attributes', 'creases', 'corners', 'vertices_close')):
        return None
    vertices, faces = mesh['vertices'], mesh['faces']
    named = sorted((mesh.get('uv_sets') or {}).items())
    sets = ([('', mesh['uvs'])] if mesh.get('uvs') else []) + named
    normals = mesh.get('normals') or []
    tags = mesh.get('face_materials')
    key = ('polygons', content(vertices), content(faces), content(normals) if normals else '',
           tuple(content(values) for _, values in sets), content(tags) if tags is not None else '', int(triangles), round(float(error), 6),
           polygon_rules())
    # The same mesh in the same cut as made before, its very lists: moving a car made each of its dense meshes' arrays
    # again before the cut was found kept (3 s for one), and new lists had the scene text written out anew.
    made = _MESHES.get(key)
    if made is not None:
        _MESHES.move_to_end(key)
        result = dict(mesh, **made)
        if 'normals' not in made:
            result.pop('normals', None)
        return result
    held = flat_corners(faces)
    sizes = flat_counts(faces)
    corner_list = held if held is not None else array('I', chain.from_iterable(faces))
    size_list = sizes if sizes is not None else array('I', map(len, faces))
    if not len(size_list) or min(size_list) < 3:
        return None
    # Each polygon a fan of triangles: its corners' places among the polygon corners (triangles as they are).
    if min(size_list) == max(size_list) == 3:
        fan = array('I', range(len(corner_list)))
        indices = array('I', corner_list)
    else:
        # An n-gon ear-clipped as MoonRay does it (polygons.corners, by the n-gon override as it stands), the rest fanned.
        from .polygons import corners as face_corners, follow
        from .native import ngon_ears
        follow(ngon_ears())
        fan, start = array('I'), 0
        for index, n in enumerate(size_list):
            if n > 4:
                fan.extend(start + k for k in face_corners(faces[index], vertices))
            else:
                for k in range(1, n - 1):
                    fan.extend((start, start + k, start + k + 1))
            start += n
        indices = array('I', (corner_list[c] for c in fan))
    whole = len(fan) == len(corner_list)
    positions = numbers(vertices, 3) or array('f', chain.from_iterable(vertices))
    uvs = []
    for _, values in sets:
        flat = numbers(values, 2) or array('f', chain.from_iterable(values))
        uvs.append(flat if whole else _gather(flat, 2, fan))
    # Face-varying normals: each triangle corner a vertex of its own, with its normal.
    if normals:
        flat_normals = numbers(normals, 3) or array('f', chain.from_iterable(normals))
        positions = _gather(positions, 3, indices)
        normal_values = flat_normals if whole else _gather(flat_normals, 3, fan)
        indices = array('I', range(len(fan)))
    else:
        normal_values = None
    names, materials = [], None
    if tags is not None:
        names = sorted(set(tags))
        place = {tag: i for i, tag in enumerate(names)}
        materials = array('I', (place[tag] for tag, n in zip(tags, size_list) for _ in range(n - 2)))
    made = arrays(positions, indices, normal_values, None, uvs, materials, bool(mesh.get('smooth', True)), triangles, error, key)
    if made is None:
        return None
    out_positions, out_normals, _, out_indices, out_uvs, out_materials, _ = made
    count = len(out_indices) // 3
    result = dict(mesh, vertices=Rows(out_positions, 3, 'simplified-v:%x' % hash(key)),
                  faces=Faces(out_indices, array('I', [3] * count), 'simplified-f:%x' % hash(key)))
    # Normals and UVs go per face corner, as the scene text holds them.
    if len(out_normals):
        result['normals'] = Rows(_gather(out_normals, 3, out_indices), 3, 'simplified-n:%x' % hash(key))
    else:
        result.pop('normals', None)
    at = 0
    if mesh.get('uvs'):
        result['uvs'] = Rows(out_uvs[0], 2, 'simplified-u:%x' % hash(key))
        at = 1
    if named:
        result['uv_sets'] = {name: Rows(out_uvs[at + i], 2, 'simplified-u%d:%x' % (i, hash(key))) for i, (name, _) in enumerate(named)}
    if tags is not None:
        result['face_materials'] = [names[m] for m in out_materials]
    _MESHES[key] = {name: result[name] for name in ('vertices', 'faces', 'normals', 'uvs', 'uv_sets', 'face_materials') if name in result}
    while len(_MESHES) > MESHES_KEPT:
        _MESHES.popitem(last=False)
    return result
