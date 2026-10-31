# python
"""A Weight Map Texture layer on a MoonRay material, as an artist asked for a cornea: a sphere weighted 1 on one side and 0
on the other, a DwaBaseMaterial with a black albedo, the layer above it in the Shader Tree driving reflection amount or
roughness. The scenes as the plugin hands them to the renderers are kept. Writes test-results/weight-layer-dwa/."""
import json
import pathlib
import pickle
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\weight-layer-dwa')
out.mkdir(parents=True, exist_ok=True)
report = {}
try:
    from moonray_modo import host, properties
    lx.eval('scene.new')
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    scene = modo.Scene()
    mesh = [i for i in scene.items('mesh')][-1]
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('moonray.library.assign %s' % properties.encode({'shader': 'DwaBaseMaterial', 'parameters': {'albedo': [0, 0, 0], 'roughness': .05}}))
    material = next(i for i in scene.items() if properties.is_material(i) and properties.read(i).get('native_shader'))
    geometry = modo.Mesh(mesh).geometry
    weights = geometry.vmaps.addWeightMap('Cornea')
    for vertex in geometry.vertices:
        weights[vertex.index] = 1.0 if vertex.position[0] > 0 else 0.0
    geometry.setMeshEdits()
    scene.select(material)
    lx.eval('shader.create vmapTexture')
    layer = next(i for i in scene.items('vmapTexture'))
    layer.channel('vmap').set('Cornea')
    for effect in ('specAmount', 'rough'):
        layer.channel('effect').set(effect)
        report[effect + ' effect'] = layer.channel('effect').get()
        snapshot = host.snapshot()
        report[effect + ' warnings'] = snapshot.get('warnings')
        report[effect + ' layers'] = [[l.get('kind'), l.get('effect'), (l.get('gradient') or {}).get('vmap')] for m in snapshot['materials'].values() for l in (m.get('layers') or [])]
        (out / (effect + '.pickle')).write_bytes(pickle.dumps(snapshot, protocol=4))
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
