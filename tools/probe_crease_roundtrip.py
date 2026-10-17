# python
"""Isolated GUI test: subdivision creases come in from a MoonRay scene as Modo's subdivision weights, and go out to
MoonRay again as crease sharpness.

A subdivided cube is imported with a fully sharp crease (sharpness 10), a semi-sharp one (3) and a sharp corner. The
weights the import wrote are read back, then the scene is captured as for a render, and its mesh's creases, corners and
the scene text MoonRay is given are written down."""
import json
import pathlib
import traceback
import lx
import modo

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/crease-roundtrip'
out.mkdir(parents=True, exist_ok=True)
result = {}

CORNERS = [[-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1], [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1]]
FACES = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [2, 3, 7, 6], [1, 2, 6, 5], [0, 4, 7, 3]]

try:
    from moonray_modo import host, rdl_import, rdla
    lx.eval('scene.new')
    attributes = {'subd_crease_indices': [4, 5, 5, 6], 'subd_crease_sharpnesses': [10, 3], 'subd_corner_indices': [0], 'subd_corner_sharpnesses': [10]}
    edges, corners, _ = rdl_import.hard_creases(attributes, FACES, len(CORNERS))
    record = dict(name='Creased cube', vertices=CORNERS, faces=FACES, uv=[], normals=[], tags=[None] * 6, subd=True, matrix=None, render=True,
                  attributes=[], hard_edges=edges, hard_corners=corners)
    data = dict(meshes=[record], curves=[], instances=[], entities=[], materials={}, cameras=[], settings={}, links=[], warnings=[], source='test.rdla')
    result['import'] = rdl_import.apply(data)
    item = next(i for i in modo.Scene().items('mesh') if i.name == 'Creased cube')
    geo = item.geometry
    mesh = geo.internalMesh
    map_id = host.first_map(mesh, lx.symbol.i_VMAP_SUBDIV)
    value = lx.object.storage('f', 1)
    edge = lx.object.Edge(mesh.EdgeAccessor())
    weights = {}
    for a, b in ((4, 5), (5, 6), (6, 7)):
        edge.SelectEndpoints(geo.vertices[a]._id, geo.vertices[b]._id)
        weights['%d-%d' % (a, b)] = round(value.get()[0], 4) if edge.MapValue(map_id, value) else None
    result['weights_in_modo'] = weights
    snapshot = host.snapshot()
    captured = next(m for m in snapshot['meshes'] if m['name'] == 'Creased cube')
    result['captured'] = {'subdivision': captured.get('subdivision'), 'creases': captured.get('creases'), 'corners': captured.get('corners')}
    text = rdla.scene_text(snapshot, 64, 64)
    result['scene_lines'] = [line.strip() for line in text.splitlines() if 'subd_crease' in line or 'subd_corner' in line]
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
