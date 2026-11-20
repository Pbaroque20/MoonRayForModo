# python
"""Headless, after probe_cl_links_commands.py's questions: for the Links panel (links.py).
1. What a file proxy.convert writes holds: opened as a scene of its own, its items, places and materials.
2. Whether proxy.restore reads the file as it is on disk now: a proxy's file replaced by another mesh's, then restored.
3. A mesh with a child locator converted: where the child goes.
4. A file written for a mesh that stays editable: the mesh duplicated, the copy converted to the file and its proxy
   deleted; the mesh kept as it was (its id, its place), the file holding the edit.
5. Timings of convert and restore for a dense mesh (a sphere of many points).
Written to test-results/links/details.json."""
import json
import os
import pathlib
import time
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\links-manager\test-results\links'))
out.mkdir(parents=True, exist_ok=True)
for old in out.glob('d-*.lxo'):
    old.unlink()
result = {}


def save():
    (out / 'details.json').write_text(json.dumps(result, indent=1, default=str))


def find(name, kind=None):
    return [i for i in modo.Scene().items() if i.name == name and (kind is None or i.type == kind)]


def describe(scene=None):
    scene = scene or modo.Scene()
    rows = []
    for item in scene.items():
        if item.type in ('mesh', 'proxy', 'locator', 'groupLocator'):
            row = {'name': item.name, 'id': item.id, 'type': item.type, 'parent': item.parent.name if item.parent else None}
            try:
                row['pos'] = [round(float(item.channel('pos.' + a).get()), 3) for a in 'XYZ'] if False else None
            except Exception:
                pass
            try:
                xfrm = modo.LocatorSuperType(item) if item.type != 'proxy' else None
                row['pos'] = [round(v, 3) for v in xfrm.position.get()] if xfrm else None
            except Exception:
                row['pos'] = None
            try:
                row['world'] = [round(v, 3) for v in modo.Matrix4(item.channel('worldMatrix').get()).position]
            except Exception:
                pass
            if item.type == 'mesh':
                try:
                    row['points'] = item.geometry.numVertices
                    row['materials'] = sorted({p.materialTag for p in item.geometry.polygons})
                except Exception:
                    pass
            if item.type == 'proxy':
                row['file'] = str(item.channel('scene').get())
            rows.append(row)
    materials = sorted(i.name for i in scene.items('advancedMaterial'))
    return {'items': rows, 'materials': materials}


def cube(name, x=0.0, material='Red', colour='0.8 0.1 0.1', segments=None):
    lx.eval('item.create mesh {%s}' % name)
    mesh = find(name, 'mesh')[0]
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('tool.set prim.cube on')
    if segments:
        for axis in 'XYZ':
            lx.eval('tool.attr prim.cube segments%s %d' % (axis, segments))
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('select.type polygon')
    lx.eval('select.all')
    lx.eval('poly.setMaterial {%s} {%s} 0.8 0.04 true false' % (material, colour))
    lx.eval('select.type item')
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('transform.channel pos.X %s' % x)
    return find(name, 'mesh')[0]


def restore(proxy):
    lx.eval('select.item {%s} set' % proxy.id)
    lx.eval('!proxy.restore item:{%s}' % proxy.id)


def convert(mesh, path):
    # proxy.convert works on the selection.
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('!proxy.convert item:{%s} filename:{%s} format:$LXOB tsurf:false' % (mesh.id, path))
    return [i for i in modo.Scene().items('proxy') if str(i.channel('scene').get()) == str(path)]


try:
    lx.eval('scene.new')
    main = modo.Scene()
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'd-main.lxo'))
    # 1 and 2.
    a = cube('Alpha', 2.0)
    proxy = convert(a, out / 'd-alpha.lxo')[0]
    lx.eval('!scene.open {%s} normal' % (out / 'd-alpha.lxo'))
    result['file_holds'] = describe()
    result['file_scene'] = modo.Scene().filename
    lx.eval('!scene.close')
    result['back_to'] = modo.Scene().filename
    save()
    # 2: the linked file edited in a scene of its own (Edit Original), its cube made denser, then restored here.
    lx.eval('!scene.open {%s} normal' % (out / 'd-alpha.lxo'))
    held = find('Alpha', 'mesh')[0]
    lx.eval('select.item {%s} set' % held.id)
    lx.eval('select.type polygon')
    lx.eval('select.all')
    lx.eval('poly.subdivide flat')
    lx.eval('select.type item')
    edited_points = held.geometry.numVertices
    lx.eval('!scene.save')
    lx.eval('!scene.close')
    proxy = find('Alpha', 'proxy')[0]
    restore(proxy)
    result['restore_after_file_edited'] = {'edited_points': edited_points, 'scene': describe()}
    save()
    # 3: a child.
    parent = cube('Gamma', 4.0)
    lx.eval('item.create locator {GammaChild}')
    child = find('GammaChild')[0]
    lx.eval('item.parent {%s} {%s} 0 inPlace:1' % (child.id, parent.id))
    convert(parent, out / 'd-gamma.lxo')
    result['child'] = describe()
    save()
    # 4: written while it stays editable.
    d = cube('Delta', 6.0)
    convert(d, out / 'd-delta.lxo')
    restore(find('Delta', 'proxy')[0])
    d = find('Delta', 'mesh')[0]
    kept_id = d.id
    lx.eval('select.item {%s} set' % d.id)
    lx.eval('transform.channel pos.Y 1.25')
    lx.eval('select.type vertex')
    lx.eval('select.all')
    lx.eval('vert.move posY:0.5')
    lx.eval('select.type item')
    before = (out / 'd-delta.lxo').stat().st_mtime_ns
    started = time.monotonic()
    lx.eval('select.item {%s} set' % d.id)
    lx.eval('item.duplicate false locator false true')
    copies = [i for i in modo.Scene().items('mesh') if i.name.startswith('Delta') and i.id != kept_id]
    result['duplicate'] = [i.name for i in copies]
    if copies:
        copy = copies[0]
        copy.name = 'Delta'
        convert(copy, out / 'd-delta.lxo')
        written = [i for i in modo.Scene().items('proxy') if str(i.channel('scene').get()) == str(out / 'd-delta.lxo')]
        for item in written:
            lx.eval('select.item {%s} set' % item.id)
            lx.eval('!item.delete')
    result['write_kept_editable'] = {'seconds': round(time.monotonic() - started, 3), 'file_changed': (out / 'd-delta.lxo').stat().st_mtime_ns != before,
                                     'kept': [i.id for i in find('Delta', 'mesh')], 'kept_id': kept_id, 'scene': describe()}
    save()
    lx.eval('!scene.open {%s} normal' % (out / 'd-delta.lxo'))
    result['delta_file_holds'] = describe()
    lx.eval('!scene.close')
    # 5: timings.
    s = cube('Sigma', 8.0, segments=120)
    result['sigma_points'] = s.geometry.numVertices
    started = time.monotonic()
    convert(s, out / 'd-sigma.lxo')
    result['convert_seconds'] = round(time.monotonic() - started, 3)
    started = time.monotonic()
    restore(find('Sigma', 'proxy')[0])
    result['restore_seconds'] = round(time.monotonic() - started, 3)
    result['sigma_file_mb'] = round((out / 'd-sigma.lxo').stat().st_size / 1e6, 2)
    result['done'] = True
except Exception:
    result['error'] = traceback.format_exc()
save()
