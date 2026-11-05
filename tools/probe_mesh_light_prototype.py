# python
"""Command line: how a Modo Mesh Light names its Prototype mesh (Properties > Prototype, light.mesh), for the kit to make
that mesh emit. A cube made, a Mesh Light made with the cube as its prototype; then every item graph the light is linked
through, its channels, what light.mesh says, and whether the render cache has a surface for the light. Writes
test-results/mesh-light-prototype/report.json."""
import json
import pathlib
import traceback
import lx
import lxu
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\mesh-light-prototype')
out.mkdir(parents=True, exist_ok=True)
result = {}


def attempt(name, fn):
    try:
        result[name] = fn()
    except Exception:
        result[name] = 'error: ' + traceback.format_exc()[-900:]


try:
    scene = modo.Scene()
    mesh = scene.addMesh('Panel')
    with mesh.geometry as geo:
        points = [geo.vertices.new(p) for p in ((-1, 0, -1), (1, 0, -1), (1, 0, 1), (-1, 0, 1))]
        geo.polygons.new(points)
    mesh.position.set((0.0, 2.0, 0.0))
    lx.eval('item.create meshLight')
    light = next(i for i in scene.items('meshLight', superType=False))
    result['light'] = [light.type, light.id, light.name]
    lx.eval('select.item {%s} set' % light.id)
    attempt('light.mesh set', lambda: [lx.eval('light.mesh mesh:{%s}' % mesh.id), 'ok'][-1])
    attempt('light.mesh ?', lambda: lx.eval('light.mesh mesh:?'))

    def graphs():
        sc = lx.object.Scene(scene)
        found = {}
        for index in range(sc.GraphCount()):
            graph = sc.GraphByIndex(index)
            name = graph.Name()
            try:
                item_graph = lx.object.ItemGraph(graph)
            except Exception:
                continue
            item = lx.object.Item(light)
            forward = [lx.object.Item(item_graph.FwdByIndex(item, k)).Ident() for k in range(item_graph.FwdCount(item))]
            reverse = [lx.object.Item(item_graph.RevByIndex(item, k)).Ident() for k in range(item_graph.RevCount(item))]
            if forward or reverse:
                found[name] = {'forward': forward, 'reverse': reverse}
        return found
    attempt('graphs', graphs)
    result['mesh_id'] = mesh.id

    def channels():
        item = lx.object.Item(light)
        names = [item.ChannelName(k) for k in range(item.ChannelCount())]
        return {n: str(light.channel(n).get()) for n in names if not n.startswith('wpos') and not n.startswith('wrot')}
    attempt('channels', channels)
    attempt('superTypes', lambda: [lx.service.Scene().ItemTypeName(t) for t in [lx.object.Item(light).Type()]])

    def cache():
        from moonray_modo import evaluated
        data = evaluated.capture(lx.service.Selection().GetTime())
        return [(s.get('source_item'), s.get('name'), len(s.get('faces') or s.get('segments') or [])) for s in data.get('surfaces', [])]
    attempt('render_cache', cache)

    def snapshot():
        from moonray_modo import host
        shot = host.snapshot()
        return {'meshes': [m.get('name') for m in shot.get('meshes') or []],
                'lights': [(l.get('type'), l.get('name')) for l in shot.get('lights') or []],
                'warnings': shot.get('warnings')}
    attempt('snapshot', snapshot)
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=2, default=str))
