# python
"""Command line: where a scene's mesh normals come from. PROBE_SCENE the .lxo. For each mesh: its vertex maps by type
(a vertex normal map among them), its materials' smoothing, and the normals the kit reads (host.snapshot): how many,
how many of zero length. Writes test-results/mesh-normals/report.json."""
import json
import math
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\mesh-normals')
out.mkdir(parents=True, exist_ok=True)
report = {}
try:
    lx.eval('!scene.open {%s} normal' % os.environ['PROBE_SCENE'])
    scene = modo.Scene()
    for mesh in scene.items('mesh'):
        maps = {}
        for vmap in mesh.geometry.vmaps:
            maps.setdefault(str(vmap.map_type), []).append(vmap.name)
        report.setdefault('items', {})[mesh.name] = {'vmaps': maps, 'polygons': mesh.geometry.numPolygons}
    for material in scene.items('advancedMaterial'):
        report.setdefault('materials', {})[material.name] = {k: material.channel(k).get() for k in ('smooth', 'smAngle') if material.channel(k)}
    # Each vertex normal map's values on the first polygons, read as the kit reads maps (MapEvaluate): which hold any.
    from moonray_modo.host import first_map
    for item in scene.items('mesh'):
        names = [v.name for v in item.geometry.vmaps if str(v.map_type) == str(lx.symbol.i_VMAP_NORMAL)]
        mesh = lx.object.Mesh(item.geometry.internalMesh)
        polygons = lx.object.Polygon(mesh.PolygonAccessor())
        for name in names:
            found = first_map(mesh, lx.symbol.i_VMAP_NORMAL, name)
            map_id = found[1] if isinstance(found, tuple) else found
            storage = lx.object.storage('f', 3)
            nonzero = sampled = 0
            first = []
            for index in range(min(200, mesh.PolygonCount())):
                polygons.SelectByIndex(index)
                for corner in range(polygons.VertexCount()):
                    point = polygons.VertexByIndex(corner)
                    ok = polygons.MapEvaluate(map_id, point, storage)
                    value = tuple(round(v, 4) for v in storage.get()) if ok else None
                    sampled += 1
                    nonzero += bool(value and any(value))
                    if len(first) < 3:
                        first.append(value)
            report.setdefault('normal maps', {})['%s / %s' % (item.name, name)] = {'sampled': sampled, 'nonzero': nonzero, 'first': first}
    from moonray_modo import host
    snapshot = host.snapshot()
    for mesh in snapshot.get('meshes', []):
        normals = list(mesh.get('normals') or [])
        zero = sum(1 for n in normals if not math.isfinite(sum(n)) or sum(c * c for c in n) == 0)
        report.setdefault('read', []).append({'name': mesh.get('name'), 'normals': len(normals), 'zero': zero,
                                              'first': normals[:2], 'smooth': mesh.get('smooth'),
                                              'smoothing_angle': mesh.get('smoothing_angle'), 'subdivision': mesh.get('subdivision')})
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
