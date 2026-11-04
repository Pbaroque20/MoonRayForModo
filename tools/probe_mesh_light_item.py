# python
"""How Modo holds a Mesh Light item's geometry, for the kit to read it (a tester's mesh lights lit nothing: host.py skipped
the meshLight type). Makes a mesh light, makes it the active layer, builds a cube into it, and asks the layer service and
the render cache for its polygons. Writes test-results/mesh-light-item/report.json."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\mesh-light-item')
out.mkdir(parents=True, exist_ok=True)
result = {}


def attempt(name, fn):
    try:
        result[name] = fn()
    except Exception:
        result[name] = 'error: ' + traceback.format_exc().strip().splitlines()[-1]


try:
    scene = modo.Scene()
    lx.eval('item.create meshLight')
    light = scene.selected[0]
    result['light'] = [light.type, light.id]
    attempt('select', lambda: [lx.eval('select.item %s set' % light.id), 'ok'][-1])
    attempt('build', lambda: [lx.eval('tool.set prim.cube on'), lx.eval('tool.apply'), lx.eval('tool.set prim.cube off'), 'ok'][-1])
    attempt('layers', lambda: [(lx.eval('query layerservice layer.name ? %d' % i), lx.eval('query layerservice layer.id ? %d' % i))
                               for i in range(lx.eval('query layerservice layer.N ? all'))])
    attempt('meshes', lambda: [(i.type, i.name, len(i.geometry.polygons)) for i in scene.items('mesh', superType=False)])
    attempt('every_item', lambda: [(i.type, i.name) for i in scene.items()][:12])
    def layer_polys():
        found = {}
        n = lx.eval('query layerservice layer.N ? all')
        for i in range(n):
            lx.eval('query layerservice layer.index ? %d' % i)
            found[lx.eval('query layerservice layer.name ? %d' % i)] = lx.eval('query layerservice poly.N ? all')
        return found
    attempt('layer_polys', layer_polys)
    # A Mesh Light item's own tag: does Modo say which mesh it shows?
    attempt('light_links', lambda: [(g, [x.name for x in light.itemGraph(g).forward()], [x.name for x in light.itemGraph(g).reverse()])
                                    for g in ('meshInst', 'shadeLoc', 'source', 'deformers', 'chanMods', 'parent')
                                    if True])
    def cache():
        from moonray_modo import evaluated
        got = evaluated.capture(lx.service.Selection().GetTime())
        return {'surfaces': str(got.get('surfaces'))[:400], 'items': sorted({str(p.get('item')) for p in (got.get('prototypes') or {}).values()})}
    attempt('render_cache', cache)
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=2, default=str))
