# python
"""Command line: an edited mesh's surfaces read directly (the adapter's MR_mesh_surfaces) against Modo's render cache's,
mesh by mesh, on MOONRAY_PROBE_SCENE: for each material and part, its triangles compared as sets of corners (point,
normal, UVs, each to 1e-5), with the UV sets in the mesh's order of maps. MOONRAY_PROBE_DISPLACED=1 compares with the
displaced render cache (MoonRay's readings). Writes test-results/geometry-cache/surfaces-<label>.json."""
import ctypes
import json
import os
import pathlib
import struct
import tempfile
import traceback
from array import array
import lx
import modo

label = os.environ.get('MOONRAY_PROBE_LABEL', 'scene')
out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\geometry-cache') / ('surfaces-%s.json' % label)
result = {}


def save():
    out.write_text(json.dumps(result, indent=1, default=str), encoding='utf-8')


def read(data):
    assert data[:4] == b'MRS1'
    at = 4

    def i32():
        nonlocal at
        v, = struct.unpack_from('<i', data, at); at += 4
        return v

    def text():
        nonlocal at
        n = i32(); s = data[at:at + n].decode('utf-8', 'replace'); at += n
        return s

    def floats(n):
        nonlocal at
        a = array('f'); a.frombytes(data[at:at + 4 * n]); at += 4 * n
        return a
    uv_names = [text() for _ in range(i32())]
    surfaces = {}
    for _ in range(i32()):
        material, part, corners = text(), text(), i32()
        positions, normals = floats(corners * 3), floats(corners * 3)
        uvs = [floats(corners * 2) for _ in uv_names]
        surfaces[(material, part)] = (corners, positions, normals, uvs)
    return uv_names, surfaces


def r5(v):
    return tuple(round(float(x), 5) for x in v)


try:
    lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    scene = modo.Scene()
    from moonray_modo import evaluated
    bridge = evaluated._load()
    call = bridge.MR_mesh_surfaces
    call.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    call.restype = ctypes.c_char_p
    data = evaluated.capture(lx.service.Selection().GetTime(), displaced=os.environ.get('MOONRAY_PROBE_DISPLACED') == '1', kept=False)
    by_item = {}
    for proto in data['prototypes'].values():
        by_item.setdefault(proto.get('item'), []).append(proto)
    report = []
    folder = tempfile.mkdtemp(prefix='MoonRay-surfaces-')
    for item in scene.items('mesh', superType=False):
        protos = by_item.get(item.id)
        if not protos:
            continue
        entry = {'name': item.name, 'polygons': item.geometry.numPolygons}
        mesh = modo.meshgeometry.MeshProvider.meshFromMeshChannel(lx.object.Item(item), 'deformed', 0.0)
        path = os.path.join(folder, 'mesh.bin')
        by_part = int(any(proto.get('part') for proto in protos))
        error = call(mesh.__peekobj__(), path.encode('utf-8'), by_part)
        if error:
            entry['refused'] = error.decode()
            report.append(entry)
            continue
        uv_names, mine = read(pathlib.Path(path).read_bytes())
        entry['uv_maps'] = uv_names
        entry['keys_mine'] = sorted(map(list, mine))[:4]
        entry['keys_modo'] = sorted([proto.get('material'), proto.get('part')] for proto in protos)[:4]
        same = total = 0
        surfaces_ok = True
        for proto in protos:
            key = (proto.get('material') or '', proto.get('part') or '')
            got = mine.get(key)
            modo_tris = []
            for segment in proto['segments']:
                verts = list(segment['vertices'])
                normals = list(segment['normals']) if segment['normals'] else []
                uv_sets = [list(s) for s in segment['uv_sets']]
                c = 0
                for face in segment['faces']:
                    face = list(face)
                    tri = []
                    for k, i in enumerate(face):
                        tri.append((r5(verts[i]), r5(normals[c + k]) if normals else None, tuple(r5(s[c + k]) for s in uv_sets)))
                    c += len(face)
                    modo_tris.append(tuple(sorted(tri)))
            total += len(modo_tris)
            if got is None:
                surfaces_ok = False
                continue
            corners, positions, normals, uvs = got
            uv_count = len(proto['segments'][0]['uv_sets']) if proto['segments'] else 0
            entry.setdefault('uv_sets', set()).add(uv_count)
            import itertools

            def matched(chosen, with_uvs=True):
                mine_count = {}
                for t in range(corners // 3):
                    tri = []
                    for k in range(3):
                        c = 3 * t + k
                        tri.append((r5(positions[3 * c:3 * c + 3]), r5(normals[3 * c:3 * c + 3]),
                                    tuple(r5(uvs[u][2 * c:2 * c + 2]) for u in chosen) if with_uvs else ()))
                    tri = tuple(sorted(tri))
                    mine_count[tri] = mine_count.get(tri, 0) + 1
                hits = 0
                for tri in modo_tris:
                    if not with_uvs:
                        tri = tuple(sorted((p, n, ()) for p, n, _ in tri))
                    if mine_count.get(tri):
                        mine_count[tri] -= 1
                        hits += 1
                return hits
            best = (-1, None)
            # The adapter gives the maps in the render cache's order (by name); MOONRAY_PROBE_UV_ORDERS=1 tries every order.
            orders = itertools.permutations(range(len(uvs)), uv_count) if os.environ.get('MOONRAY_PROBE_UV_ORDERS') == '1' else [tuple(range(uv_count))]
            for chosen in orders:
                best = max(best, (matched(chosen), chosen))
                if best[0] == len(modo_tris):
                    break
            same += best[0]
            entry.setdefault('uv_order', []).append([uv_names[u] for u in best[1]] if best[1] is not None else None)
            entry['same_without_uvs'] = entry.get('same_without_uvs', 0) + matched((), False)
        entry.update(triangles=total, same=same, surfaces_found=surfaces_ok,
                     uv_sets=sorted(entry.get('uv_sets', ())))
        report.append(entry)
    report.sort(key=lambda e: (e.get('same', 0) == e.get('triangles', 0), -e['polygons']))
    result['meshes'] = report
    result['summary'] = {'meshes': len(report), 'exact': sum(1 for e in report if e.get('triangles') and e.get('same') == e.get('triangles')),
                         'refused': sum(1 for e in report if 'refused' in e)}
except Exception:
    result['error'] = traceback.format_exc()
save()
