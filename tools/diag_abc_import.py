# python
"""Run in Modo's command line with: @{C:/Users/Raphael Tobar/MoonRayForModo/tools/diag_abc_import.py}
Read-only: why a mesh from Modo's Alembic import is not read from its file by the kit (extra_geometry.imported_alembic).
Changes nothing in the scene. Writes test-results/cl-export/diag-abc-import.json and says where in the Event Log."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\cl-export')
out.mkdir(parents=True, exist_ok=True)
result = {}
try:
    from moonray_modo import extra_geometry, native
    scene = modo.Scene()
    fps = float(scene.fps)
    frame = round(lx.service.Selection().GetTime() * fps)
    result.update(frame=frame, fps=fps, switch=native.alembic_import(), runtime=str(native.default_runtime()),
                  kit=str(pathlib.Path(extra_geometry.__file__).parent))
    result['item_types'] = sorted({item.type for item in scene.items()})
    result['abc_items'] = [(i.name, i.type, i.id, i.parent.name if i.parent else None) for i in scene.items()
                           if 'lembic' in i.type or 'ABC' in i.type or i.name in ('xf',) or i.name.startswith('xf')]
    deformers = []
    for deformer in scene.items('ABCStreamingDeformer'):
        entry = {'name': deformer.name, 'id': deformer.id}
        try:
            entry['enable'] = deformer.channel('enable').get()
            entry['targets'] = [(t.name, t.type, t.id, t.parent.name if t.parent else None,
                                 [(s.name, s.type) for s in (t.parent.children() if t.parent else [])])
                                for t in deformer.itemGraph('deformers').forward()]
            entry['time'] = {n: deformer.channel(n).get() for n in ('timeMode', 'timeOffset', 'timeSpeed')}
        except Exception:
            entry['problem'] = traceback.format_exc()
        deformers.append(entry)
    result['deformers'] = deformers
    files = []
    for item in scene.items('AlembicFile'):
        raw = item.channel('filePath').get()
        path = extra_geometry.alembic_path(raw)
        files.append({'name': item.name, 'raw': raw, 'path': str(path), 'exists': path.is_file()})
        try:
            read = extra_geometry.alembic_meshes(path, frame / fps)
            files[-1]['meshes'] = [(r['name'], len(r['vertices']), r['first'], r['last']) for r in read]
        except Exception:
            files[-1]['problem'] = traceback.format_exc()
    result['files'] = files
    # The kit's own step, on the meshes as a render reads them now.
    from moonray_modo import host
    held = host.snapshot(evaluated_geometry=True)
    before = [m['identity'] for m in held.get('meshes', [])]
    after = extra_geometry.imported_alembic(list(held.get('meshes', [])), frame, fps)
    result['meshes_before'] = before[:20]
    result['meshes_after'] = [(m['identity'], len(m['vertices']), bool(m.get('_alembic'))) for m in after][:20]
except Exception:
    result['error'] = traceback.format_exc()
target = out / 'diag-abc-import.json'
target.write_text(json.dumps(result, indent=1, default=repr), encoding='utf-8')
lx.out('MoonRay Alembic check written to %s' % target)
