# python
"""Isolated test: what Modo's mesh map interface offers for reading weight and colour vertex maps, continuous and
discontinuous. A cube is given a weight map with point values, and an RGB map with one polygon's corners set apart."""
import json
import pathlib
import traceback
import lx
import lxifc
import lxu
import modo

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/vertex-map-api'
out.mkdir(parents=True, exist_ok=True)
result = {}
try:
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    item = modo.Scene().selectedByType('mesh')[0]
    with item.geometry as geo:
        mesh = geo.internalMesh
        maps = lx.object.MeshMap(mesh.MeshMapAccessor())
        result['methods'] = sorted(m for m in dir(maps) if not m.startswith('_'))
        weight = maps.New(lx.symbol.i_VMAP_WEIGHT, 'Heat')
        maps.Select(weight)
        result['weight_continuous_before'] = str(maps.IsContinuous()) if hasattr(maps, 'IsContinuous') else 'no method'
        colour = maps.New(lx.symbol.i_VMAP_RGB, 'Paint')
        point = lx.object.Point(mesh.PointAccessor())
        value = lx.object.storage('f', 1)
        for index in range(mesh.PointCount()):
            point.SelectByIndex(index)
            value.set((index / 10.0,))
            point.SetMapValue(weight, value)
        polygon = lx.object.Polygon(mesh.PolygonAccessor())
        polygon.SelectByIndex(0)
        rgb = lx.object.storage('f', 3)
        rgb.set((1.0, 0.0, 0.0))
        for corner in range(polygon.VertexCount()):
            polygon.SetMapValue(polygon.VertexByIndex(corner), colour, rgb)
        maps.Select(weight)
        result['weight_continuous'] = str(maps.IsContinuous()) if hasattr(maps, 'IsContinuous') else 'no method'
        maps.Select(colour)
        result['colour_continuous'] = str(maps.IsContinuous()) if hasattr(maps, 'IsContinuous') else 'no method'
        result['types'] = {'weight': lx.symbol.i_VMAP_WEIGHT, 'rgb': lx.symbol.i_VMAP_RGB, 'rgba': lx.symbol.i_VMAP_RGBA}
        # Reading back: a point's value, and a corner's.
        point.SelectByIndex(0)
        result['point_weight'] = point.MapEvaluate(weight, value) and value.get()
        polygon.SelectByIndex(0)
        result['corner_colour'] = polygon.MapEvaluate(colour, polygon.VertexByIndex(0), rgb) and rgb.get()
        polygon.SelectByIndex(1)
        result['other_corner_colour'] = bool(polygon.MapEvaluate(colour, polygon.VertexByIndex(0), rgb))
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
