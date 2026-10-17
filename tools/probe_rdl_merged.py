# python
"""Isolated GUI test: an instancer with more copies than are made into Modo instances; the rest come in merged into meshes.

The plan of test-results/rdl-merged/plan.json (400 copies of a coloured box in a grid, planned outside Modo with the
limit at 100, each copy carrying its own number) is applied. Counted are the instances and the merged meshes made, the
merged mesh's points, faces and maps; then the scene is captured as for a render and written out for MoonRay
(test-results/rdl-merged/imported.rdla)."""
import json
import pathlib
import traceback
import lx
import modo

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/rdl-merged'
result = {}

try:
    from moonray_modo import host, rdl_import, rdla
    lx.eval('scene.new')
    scene = modo.Scene()
    data = json.loads((out / 'plan.json').read_text())
    result['import'] = rdl_import.apply(data)
    meshes = list(scene.items('mesh'))
    result['instances'] = len(list(scene.items('meshInst')))
    merged = [m for m in meshes if 'merged' in m.name]
    result['merged'] = [{'name': m.name, 'points': m.geometry.vertices.__len__(), 'faces': m.geometry.polygons.__len__(),
                         'maps': sorted(v.name for v in m.geometry.vmaps)} for m in merged]
    snapshot = host.snapshot()
    captured = [m for m in snapshot['meshes'] if 'merged' in m.get('name', '')]
    result['captured'] = [{'name': m['name'], 'points': len(m['vertices']), 'attributes': sorted(m.get('face_attributes', {}) or m.get('point_attributes', {}) or {})}
                          for m in captured]
    (out / 'imported.rdla').write_text(rdla.scene_text(snapshot, 320, 180, 2, 0.0, str(out / 'imported.exr')))
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
