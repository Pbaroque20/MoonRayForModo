# python
"""Headless: the Links panel's write of a mesh being edited (links.py), geometry only: the edited polygons copied
(select.copy), the link file opened, its mesh's polygons replaced by them (select.paste), its place set, saved, closed.
The open scene stays as it was. Then what proxy.restore adds to the Shader Tree, and whether removing those additions
leaves the restored mesh shaded as before. Written to test-results/links/geometry.json."""
import json
import os
import pathlib
import time
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\links-manager\test-results\links'))
out.mkdir(parents=True, exist_ok=True)
for old in out.glob('g-*.lxo'):
    old.unlink()
result = {}


def save():
    (out / 'geometry.json').write_text(json.dumps(result, indent=1, default=str))


def find(name, kind=None):
    return [i for i in modo.Scene().items() if i.name == name and (kind is None or i.type == kind)]


def shader_items():
    return sorted((i.name, i.id, i.type) for i in modo.Scene().items() if i.type in ('advancedMaterial', 'mask', 'imageMap', 'constant'))


def mesh_rows():
    found = []
    for i in modo.Scene().items('mesh'):
        geo = i.geometry
        found.append([i.name, i.id, geo.numVertices, geo.numPolygons, sorted({p.materialTag for p in geo.polygons}),
                      sorted(m.name for m in geo.vmaps), [round(v, 3) for v in modo.Matrix4(i.channel('worldMatrix').get()).position]])
    return found


def holds(path):
    lx.eval('!scene.open {%s} normal' % path)
    found = mesh_rows()
    lx.eval('!scene.close')
    return found


try:
    lx.eval('scene.new')
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'g-main.lxo'))
    lx.eval('item.create mesh {Alpha}')
    alpha = find('Alpha', 'mesh')[0]
    lx.eval('select.item {%s} set' % alpha.id)
    lx.eval('tool.set prim.cube on')
    for axis in 'XYZ':
        lx.eval('tool.attr prim.cube segments%s 1' % axis)
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('select.type polygon')
    lx.eval('select.all')
    lx.eval('poly.setMaterial {Alpha} {0.2 0.7 0.3} 0.8 0.04 true false')
    lx.eval('select.type item')
    lx.eval('transform.channel pos.X 2.0')
    path = out / 'g-alpha.lxo'
    lx.eval('select.drop item')
    lx.eval('select.item {%s} set' % alpha.id)
    lx.eval('!proxy.convert item:{%s} filename:{%s} format:$LXOB tsurf:false' % (alpha.id, path))
    proxy = find('Alpha', 'proxy')[0]
    before_restore = shader_items()
    lx.eval('select.item {%s} set' % proxy.id)
    lx.eval('!proxy.restore item:{%s}' % proxy.id)
    after_restore = shader_items()
    added = [row for row in after_restore if row not in before_restore]
    result['restore_added'] = added
    # Those additions removed: the restored mesh still wears the scene's own material.
    for name, ident, kind in added:
        if kind == 'mask':
            lx.eval('select.item {%s} set' % ident)
            lx.eval('!item.delete')
    result['after_cleanup'] = shader_items()
    alpha = find('Alpha', 'mesh')[0]
    # An edit: subdivided, moved.
    lx.eval('select.drop item')
    lx.eval('select.item {%s} set' % alpha.id)
    lx.eval('select.type polygon')
    lx.eval('select.all')
    lx.eval('poly.subdivide flat')
    lx.eval('select.type item')
    lx.eval('transform.channel pos.Y 1.5')
    main_before = mesh_rows()
    shaders_before = shader_items()
    started = time.monotonic()
    # The write.
    lx.eval('select.drop item')
    lx.eval('select.item {%s} set' % alpha.id)
    lx.eval('select.type polygon')
    lx.eval('select.drop polygon')
    lx.eval('select.all')
    lx.eval('select.copy')
    lx.eval('select.drop polygon')
    lx.eval('select.type item')
    pos = list(alpha.position.get())
    lx.eval('!scene.open {%s} normal' % path)
    held = [i for i in modo.Scene().items('mesh') if i.name == 'Alpha']
    target = held[0]
    lx.eval('select.drop item')
    lx.eval('select.item {%s} set' % target.id)
    lx.eval('select.type polygon')
    lx.eval('select.all')
    lx.eval('!delete')
    lx.eval('select.paste')
    lx.eval('select.drop polygon')
    lx.eval('select.type item')
    target.position.set(pos)
    lx.eval('!scene.save')
    lx.eval('!scene.close')
    result['write'] = {'seconds': round(time.monotonic() - started, 3), 'main_same': mesh_rows() == main_before and shader_items() == shaders_before,
                       'main': mesh_rows(), 'file': holds(path)}
    result['done'] = True
except Exception:
    result['error'] = traceback.format_exc()
save()
