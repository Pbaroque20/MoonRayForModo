# python
"""Headless: stand-ins through the Links panel's actions (links.py, standins.py). An 'Office Chair' and a 'Lamborghini
body' linked with stand-ins by name; each file's meshes (the mesh and '<name> Stand-in', its bounds), the proxies' render
and preview items, and what the kit reads to render (host.snapshot: the meshes, never a stand-in). Then the chair edited
(Edit in Scene: no stand-in comes into the scene), subdivided, the save step, Done Editing; its stand-in changed to the
car's, then none. Written to test-results/links/standins.json."""
import json
import pathlib
import shutil
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\links-manager\test-results\links\standins')
if out.exists():
    shutil.rmtree(str(out))
out.mkdir(parents=True)
result = {'steps': []}


def save():
    (out / 'standins.json').write_text(json.dumps(result, indent=1, default=str))


def file_meshes(path):
    from moonray_modo import links
    main = modo.Scene()
    lx.eval('!scene.open {%s} normal' % path)
    found = []
    for m in modo.Scene().items('mesh'):
        low, high = m.geometry.boundingBox
        try:
            tag = m.readTag('MRSI')
        except Exception:
            tag = None
        found.append({'name': m.name, 'points': m.geometry.numVertices, 'standin': tag,
                      'low': [round(v, 3) for v in low], 'high': [round(v, 3) for v in high]})
    lx.eval('!scene.close')
    links._back_to(main)
    return found


def note(step, files=True):
    from moonray_modo import host, links
    rows = links.rows(embedded=False)
    snap = host.snapshot()
    row = {'step': step, 'rows': [(r['name'], r['state'], r['status'], r.get('standin')) for r in rows],
           'rendered': sorted((m.get('name'), len(m.get('vertices') or [])) for m in snap.get('meshes', [])),
           'scene_meshes': sorted(m.name for m in modo.Scene().items('mesh')),
           'proxies': {p.name: {k: str(p.channel(k).get()) for k in ('itemRender', 'itemPreview')} for p in modo.Scene().items('proxy')}}
    if files:
        row['files'] = {pathlib.Path(r['file']).name: file_meshes(r['file']) for r in rows if r['file']}
    result['steps'].append(row)
    save()


def cube(name, x):
    lx.eval('item.create mesh {%s}' % name)
    item = [i for i in modo.Scene().items('mesh') if i.name == name][0]
    lx.eval('select.item {%s} set' % item.id)
    lx.eval('tool.set prim.cube on')
    for axis in 'XYZ':
        lx.eval('tool.attr prim.cube segments%s 1' % axis)
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    item.position.set([x, 0.0, 0.0])
    return item


try:
    from moonray_modo import links
    lx.eval('scene.new')
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'main.lxo'))
    chair = cube('Office Chair', -2.0)
    car = cube('Lamborghini body', 2.0)
    links.run('link', [chair.id, car.id], json.dumps({'folder': str(out / 'links'), 'standin': 'auto'}))
    note('linked')
    proxy = [p for p in modo.Scene().items('proxy') if p.name == 'Office Chair'][0]
    links.run('edit', [proxy.id])
    note('edit in scene', files=False)
    chair = [m for m in modo.Scene().items('mesh') if m.name == 'Office Chair'][0]
    lx.eval('select.item {%s} set' % chair.id)
    lx.eval('select.type polygon')
    lx.eval('select.all')
    lx.eval('poly.subdivide flat')
    lx.eval('select.drop polygon')
    lx.eval('select.type item')
    result['written_on_save'] = links.after_save()
    note('saved')
    links.run('done', [chair.id])
    note('done editing')
    proxy = [p for p in modo.Scene().items('proxy') if p.name == 'Office Chair'][0]
    links.run('standin', [proxy.id], 'Car')
    note('stand-in: car')
    proxy = [p for p in modo.Scene().items('proxy') if p.name == 'Office Chair'][0]
    links.run('standin', [proxy.id], 'none')
    note('stand-in: none')
    result['done'] = True
except Exception:
    result['error'] = traceback.format_exc()
save()
try:
    lx.eval('!scene.close')
except Exception:
    pass
