# python
"""Headless: where Modo's heap broke in probe_cl_links_flow.py's hidden-polygon step, a note after each sub-step, and
the selection kept by links.kept_selection. Written to test-results/links/hidden.json (fault log hidden-fault.txt)."""
import faulthandler
import json
import os
import pathlib
import shutil
import traceback
import lx
import modo
from moonray_modo import links

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\links-manager\test-results\links\hidden')
if out.exists():
    shutil.rmtree(str(out))
out.mkdir(parents=True)
fault = open(str(out / 'hidden-fault.txt'), 'w')
faulthandler.enable(file=fault, all_threads=True)
result = {'notes': []}


def note(text, **extra):
    result['notes'].append(dict(text=text, selected=[i.name for i in modo.Scene().selected], **extra))
    (out / 'hidden.json').write_text(json.dumps(result, indent=1, default=str))
    fault.write(text + '\n')
    fault.flush()


try:
    lx.eval('scene.new')
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'main.lxo'))
    for name, x in (('Ball', -2.0), ('Other', 3.0)):
        lx.eval('item.create mesh {%s}' % name)
        mesh = [i for i in modo.Scene().items('mesh') if i.name == name][0]
        lx.eval('select.item {%s} set' % mesh.id)
        lx.eval('tool.set prim.cube on')
        for axis in 'XYZ':
            lx.eval('tool.attr prim.cube segments%s 2' % axis)
        lx.eval('tool.apply')
        lx.eval('tool.set prim.cube off')
        lx.eval('select.type polygon')
        lx.eval('select.all')
        lx.eval('poly.setMaterial {%s} {0.1 0.1 0.8} 0.8 0.04 true false' % name)
        lx.eval('select.drop polygon')
        lx.eval('select.type item')
        mesh.position.set([x, 0.0, 0.0])
    ball = [i for i in modo.Scene().items('mesh') if i.name == 'Ball'][0]
    other = [i for i in modo.Scene().items('mesh') if i.name == 'Other'][0]
    lx.eval('select.item {%s} set' % other.id)
    note('made')
    # The selection kept across an update of a mesh that is not selected.
    links.link([ball.id], links.default_folder(modo.Scene().filename))
    note('linked')
    links.edit([[i for i in modo.Scene().items('proxy')][0].id])
    note('edited')
    ball = [i for i in modo.Scene().items('mesh') if i.name == 'Ball'][0]
    ball.position.set([-2.0, 0.25, 0.0])
    links.update([ball.id])
    note('updated: is Other selected?')
    # Polygons left selected in the mesh being written, another item selected: is the item selection kept?
    lx.eval('select.drop item')
    lx.eval('select.item {%s} set' % ball.id)
    lx.eval('select.type polygon')
    lx.eval('select.all')
    lx.eval('poly.subdivide flat')
    lx.eval('select.type item')
    lx.eval('select.item {%s} set' % other.id)
    note('subdivided, polygons left selected, Other selected', polygons=len(ball.geometry.polygons.selected))
    links.update([ball.id])
    note('updated with polygons selected', polygons=len(ball.geometry.polygons.selected))
    # The round trip: the file gone, so the geometry write cannot be done.
    path = links.read_tag(ball)['file']
    shaders = len(links._shaders())
    pathlib.Path(path).unlink()
    note('file deleted', status=[(r['name'], r['status']) for r in links.rows()])
    kept = ball.id
    written = links.update([ball.id])
    note('updated by the round trip', written=written, new_item=written != [kept], file_back=pathlib.Path(path).is_file(),
         shaders_before=shaders, shaders_after=len(links._shaders()), status=[(r['name'], r['status']) for r in links.rows()],
         tag=links.read_tag([i for i in modo.Scene().items('mesh') if i.name == 'Ball'][0]))
    result['done'] = True
except Exception:
    result['error'] = traceback.format_exc()
note('end')
