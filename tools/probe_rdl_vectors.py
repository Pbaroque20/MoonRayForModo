# python
"""Isolated GUI test: a vector at each point of a MoonRay shape comes in as a colour map noted as a vector, and goes
out to MoonRay again as a vector (vec3f), with its values."""
import json
import pathlib
import traceback
import lx
import modo

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/rdl-vectors'
out.mkdir(parents=True, exist_ok=True)
result = {}

try:
    from moonray_modo import host, properties, rdl_import, rdla
    lx.eval('scene.new')
    record = dict(name='Rested', vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0]], faces=[[0, 1, 2]], uv=[], normals=[], tags=[None], subd=False,
                  matrix=None, render=True, attributes=[], hard_edges=[], hard_corners=[],
                  maps=[('rest', 'vec3', 'points', [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]])])
    data = dict(meshes=[record], curves=[], instances=[], entities=[], materials={}, cameras=[], settings={}, links=[], warnings=[], source='test.rdla')
    result['import'] = rdl_import.apply(data)
    item = next(i for i in modo.Scene().items('mesh') if i.name == 'Rested')
    result['noted'] = properties.read(item).get('vertex_map_kinds')
    snapshot = host.snapshot()
    captured = next(m for m in snapshot['meshes'] if m['name'] == 'Rested')
    result['captured'] = captured.get('point_attributes')
    text = rdla.scene_text(snapshot, 16, 16)
    start = text.find('"vec3f_key"')
    result['scene'] = text[max(0, start - 60):start + 200] if start >= 0 else None
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
