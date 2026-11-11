# python
"""Command-line: Modo's Variation Texture by Item: two cubes wearing one material whose luminous colour is a Variation
Texture (source Item), captured as the kit hands it on: whether the layer is read, and each cube's random number (the
weight its points carry); and a source the kit does not follow yet (Mesh Part), named in a notice. Writes
test-results/variation-item/report.json and item.pickle."""
import json
import pathlib
import pickle
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\variation-item')
out.mkdir(parents=True, exist_ok=True)
report = {}
try:
    from moonray_modo import host
    lx.eval('scene.new')
    scene = modo.Scene()
    for name, x in (('CubeA', -1.5), ('CubeB', 1.5)):
        mesh = scene.addMesh(name)
        geometry = modo.Mesh(mesh).geometry
        corners = [geometry.vertices.new((x + a - .5, b - .5, c - .5)) for a in (0, 1) for b in (0, 1) for c in (0, 1)]
        for face in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
            geometry.polygons.new([corners[i] for i in face])
        geometry.setMeshEdits()
    material = next(i for i in scene.items('advancedMaterial'))
    material.channel('radiance').set(1)
    scene.select(material)
    lx.eval('shader.create variationTexture')
    layer = next(i for i in scene.items('variationTexture'))
    layer.channel('effect').set('lumiColor')
    layer.channel('type').set('item')
    snapshot = host.snapshot()
    report['item'] = {'warnings': [w for w in snapshot.get('warnings', []) if 'ariation' in w],
                      'layers': [l.get('kind') for m in snapshot['materials'].values() for l in (m.get('layers') or [])],
                      'numbers': {m['name']: ((m.get('point_attributes') or {}).get('__modo_variation_item') or {}).get('values', [[None]])[0][0]
                                  for m in snapshot['meshes']}}
    (out / 'item.pickle').write_bytes(pickle.dumps(snapshot, protocol=4))
    layer.channel('type').set('meshPart')
    snapshot = host.snapshot()
    report['meshPart'] = {'warnings': [w for w in snapshot.get('warnings', []) if 'ariation' in w]}
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
