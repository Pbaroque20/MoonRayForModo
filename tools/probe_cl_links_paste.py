# python
"""Headless: a mesh being edited written to its file while the scene stays as it is, for links.py: the mesh copied
(Modo's copy), pasted into a new scene, that scene saved as the file and closed. Whether its material, place, tags and
children come along, whether the open scene is untouched, and how long it takes. Also which other surfaces
proxy.convert takes into a file: two meshes sharing one material tag, one converted.
Written to test-results/links/paste.json."""
import json
import os
import pathlib
import time
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\links-manager\test-results\links'))
out.mkdir(parents=True, exist_ok=True)
for old in out.glob('p-*.lxo'):
    old.unlink()
result = {}


def save():
    (out / 'paste.json').write_text(json.dumps(result, indent=1, default=str))


def find(name, kind=None):
    return [i for i in modo.Scene().items() if i.name == name and (kind is None or i.type == kind)]


def rows():
    found = []
    for i in modo.Scene().items():
        if i.type in ('mesh', 'locator', 'proxy', 'camera', 'sunLight', 'advancedMaterial', 'mask'):
            row = [i.name, i.id, i.type, i.parent.name if i.parent else None]
            if i.type == 'mesh':
                row += [i.geometry.numVertices, sorted({p.materialTag for p in i.geometry.polygons})]
                try:
                    row.append([round(v, 3) for v in modo.Matrix4(i.channel('worldMatrix').get()).position])
                except Exception:
                    pass
                try:
                    row.append(i.readTag('MRLK'))
                except Exception:
                    row.append(None)
            if i.type == 'advancedMaterial':
                try:
                    row.append([round(float(v), 3) for v in i.channel('diffCol').get()])
                except Exception:
                    pass
            found.append(row)
    return found


def holds(path):
    lx.eval('!scene.open {%s} normal' % path)
    found = rows()
    lx.eval('!scene.close')
    return found


def cube(name, x=0.0, tag=None, colour='0.8 0.1 0.1'):
    lx.eval('item.create mesh {%s}' % name)
    mesh = find(name, 'mesh')[0]
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('tool.set prim.cube on')
    for axis in 'XYZ':
        lx.eval('tool.attr prim.cube segments%s 1' % axis)
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('select.type polygon')
    lx.eval('select.all')
    lx.eval('poly.setMaterial {%s} {%s} 0.8 0.04 true false' % (tag or name, colour))
    lx.eval('select.type item')
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('transform.channel pos.X %s' % x)
    return find(name, 'mesh')[0]


try:
    lx.eval('scene.new')
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'p-main.lxo'))
    main_file = modo.Scene().filename
    alpha = cube('Alpha', 2.0, colour='0.2 0.7 0.3')
    lx.eval('item.create locator {AlphaChild}')
    child = find('AlphaChild')[0]
    lx.eval('item.parent {%s} {%s} 0 inPlace:1' % (child.id, alpha.id))
    alpha.setTag('MRLK', 'record')
    lx.eval('select.drop item')
    lx.eval('select.item {%s} set' % alpha.id)
    lx.eval('select.type vertex')
    lx.eval('select.all')
    lx.eval('vert.move posY:0.5')
    lx.eval('select.type item')
    before = rows()
    started = time.monotonic()
    lx.eval('select.drop item')
    lx.eval('select.item {%s} set' % alpha.id)
    lx.eval('copy')
    lx.eval('scene.new')
    for item in list(modo.Scene().items('mesh')):
        lx.eval('select.item {%s} set' % item.id)
        lx.eval('!item.delete')
    lx.eval('paste')
    pasted = rows()
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'p-alpha.lxo'))
    lx.eval('!scene.close')
    result['paste'] = {'seconds': round(time.monotonic() - started, 3), 'back_to_main': modo.Scene().filename == main_file,
                       'main_same': rows() == before, 'pasted_scene': pasted, 'file': holds(out / 'p-alpha.lxo'), 'main_before': before}
    save()
    # Which surfaces proxy.convert takes: two meshes of one material tag, and one of another.
    one = cube('ShareOne', 5.0, tag='Shared')
    two = cube('ShareTwo', 7.0, tag='Shared')
    three = cube('Apart', 9.0, tag='Apart')
    lx.eval('select.drop item')
    lx.eval('select.item {%s} set' % one.id)
    lx.eval('!proxy.convert item:{%s} filename:{%s} format:$LXOB tsurf:false' % (one.id, out / 'p-share.lxo'))
    result['shared_tag_file'] = holds(out / 'p-share.lxo')
    result['done'] = True
except Exception:
    result['error'] = traceback.format_exc()
save()
