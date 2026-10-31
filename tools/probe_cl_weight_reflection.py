# python
"""Command-line test: a weight map driving a material's reflections, as an artist asked for a cornea. A sphere weighted 1
on one side and 0 on the other, read by name through an AttributeMap into DwaBaseMaterial's specular or roughness. The
scenes as the plugin hands them to the renderers are written for rendering outside Modo. Writes
test-results/weight-reflection/<input>.pickle and report.json."""
import json
import pathlib
import pickle
import traceback
import lx
import modo

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/weight-reflection'
out.mkdir(parents=True, exist_ok=True)
report = {}
try:
    from moonray_modo import host, nodes, properties
    lx.eval('scene.new')
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    mesh = [i for i in modo.Scene().items('mesh')][-1]
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('moonray.library.assign %s' % properties.encode({'shader': 'DwaBaseMaterial', 'parameters': {}}))
    material = next(i for i in modo.Scene().items() if properties.is_material(i) and properties.read(i).get('native_shader'))
    geometry = modo.Mesh(mesh).geometry
    weights = geometry.vmaps.addWeightMap('Cornea')
    for vertex in geometry.vertices:
        weights[vertex.index] = 1.0 if vertex.position[0] > 0 else 0.0
    geometry.setMeshEdits()
    report['weighted'] = sum(1 for v in geometry.vertices if v.position[0] > 0)
    for target in ('specular', 'roughness'):
        graph = nodes.new()
        graph['nodes']['surface']['parameters'].update(albedo=[0, 0, 0], roughness=.05)
        graph['nodes']['cornea'] = {'type': 'AttributeMap', 'parameters': {'map_type': 0, 'primitive_attribute_name': 'Cornea', 'primitive_attribute_type': 0},
                                    'inputs': {}, 'position': [-300, 0]}
        graph['nodes']['surface']['inputs'][target] = 'cornea'
        report[target + ' connectable'] = nodes.connectable('DwaBaseMaterial', target)
        settings = properties.read(material)
        settings.update(node_graph=nodes.validate(graph), node_override=True)
        lx.eval('moonray.material.applyGraph {%s} %s' % (material.id, properties.encode(settings)))
        snapshot = host.snapshot()
        (out / (target + '.pickle')).write_bytes(pickle.dumps(snapshot, protocol=4))
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
