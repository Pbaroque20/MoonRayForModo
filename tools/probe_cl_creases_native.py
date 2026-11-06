# python
"""Command line: a subdivided mesh's creases read by the geometry adapter (host.creases_natively) against the reading
in Python: the same edges in the same order, the same points, the same sharpness, the same MoonRay scene text, and
how long each took. Cubes of 1 and of 60 x 60 x 60 segments turned to subdivision surfaces (Catmull-Clark), with a
Subdivision weight on every fifth edge (some above 100%) and every eleventh point. Writes
test-results/creases-native.json."""
import json
import pathlib
import time
import traceback
import lx
import modo

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results')
result = {}


def cube(segments, name):
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    for axis in 'XYZ':
        lx.eval('tool.attr prim.cube segments%s %d' % (axis, segments))
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('select.typeFrom polygon')
    lx.eval('select.all')
    lx.eval('poly.convert face psubdiv true')
    lx.eval('select.typeFrom item')
    made = modo.Scene().selectedByType('mesh')[0]
    made.name = name
    return made


def weigh(item):
    with item.geometry as geo:
        mesh = geo.internalMesh
        maps = lx.object.MeshMap(mesh.MeshMapAccessor())
        weights = maps.New(lx.symbol.i_VMAP_SUBDIV, 'Subdivision')
        point = lx.object.Point(mesh.PointAccessor())
        polygon = lx.object.Polygon(mesh.PolygonAccessor())
        edge = lx.object.Edge(mesh.EdgeAccessor())
        one = lx.object.storage('f', 1)
        done, counted = set(), 0
        for index in range(mesh.PolygonCount()):
            polygon.SelectByIndex(index)
            ids = [polygon.VertexByIndex(k) for k in range(polygon.VertexCount())]
            for a, b in zip(ids, ids[1:] + ids[:1]):
                key = frozenset((a, b))
                if key in done:
                    continue
                done.add(key)
                counted += 1
                if counted % 5 == 0:
                    edge.SelectEndpoints(a, b)
                    one.set(((counted % 13) / 10.0,))
                    edge.SetMapValue(weights, one)
        for index in range(0, mesh.PointCount(), 11):
            point.SelectByIndex(index)
            one.set((.05 * (index % 30),))
            point.SetMapValue(weights, one)
        return mesh.PointCount(), mesh.PolygonCount(), counted


try:
    from moonray_modo import host, rdla, mesh_reader
    for segments, name in ((1, 'Small'), (60, 'Heavy')):
        made = cube(segments, name)
        result.setdefault('sizes', {})[name] = weigh(made)
        mesh = modo.meshgeometry.MeshProvider.meshFromMeshChannel(made._item, 'deformed')
        read = mesh_reader.read(mesh)
        faces = host.mesh_faces(read) if hasattr(host, 'mesh_faces') else None
        listed = []
        polygon = lx.object.Polygon(mesh.PolygonAccessor())
        point = lx.object.Point(mesh.PointAccessor())
        index_of = {}
        for p in range(mesh.PointCount()):
            point.SelectByIndex(p)
            index_of[point.ID()] = p
        for index in range(mesh.PolygonCount()):
            polygon.SelectByIndex(index)
            listed.append([index_of[polygon.VertexByIndex(k)] for k in range(polygon.VertexCount())])
        own = {}
        map_id = host.first_map(mesh, lx.symbol.i_VMAP_SUBDIV)
        held = host.creases_natively
        for label, faces_given in (('lists', listed), ('some', listed[::3])):
            start = time.perf_counter()
            native = host.creases_natively(mesh, map_id, faces_given)
            native_time = time.perf_counter() - start
            host.creases_natively = lambda *a: None
            try:
                start = time.perf_counter()
                python = host.subdivision_creases(mesh, faces_given)
                python_time = time.perf_counter() - start
            finally:
                host.creases_natively = held
            own[label] = {'seconds': {'native': round(native_time, 4), 'python': round(python_time, 4)},
                          'counts': [len(native[0]), len(native[1])] if native else None,
                          'same': native is not None and [list(map(list, native[0])), list(map(list, native[1]))] == [list(map(list, python[0])), list(map(list, python[1]))]}
        result[name] = own
    texts = {}
    held = host.creases_natively
    # Python first: a second snapshot may reuse what the first read.
    for label in ('python', 'native'):
        if label == 'python':
            host.creases_natively = lambda *a: None
        try:
            start = time.perf_counter()
            snapshot = host.snapshot()
            result.setdefault('snapshot_seconds', {})[label] = round(time.perf_counter() - start, 3)
            result.setdefault('mesh_creases', {})[label] = {m['name']: [len(m.get('creases') or []), len(m.get('corners') or []), bool(m.get('subdivision'))] for m in snapshot['meshes']}
            texts[label] = rdla.scene_text(snapshot)
        finally:
            host.creases_natively = held
    result['scene_text_same'] = texts['native'] == texts['python']
except Exception:
    result['error'] = traceback.format_exc()
(root / 'creases-native.json').write_text(json.dumps(result, indent=1, default=str))
