# python
"""Command line: a mesh's weight, RGB and RGBA maps read by the geometry adapter (vertex_maps.read_natively) against
the reading in Python (read_by_python): the same maps, the same values at each point or corner, the same shapes'
maps (for_faces, all polygons and some), the same vectors (as_vectors), the same MoonRay scene text, and how long
each took. Cubes of 1 and of 60 x 60 x 60 segments, with values set apart on some polygons and maps of every kind,
one map given values on half its points only. Writes test-results/vertex-maps-native.json."""
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
    made = modo.Scene().selectedByType('mesh')[0]
    made.name = name
    return made


def paint(item):
    with item.geometry as geo:
        mesh = geo.internalMesh
        maps = lx.object.MeshMap(mesh.MeshMapAccessor())
        weight = maps.New(lx.symbol.i_VMAP_WEIGHT, 'Heat')
        half = maps.New(lx.symbol.i_VMAP_WEIGHT, 'Half')
        colour = maps.New(lx.symbol.i_VMAP_RGB, 'Paint')
        alpha = maps.New(lx.symbol.i_VMAP_RGBA, 'Tint')
        vector = maps.New(lx.symbol.i_VMAP_RGB, 'Flow')
        point = lx.object.Point(mesh.PointAccessor())
        one, three, four = lx.object.storage('f', 1), lx.object.storage('f', 3), lx.object.storage('f', 4)
        for index in range(mesh.PointCount()):
            point.SelectByIndex(index)
            x, y, z = point.Pos()
            one.set((x + .5,))
            point.SetMapValue(weight, one)
            if index % 2:
                one.set((y * 3.0,))
                point.SetMapValue(half, one)
            three.set((x, y, z))
            point.SetMapValue(colour, three)
            four.set((z, x, y, .25 + x))
            point.SetMapValue(alpha, four)
            three.set((y, z, x))
            point.SetMapValue(vector, three)
        polygon = lx.object.Polygon(mesh.PolygonAccessor())
        # Values set apart: Paint on every seventh polygon, Tint on the first, Heat on the tenth.
        for index in range(0, mesh.PolygonCount(), 7):
            polygon.SelectByIndex(index)
            three.set((1.0, float(index % 3), .5))
            for corner in range(polygon.VertexCount()):
                polygon.SetMapValue(polygon.VertexByIndex(corner), colour, three)
        polygon.SelectByIndex(0)
        four.set((.1, .2, .3, .4))
        for corner in range(polygon.VertexCount()):
            polygon.SetMapValue(polygon.VertexByIndex(corner), alpha, four)
        polygon.SelectByIndex(min(9, mesh.PolygonCount() - 1))
        one.set((7.0,))
        polygon.SetMapValue(polygon.VertexByIndex(1), weight, one)
        return mesh.PointCount(), mesh.PolygonCount()


def plain(maps):
    """Maps as lists, to compare."""
    out = {}
    for name, held in maps.items():
        key = 'points' if 'points' in held else 'corners'
        values = held[key]
        out[name] = {'kind': held['kind'], key: [list(v) for v in values] if key == 'points' else [[list(v) for v in face] for face in values]}
    return out


def shapes(maps, ordinals):
    from moonray_modo import vertex_maps
    points, corners = vertex_maps.for_faces(maps, ordinals)
    return ({k: (v['kind'], [list(x) for x in v['values']]) for k, v in points.items()},
            {k: (v['kind'], [list(x) for x in v['values']]) for k, v in corners.items()})


try:
    from moonray_modo import vertex_maps, host, rdla
    result['adapter'] = vertex_maps._library() is not None
    for segments, name in ((1, 'Small'), (60, 'Heavy')):
        made = cube(segments, name)
        result.setdefault('sizes', {})[name] = paint(made)
        mesh = modo.meshgeometry.MeshProvider.meshFromMeshChannel(made._item, 'deformed')
        start = time.perf_counter()
        native = vertex_maps.read_natively(mesh)
        native_time = time.perf_counter() - start
        start = time.perf_counter()
        python = vertex_maps.read_by_python(mesh)
        python_time = time.perf_counter() - start
        own = {'seconds': {'native': round(native_time, 4), 'python': round(python_time, 4)}, 'read': native is not None}
        if native is not None:
            own['names'] = [sorted(native), sorted(python)]
            own['by'] = {k: ('points' if 'points' in v else 'corners') for k, v in native.items()}
            own['same'] = plain(native) == plain(python)
            if not own['same']:
                own['differ'] = [k for k in python if plain(native).get(k) != plain(python)[k]]
            count = mesh.PolygonCount()
            for label, ordinals in (('all', list(range(count))), ('some', list(range(count - 1, -1, -3))), ('none', [])):
                own.setdefault('for_faces', {})[label] = shapes(native, ordinals) == shapes(python, ordinals)
            kinds = {'Flow': 'vec2', 'Paint': 'vec3'}
            vertex_maps.as_vectors(native, kinds)
            vertex_maps.as_vectors(python, kinds)
            own['as_vectors'] = plain(native) == plain(python)
            own['for_faces_vectors'] = shapes(native, list(range(count - 1, -1, -2))) == shapes(python, list(range(count - 1, -1, -2)))
        result[name] = own
    # The scene as written for MoonRay, with the maps read by the adapter and by Python.
    texts = {}
    held = vertex_maps.read_natively
    for label in ('native', 'python'):
        if label == 'python':
            vertex_maps.read_natively = lambda mesh: None
        try:
            start = time.perf_counter()
            snapshot = host.snapshot()
            result.setdefault('snapshot_seconds', {})[label] = round(time.perf_counter() - start, 3)
            texts[label] = rdla.scene_text(snapshot)
            result.setdefault('map_types', {})[label] = {m['name']: {k: type(v['values']).__name__ for k, v in (m.get('corner_attributes') or {}).items()}
                                                         for m in snapshot['meshes']}
        finally:
            vertex_maps.read_natively = held
    result['scene_text_same'] = texts['native'] == texts['python']
    if not result['scene_text_same']:
        a, b = texts['native'].splitlines(), texts['python'].splitlines()
        result['first_difference'] = next(([i, a[i][:200], b[i][:200]] for i in range(min(len(a), len(b))) if a[i] != b[i]), [len(a), len(b)])
except Exception:
    result['error'] = traceback.format_exc()
(root / 'vertex-maps-native.json').write_text(json.dumps(result, indent=1, default=str))
