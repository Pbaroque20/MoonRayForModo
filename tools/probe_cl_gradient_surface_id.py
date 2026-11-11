# python
"""Command-line: Modo's Gradient on Surface ID as the kit hands it on: three cubes (separate meshes, one material) under
a Gradient on Surface ID; whether the layer is read, and each cube's number. Writes
test-results/gradient-surface-id/report.json."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\gradient-surface-id')
out.mkdir(parents=True, exist_ok=True)
report = {}
try:
    from moonray_modo import host
    from moonray_modo.procedurals import VARIATION_MAP
    lx.eval('scene.new')
    scene = modo.Scene()
    for name, x in (('CubeA', -2.0), ('CubeB', 0.0), ('CubeC', 2.0)):
        mesh = scene.addMesh(name)
        with mesh.geometry as geo:
            c = [geo.vertices.new((x + a, b, d)) for a in (-.5, .5) for b in (-.5, .5) for d in (-.5, .5)]
            for face in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
                geo.polygons.new([c[i] for i in face])
    material = next(i for i in scene.items('advancedMaterial'))
    scene.select(material)
    lx.eval('shader.create gradient')
    gradient = next(i for i in scene.items('gradient'))
    gradient.channel('effect').set('lumiColor')
    gradient.channel('param').set('surfaceID')
    snapshot = host.snapshot()
    report['warnings'] = [w for w in snapshot.get('warnings', []) if 'radient' in w or 'urface' in w]
    report['layers'] = [(l.get('kind'), (l.get('gradient') or {}).get('vmap')) for m in snapshot['materials'].values() for l in (m.get('layers') or [])]
    report['numbers'] = {m['name']: ((m.get('point_attributes') or {}).get(VARIATION_MAP) or {}).get('values', [[None]])[0][0] for m in snapshot['meshes']}
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
