# python
"""Headless: a mesh being edited written to its file while it stays editable, by proxy.convert and then app.undo: the
file stays written, the scene goes back to as it was (the same item, its materials, its children). Also what else a
proxy file holds (cameras, lights) and what an unrelated top-level locator does there. For links.py.
Written to test-results/links/undo.json."""
import json
import os
import pathlib
import time
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\links-manager\test-results\links'))
out.mkdir(parents=True, exist_ok=True)
for old in out.glob('u-*.lxo'):
    old.unlink()
result = {}


def save():
    (out / 'undo.json').write_text(json.dumps(result, indent=1, default=str))


def find(name, kind=None):
    return [i for i in modo.Scene().items() if i.name == name and (kind is None or i.type == kind)]


def scene_rows():
    return [(i.name, i.id, i.type, i.parent.name if i.parent else None) for i in modo.Scene().items()
            if i.type in ('mesh', 'locator', 'proxy', 'camera', 'sunLight', 'pointLight', 'groupLocator', 'advancedMaterial', 'mask')]


def holds(path):
    lx.eval('!scene.open {%s} normal' % path)
    rows = scene_rows()
    points = {i.name: i.geometry.numVertices for i in modo.Scene().items('mesh')}
    lx.eval('!scene.close')
    return {'items': rows, 'points': points}


try:
    lx.eval('scene.new')
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'u-main.lxo'))
    lx.eval('item.create mesh {Alpha}')
    alpha = find('Alpha', 'mesh')[0]
    lx.eval('select.item {%s} set' % alpha.id)
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('select.type polygon')
    lx.eval('select.all')
    lx.eval('poly.setMaterial {Alpha} {0.8 0.1 0.1} 0.8 0.04 true false')
    lx.eval('select.type item')
    lx.eval('item.create locator {AlphaChild}')
    child = find('AlphaChild')[0]
    lx.eval('item.parent {%s} {%s} 0 inPlace:1' % (child.id, alpha.id))
    alpha.setTag('MRLK', 'record')
    result['scene_before'] = scene_rows()
    path = out / 'u-alpha.lxo'
    # The file first written by Link (convert), then restored for editing.
    lx.eval('select.drop item')
    lx.eval('select.item {%s} set' % alpha.id)
    lx.eval('!proxy.convert item:{%s} filename:{%s} format:$LXOB tsurf:false' % (alpha.id, path))
    result['file_first'] = holds(path)
    proxy = find('Alpha', 'proxy')[0]
    lx.eval('select.item {%s} set' % proxy.id)
    lx.eval('!proxy.restore item:{%s}' % proxy.id)
    alpha = find('Alpha', 'mesh')[0]
    # An edit: subdivided.
    lx.eval('select.item {%s} set' % alpha.id)
    lx.eval('select.type polygon')
    lx.eval('select.all')
    lx.eval('poly.subdivide flat')
    lx.eval('select.type item')
    result['edited_points'] = alpha.geometry.numVertices
    before = scene_rows()
    kept = alpha.id
    mtime = path.stat().st_mtime_ns
    started = time.monotonic()
    lx.eval('select.drop item')
    lx.eval('select.item {%s} set' % alpha.id)
    lx.eval('!proxy.convert item:{%s} filename:{%s} format:$LXOB tsurf:false' % (alpha.id, path))
    converted = scene_rows()
    lx.eval('app.undo')
    result['undo'] = {'seconds': round(time.monotonic() - started, 3), 'file_written': path.stat().st_mtime_ns != mtime,
                      'scene_same': scene_rows() == before, 'converted': converted, 'after': scene_rows(), 'before': before,
                      'kept': [i.id for i in find('Alpha', 'mesh')] == [kept],
                      'points_now': find('Alpha', 'mesh')[0].geometry.numVertices if find('Alpha', 'mesh') else None}
    result['file_after'] = holds(path)
    result['done'] = True
except Exception:
    result['error'] = traceback.format_exc()
save()
