# python
"""Headless: a mesh being edited written to its link file (links.write_geometry) where it stands moved, turned, scaled
and under a turned parent: the file's mesh must hold the same points as the mesh's own (its bounds in its own space), at
the origin. Written to test-results/links/place-write.json."""
import json
import math
import pathlib
import shutil
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\links-manager\test-results\links\place-write')
if out.exists():
    shutil.rmtree(str(out))
out.mkdir(parents=True)
result = {}


def save():
    (out / 'place-write.json').write_text(json.dumps(result, indent=1, default=str))


def bounds(item):
    low, high = item.geometry.boundingBox
    return [round(v, 4) for v in list(low) + list(high)]


try:
    from moonray_modo import links
    lx.eval('scene.new')
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'main.lxo'))
    lx.eval('item.create locator {Rig}')
    rig = [i for i in modo.Scene().items('locator') if i.name == 'Rig'][0]
    rig.position.set([1.0, 2.0, -3.0])
    rig.rotation.set([0.0, math.radians(45), 0.0])
    lx.eval('item.create mesh {Crate}')
    crate = [i for i in modo.Scene().items('mesh') if i.name == 'Crate'][0]
    lx.eval('select.item {%s} set' % crate.id)
    lx.eval('tool.set prim.cube on')
    for axis in 'XYZ':
        lx.eval('tool.attr prim.cube segments%s 1' % axis)
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('item.parent {%s} {%s} 0 inPlace:0' % (crate.id, rig.id))
    crate.position.set([0.5, 0.0, 0.0])
    crate.rotation.set([math.radians(10), math.radians(30), 0.0])
    crate.scale.set([1.5, 1.0, 1.0])
    result['own'] = bounds(crate)
    links.run('link', [crate.id], json.dumps({'folder': str(out / 'links'), 'standin': 'none'}))
    proxy = list(modo.Scene().items('proxy'))[0]
    links.run('edit', [proxy.id])
    crate = [i for i in modo.Scene().items('mesh') if i.name == 'Crate'][0]
    result['restored_world'] = [round(v, 3) for v in modo.Matrix4(crate.channel('worldMatrix').get()).position]
    lx.eval('select.item {%s} set' % crate.id)
    lx.eval('select.type polygon')
    lx.eval('select.all')
    lx.eval('poly.subdivide flat')
    lx.eval('select.drop polygon')
    lx.eval('select.type item')
    result['edited_own'] = bounds(crate)
    result['written'] = links.run('update', [crate.id])
    path = links.read_tag(crate)['file']
    main = modo.Scene()
    lx.eval('!scene.open {%s} normal' % path)
    target = [m for m in modo.Scene().items('mesh') if m.name == 'Crate'][0]
    result['file'] = bounds(target)
    result['file_place'] = [list(target.position.get()), list(target.rotation.get()), list(target.scale.get()), target.parent.name if target.parent else None]
    result['file_points'] = target.geometry.numVertices
    lx.eval('!scene.close')
    links._back_to(main)
    result['same'] = all(abs(a - b) < 1e-3 for a, b in zip(result['file'], result['edited_own']))
    result['done'] = True
except Exception:
    result['error'] = traceback.format_exc()
save()
try:
    lx.eval('!scene.close')
except Exception:
    pass
