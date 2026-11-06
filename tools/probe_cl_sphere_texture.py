# python
"""Command-line test: the artist's steps of 2026-10-30, a sphere, a Dwa material, an image wired into its albedo in
the graph editor; the scene as the plugin hands it to the renderers written out for rendering outside Modo with
MoonRay and XPU2. Writes test-results/sphere-texture/snapshot.pickle and report.json."""
import json
import pathlib
import pickle
import traceback
import lx
import modo

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/sphere-texture'
out.mkdir(parents=True, exist_ok=True)
image = str(root / 'downloads/moonray-example-scenes/scenes/bedroom/scene.png')
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
    report['uv_maps'] = [m.name for m in modo.Mesh(mesh).geometry.vmaps.uvMaps]
    # The material item the assignment made, and its graph with an image in its albedo, as the graph editor writes it.
    materials = [i for i in modo.Scene().items() if properties.is_material(i)]
    report['materials'] = [m.name for m in materials]
    material = materials[-1]
    stored = properties.read(material)
    graph = stored.get('node_graph') or nodes.from_material(material)
    graph['nodes']['img'] = {'type': 'image', 'parameters': {'file': image, 'uv_map': report['uv_maps'][0] if report['uv_maps'] else ''},
                             'inputs': {}, 'position': [-300, 0]}
    graph['nodes'][graph['root']].setdefault('inputs', {})['albedo'] = 'img'
    stored['node_graph'] = graph
    properties.write(material, stored)
    snapshot = host.snapshot()
    report['meshes'] = len(snapshot.get('meshes', []))
    report['snapshot_materials'] = {k: bool(v.get('node_graph')) for k, v in snapshot.get('materials', {}).items()}
    (out / 'snapshot.pickle').write_bytes(pickle.dumps(snapshot, protocol=4))
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
