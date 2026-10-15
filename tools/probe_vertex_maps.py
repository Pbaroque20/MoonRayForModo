# python
"""Isolated GUI test: a mesh's weight and colour vertex maps as the plugin reads them for MoonRay.

A cube gets a weight map with a value for each point, an RGB map with values for its points and, on one face, values
set apart (Modo's discontinuous values), and an RGBA map. The scene is read as the plugin reads it for a render, and
what each mesh carries is written down, with the MoonRay scene text for the maps. A cube of 6 x 6 x 6 segments,
heavy enough to be read by the geometry adapter, is read the same way."""
import json
import os
import pathlib
import traceback
import lx
import lxifc
import modo

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/vertex-maps-gui'
out.mkdir(parents=True, exist_ok=True)
result = {}


def cube(segments):
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    for axis in 'XYZ':
        lx.eval('tool.attr prim.cube segments%s %d' % (axis, segments))
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    return modo.Scene().selectedByType('mesh')[0]


def paint(item):
    with item.geometry as geo:
        mesh = geo.internalMesh
        maps = lx.object.MeshMap(mesh.MeshMapAccessor())
        weight = maps.New(lx.symbol.i_VMAP_WEIGHT, 'Heat')
        colour = maps.New(lx.symbol.i_VMAP_RGB, 'Paint')
        alpha = maps.New(lx.symbol.i_VMAP_RGBA, 'Tint')
        point = lx.object.Point(mesh.PointAccessor())
        one, three, four = lx.object.storage('f', 1), lx.object.storage('f', 3), lx.object.storage('f', 4)
        for index in range(mesh.PointCount()):
            point.SelectByIndex(index)
            x, y, z = point.Pos()
            one.set((x + .5,))
            point.SetMapValue(weight, one)
            three.set((0.0, 1.0, 0.0))
            point.SetMapValue(colour, three)
            four.set((0.0, 0.0, 1.0, .5))
            point.SetMapValue(alpha, four)
        polygon = lx.object.Polygon(mesh.PolygonAccessor())
        polygon.SelectByIndex(0)
        three.set((1.0, 0.0, 0.0))
        for corner in range(polygon.VertexCount()):
            polygon.SetMapValue(polygon.VertexByIndex(corner), colour, three)
        return mesh.PointCount(), mesh.PolygonCount()


try:
    light = cube(1)
    light.name = 'Small'
    result['small'] = paint(light)
    heavy = cube(30)
    heavy.name = 'Heavy'
    result['heavy'] = paint(heavy)
    from moonray_modo import host, rdla, vertex_maps
    for made in (light, heavy):
        evaluated = modo.meshgeometry.MeshProvider.meshFromMeshChannel(made._item, 'deformed')
        listed = vertex_maps.listed(evaluated)
        result.setdefault('debug', {})[made.name] = {'listed': listed, 'polygons': evaluated.PolygonCount(),
                                                     'apart': {name: vertex_maps.set_apart(evaluated, ident) for name, kind, ident in listed}}
        # Counting the discontinuous values of Paint some other ways.
        accessor = lx.object.MeshMap(evaluated.MeshMapAccessor())
        for name, kind, ident in listed:
            if name != 'Paint':
                continue
            accessor.Select(ident)
            counted = []
            class Count(lxifc.Visitor):
                def vis_Evaluate(self):
                    counted.append(1)
            for method in ('EnumerateDiscontinuous', 'EnumerateContinuous'):
                counted.clear()
                try:
                    getattr(accessor, method)(Count())
                    result['debug'][made.name][method] = len(counted)
                except Exception as exc:
                    result['debug'][made.name][method] = repr(exc)
    snapshot = host.snapshot()
    for mesh in snapshot['meshes']:
        result.setdefault('meshes', []).append({
            'name': mesh['name'], 'faces': len(mesh['faces']), 'points': len(mesh['vertices']),
            'point_maps': {k: (v['kind'], len(v['values']), v['values'][:2]) for k, v in (mesh.get('point_attributes') or {}).items()},
            'corner_maps': {k: (v['kind'], len(v['values']), sorted({tuple(c) for c in v['values']})) for k, v in (mesh.get('corner_attributes') or {}).items()}})
    # Which faces got the red corners, and whether that is the polygon painted (polygon 0, by its points).
    for mesh in snapshot['meshes']:
        held = (mesh.get('corner_attributes') or {}).get('Paint')
        if not held:
            continue
        corner, red = 0, []
        for index, face in enumerate(mesh['faces']):
            values = held['values'][corner:corner + len(face)]
            if any(v[0] > .5 for v in values):
                red.append((index, all(v[0] > .5 for v in values)))
            corner += len(face)
        made = light if mesh['name'] == 'Small' else heavy
        geometry = modo.meshgeometry.MeshProvider.meshFromMeshChannel(made._item, 'deformed')
        polygon = lx.object.Polygon(geometry.PolygonAccessor())
        polygon.SelectByIndex(0)
        point = lx.object.Point(geometry.PointAccessor())
        painted = set()
        for c in range(polygon.VertexCount()):
            point.Select(polygon.VertexByIndex(c))
            painted.add(tuple(round(v, 4) for v in point.Pos()))
        faces = [sorted(tuple(round(v, 4) for v in mesh['vertices'][i]) for i in mesh['faces'][index]) for index, _ in red]
        result.setdefault('red', {})[mesh['name']] = {'faces': red, 'is_polygon_0': [f == sorted(painted) for f in faces]}
    text = rdla.scene_text(snapshot)
    result['userdata'] = [line.strip() for line in text.splitlines() if '_key' in line or '"rate"' in line][:24]
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
