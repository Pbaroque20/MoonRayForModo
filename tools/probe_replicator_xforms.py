# python
"""Isolated GUI test: can a Modo replicator place copies of a prototype with a turn and size of their own at each point?

Lists Modo's particle vertex map kinds, makes a point mesh of three points with a particle size map and, where Modo has
one, a particle transform map, and a replicator of a cube over it; then captures the scene as for a render to see
where the plugin finds each copy."""
import json
import pathlib
import traceback
import lx
import modo

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/replicator-xforms'
out.mkdir(parents=True, exist_ok=True)
result = {}

try:
    result['all_vmap_kinds'] = sorted(name for name in dir(lx.symbol) if name.startswith('i_VMAP_'))
    result['particle_kinds'] = [name for name in result['all_vmap_kinds'] if any(w in name for w in ('PART', 'XFRM', 'SIZE', 'ROT', 'PSIZ', 'PXF'))]
    lx.eval('scene.new')
    scene = modo.Scene()
    cube = scene.addMesh('Proto')
    corners = [(a - .5, b - .5, c - .5) for a in (0, 1) for b in (0, 1) for c in (0, 1)]
    with cube.geometry as geometry:
        points = [geometry.vertices.new(p) for p in corners]
        for face in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
            geometry.polygons.new([points[i] for i in face])
    cloud = scene.addMesh('Points')
    with cloud.geometry as geometry:
        for p in ((0, 0, 0), (3, 0, 0), (6, 0, 0)):
            geometry.vertices.new(p)
    mesh = cloud.geometry.internalMesh
    maps = lx.object.MeshMap(mesh.MeshMapAccessor())
    made = {}
    for name in result['particle_kinds']:
        try:
            made[name] = maps.New(getattr(lx.symbol, name), 'test_' + name)
        except Exception as exc:
            made[name] = 'failed: %s' % exc
    result['made'] = {k: str(v) for k, v in made.items()}
    replicator = scene.addItem('replicator', name='Copies')
    result['replicator_channels'] = [c.name for c in replicator.channels()][-30:]
    lx.eval('select.item {%s} set' % replicator.id)
    for command in ('replicator.source {%s}' % cloud.id, 'replicator.prototype {%s}' % cube.id):
        try:
            lx.eval(command)
        except Exception as exc:
            result.setdefault('commands', []).append('%s: %s' % (command, exc))
    result['particle_items'] = sorted({name for name in dir(lx.symbol) if name.startswith('sITYPE_') and ('PART' in name or 'CLOUD' in name or 'REPL' in name)})
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
