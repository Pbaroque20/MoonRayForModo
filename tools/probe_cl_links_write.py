# python
"""Headless: how the Links panel (links.py) can write a mesh being edited to its file while it stays editable.
A. proxy.convert writes what: the selection logged before each convert, the file opened afterwards.
B. A copy: the mesh duplicated (item.duplicate as Modo's menu runs it), the copy alone selected and converted to the
   file, its proxy deleted; the mesh kept as it was.
C. A round trip: the mesh converted and restored; its id, name, tag, children and the scene's materials before and after.
Written to test-results/links/write.json."""
import json
import os
import pathlib
import time
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\links-manager\test-results\links'))
out.mkdir(parents=True, exist_ok=True)
for old in out.glob('w-*.lxo'):
    old.unlink()
result = {}


def save():
    (out / 'write.json').write_text(json.dumps(result, indent=1, default=str))


def find(name, kind=None):
    return [i for i in modo.Scene().items() if i.name == name and (kind is None or i.type == kind)]


def selected():
    return [(i.name, i.type) for i in modo.Scene().selected]


def materials():
    return sorted(i.name for i in modo.Scene().items('advancedMaterial'))


def holds(path):
    lx.eval('!scene.open {%s} normal' % path)
    rows = [(i.name, i.type, i.parent.name if i.parent else None) for i in modo.Scene().items() if i.type in ('mesh', 'locator', 'proxy', 'groupLocator')]
    lx.eval('!scene.close')
    return rows


def cube(name, x=0.0):
    lx.eval('item.create mesh {%s}' % name)
    mesh = find(name, 'mesh')[0]
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('select.type polygon')
    lx.eval('select.all')
    lx.eval('poly.setMaterial {%s} {0.8 0.1 0.1} 0.8 0.04 true false' % name)
    lx.eval('select.type item')
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('transform.channel pos.X %s' % x)
    return find(name, 'mesh')[0]


def only(item):
    lx.eval('select.drop item')
    lx.eval('select.item {%s} set' % item.id)


try:
    lx.eval('scene.new')
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'w-main.lxo'))
    alpha = cube('Alpha', 2.0)
    other = cube('Other', -2.0)
    lx.eval('item.create locator {Loc}')
    lx.eval('item.create locator {AlphaChild}')
    child = find('AlphaChild')[0]
    lx.eval('item.parent {%s} {%s} 0 inPlace:1' % (child.id, alpha.id))
    alpha.setTag('MRLK', 'record')
    # A.
    only(alpha)
    result['A_selection'] = selected()
    lx.eval('!proxy.convert item:{%s} filename:{%s} format:$LXOB tsurf:false' % (alpha.id, out / 'w-alpha.lxo'))
    result['A_file'] = holds(out / 'w-alpha.lxo')
    result['A_scene'] = [(i.name, i.type, i.parent.name if i.parent else None) for i in modo.Scene().items() if i.type in ('mesh', 'locator', 'proxy')]
    proxy = find('Alpha', 'proxy')[0]
    only(proxy)
    lx.eval('!proxy.restore item:{%s}' % proxy.id)
    alpha = find('Alpha', 'mesh')[0]
    result['A_restored'] = {'id': alpha.id, 'tag': alpha.readTag('MRLK'), 'children': [c.name for c in alpha.children()], 'materials': materials()}
    save()
    # B: a copy converted.
    lx.eval('select.type vertex')
    only(alpha)
    lx.eval('select.type vertex')
    lx.eval('select.all')
    lx.eval('vert.move posY:0.5')
    lx.eval('select.type item')
    kept = alpha.id
    before = materials()
    only(alpha)
    started = time.monotonic()
    lx.eval('item.duplicate')
    result['B_after_duplicate_selection'] = selected()
    copies = [i for i in modo.Scene().items('mesh') if i.name.startswith('Alpha') and i.id != kept]
    copy = copies[0]
    only(copy)
    result['B_selection'] = selected()
    lx.eval('!proxy.convert item:{%s} filename:{%s} format:$LXOB tsurf:false' % (copy.id, out / 'w-alpha.lxo'))
    made = [i for i in modo.Scene().items('proxy') if str(i.channel('scene').get()) == str(out / 'w-alpha.lxo')]
    for item in made:
        only(item)
        lx.eval('!item.delete')
    result['B_seconds'] = round(time.monotonic() - started, 3)
    result['B_file'] = holds(out / 'w-alpha.lxo')
    result['B_scene'] = [(i.name, i.id, i.type, i.parent.name if i.parent else None) for i in modo.Scene().items() if i.type in ('mesh', 'locator', 'proxy')]
    result['B_materials'] = {'before': before, 'after': materials()}
    result['B_kept'] = [i.id for i in find('Alpha', 'mesh')]
    save()
    # C: a round trip.
    alpha = find('Alpha', 'mesh')[0]
    before = materials()
    started = time.monotonic()
    only(alpha)
    lx.eval('!proxy.convert item:{%s} filename:{%s} format:$LXOB tsurf:false' % (alpha.id, out / 'w-alpha.lxo'))
    proxy = find('Alpha', 'proxy')[0]
    only(proxy)
    lx.eval('!proxy.restore item:{%s}' % proxy.id)
    alpha = find('Alpha', 'mesh')[0]
    result['C'] = {'seconds': round(time.monotonic() - started, 3), 'id_before': kept, 'id_after': alpha.id, 'tag': alpha.readTag('MRLK'),
                   'children': [c.name for c in alpha.children()], 'materials_before': before, 'materials_after': materials(),
                   'file': holds(out / 'w-alpha.lxo')}
    result['done'] = True
except Exception:
    result['error'] = traceback.format_exc()
save()
