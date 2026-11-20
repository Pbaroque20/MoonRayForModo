# python
"""Headless: the Links panel's module (links.py) end to end in a test scene: two meshes linked, one brought back to
edit, edited, written (Update File, geometry only: the same item), moved and written by the save step (after_save),
its file changed on disk, made a proxy again (Done Editing), relinked, embedded; each action run as moonray.links.act, as
the panel runs it. After each step the panel's rows, the Shader Tree's size and what the file holds.
Written to test-results/links/flow.json."""
import json
import os
import pathlib
import shutil
import time
import traceback
import lx
import modo
from moonray_modo import links

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\links-manager\test-results\links\flow'))
if out.exists():
    shutil.rmtree(str(out))
out.mkdir(parents=True)
result = {'steps': []}


def save():
    (out / 'flow.json').write_text(json.dumps(result, indent=1, default=str))


def shader_count():
    return len(links._shaders())


def holds(path):
    lx.eval('!scene.open {%s} normal' % path)
    found = {m.name: [m.geometry.numVertices, [round(v, 3) for v in m.position.get()]] for m in modo.Scene().items('mesh') if m.geometry.numPolygons}
    lx.eval('!scene.close')
    return found


def note(step, **extra):
    rows = links.rows()
    result['steps'].append(dict(step=step, rows=[{k: r.get(k) for k in ('id', 'name', 'state', 'status', 'file')} for r in rows],
                                shaders=shader_count(), scene=modo.Scene().filename,
                                selected=[i.name for i in modo.Scene().selected], **extra))
    save()
    return {r['name']: r for r in rows}


def cube(name, x, colour, segments=1):
    lx.eval('item.create mesh {%s}' % name)
    mesh = [i for i in modo.Scene().items('mesh') if i.name == name][0]
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('tool.set prim.cube on')
    for axis in 'XYZ':
        lx.eval('tool.attr prim.cube segments%s %d' % (axis, segments))
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('select.type polygon')
    lx.eval('select.all')
    lx.eval('poly.setMaterial {%s} {%s} 0.8 0.04 true false' % (name, colour))
    lx.eval('select.drop polygon')
    lx.eval('select.type item')
    mesh.position.set([x, 0.0, 0.0])
    return mesh


def by_name(name, kind):
    return [i for i in modo.Scene().items(kind) if i.name == name]


try:
    lx.eval('scene.new')
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'main.lxo'))
    box = cube('Box', 2.0, '0.8 0.1 0.1')
    ball = cube('Ball', -2.0, '0.1 0.1 0.8', 4)
    other = cube('Other', 5.0, '0.1 0.8 0.1')
    # A mesh under a moved locator.
    kid = cube('Kid', 0.5, '0.8 0.8 0.1')
    lx.eval('item.create locator {Rig}')
    rig = [i for i in modo.Scene().items('locator') if i.name == 'Rig'][0]
    rig.position.set([0.0, 2.0, -3.0])
    lx.eval('item.parent {%s} {%s} 0 inPlace:0' % (kid.id, rig.id))
    lx.eval('select.item {%s} set' % other.id)
    from moonray_modo import evaluated
    def placed():
        data = evaluated.capture(lx.service.Selection().GetTime())
        evaluated.proxies(data, modo.Scene(), lx.service.Selection().GetTime(), [])
        return sorted([round(v, 3) for v in (s.get('matrix') or [])[12:15]] for s in data['surfaces'])
    result['placed_embedded'] = placed()
    note('made')
    folder = links.default_folder(modo.Scene().filename)
    started = time.monotonic()
    proxies = links.run('link', [box.id, ball.id, kid.id], folder)
    rows = note('linked', seconds=round(time.monotonic() - started, 3), proxies=proxies, files=sorted(p.name for p in folder.glob('*.lxo')),
                kid_file=holds(folder / 'Kid.lxo'))
    result['placed_linked'] = placed()
    shaders = shader_count()
    proxy = by_name('Box', 'proxy')[0]
    started = time.monotonic()
    meshes = links.run('edit', [proxy.id])
    rows = note('edit in scene', seconds=round(time.monotonic() - started, 3), shaders_before=shaders, meshes=meshes)
    box = by_name('Box', 'mesh')[0]
    kept = box.id
    lx.eval('select.item {%s} set' % box.id)
    lx.eval('select.type polygon')
    lx.eval('select.all')
    lx.eval('poly.subdivide flat')
    lx.eval('select.drop polygon')
    lx.eval('select.type item')
    lx.eval('select.item {%s} set' % other.id)
    note('edited')
    started = time.monotonic()
    written = links.run('update', [box.id])
    note('update file', seconds=round(time.monotonic() - started, 3), written=written, same_item=written == [kept],
         file=holds(folder / 'Box.lxo'))
    box = by_name('Box', 'mesh')[0]
    box.position.set([2.0, 1.5, 0.0])
    note('moved: nothing new for the file')
    lx.eval('select.item {%s} set' % box.id)
    lx.eval('select.type vertex')
    lx.eval('select.all')
    lx.eval('vert.move posY:0.25')
    lx.eval('select.drop vertex')
    lx.eval('select.type item')
    lx.eval('select.item {%s} set' % other.id)
    note('points moved')
    started = time.monotonic()
    written = links.after_save()
    note('after save', seconds=round(time.monotonic() - started, 3), written=written, file=holds(folder / 'Box.lxo'))
    written = links.after_save()
    note('after save, nothing changed', written=written)
    # The file changed on disk by another hand.
    os.utime(str(folder / 'Box.lxo'), None)
    time.sleep(0.05)
    path = folder / 'Box.lxo'
    os.utime(str(path), ns=(time.time_ns(), path.stat().st_mtime_ns + 5_000_000_000))
    note('file changed on disk')
    box = by_name('Box', 'mesh')[0]
    made = links.run('done', [box.id])
    note('done editing', made=made, file=holds(folder / 'Box.lxo'))
    result['placed_done'] = placed()
    kid_proxy = by_name('Kid', 'proxy')[0]
    links.run('edit', [kid_proxy.id])
    kid = by_name('Kid', 'mesh')[0]
    note('kid edited', kid_world=[round(v, 3) for v in modo.Matrix4(kid.channel('worldMatrix').get()).position],
         kid_parent=kid.parent.name if kid.parent else None)
    proxy = by_name('Box', 'proxy')[0]
    other_file = folder / 'Box copy.lxo'
    shutil.copyfile(str(folder / 'Box.lxo'), str(other_file))
    links.run('relink', [proxy.id], other_file)
    note('relinked', channel=links.proxy_file(by_name('Box', 'proxy')[0]))
    (folder / 'Ball.lxo').rename(folder / 'Ball moved.lxo')
    note('ball file missing')
    (folder / 'Ball moved.lxo').rename(folder / 'Ball.lxo')
    made = links.run('embed', [by_name('Box', 'proxy')[0].id])
    note('embedded', made=made, tag=links.read_tag(by_name('Box', 'mesh')[0]) if by_name('Box', 'mesh') else 'no mesh')
    result['watch_saves'] = links.watch_saves()
    lx.eval('!scene.save')
    note('saved')
    if os.environ.get('PROBE_RELEASE'):
        from moonray_modo import evaluated as _evaluated
        _evaluated.release_proxies()
        result['released'] = True
    result['done'] = True
except Exception:
    result['error'] = traceback.format_exc()
save()
