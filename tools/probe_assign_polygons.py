# python
"""Isolated GUI test: a MoonRay material assigned with polygons selected goes on those polygons only.

A cube with two polygons picked out in polygon mode takes the material on those two; the same cube in item mode, with
that selection still there but not in view, takes it on every polygon; and what the plugin reads from the scene
afterwards has each polygon wearing what it was given."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/assign-polygons'
out.mkdir(parents=True, exist_ok=True)
result = {}


def cube(name, x):
    lx.eval('select.typeFrom item')
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    for key, value in (('cenX', x), ('sizeX', 1.0), ('sizeY', 1.0), ('sizeZ', 1.0)):
        lx.eval('tool.attr prim.cube %s %s' % (key, value))
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    mesh = modo.Scene().selected[0]
    mesh.name = name
    return mesh


def tags(mesh):
    return [mesh.geometry.polygons[index].materialTag for index in range(len(mesh.geometry.polygons))]


try:
    from moonray_modo import host, materials
    scene = modo.Scene()
    first = cube('Picked', -1.0)
    scene.select(first)
    lx.eval('select.typeFrom polygon')
    lx.eval('select.drop polygon')
    for index in (0, 2):
        first.geometry.polygons[index].select()
    result['selected'] = sorted(p.index for p in first.geometry.polygons.selected)
    # Where each picked polygon is, to know them again: a polygon may change its place among the others.
    def middle(polygon):
        points = [v.position for v in polygon.vertices]
        return tuple(round(sum(p[axis] for p in points) / len(points), 4) for axis in range(3))
    wanted_places = sorted(middle(p) for p in first.geometry.polygons.selected)
    result['chosen'] = materials.chosen_polygons([first])
    made = materials.assign('DwaMetalMaterial')
    after = tags(first)
    tag = made.parent.channel('ptag').get()
    wearing = sorted(middle(first.geometry.polygons[i]) for i, t in enumerate(after) if t == tag)
    result['picked'] = {'mask': made.parent.name, 'wearing_it': len(wearing), 'the_same_polygons': wearing == wanted_places, 'others': sorted(set(t for t in after if t != tag))}
    # A second material on other polygons of the same mesh leaves the first where it was.
    scene.select(first)
    lx.eval('select.typeFrom polygon')
    lx.eval('select.drop polygon')
    first.geometry.polygons[4].select()
    second = materials.assign('DwaRefractiveMaterial')
    again = tags(first)
    other = second.parent.channel('ptag').get()
    result['second'] = {'first_still_on': sorted(middle(first.geometry.polygons[i]) for i, t in enumerate(again) if t == tag) == wanted_places,
                        'second_on': sum(t == other for t in again)}
    # In item mode a selection of polygons left from before is not in view, and the whole mesh takes the material.
    whole = cube('Whole', 1.0)
    scene.select(whole)
    lx.eval('select.typeFrom polygon')
    lx.eval('select.drop polygon')
    whole.geometry.polygons[1].select()
    lx.eval('select.typeFrom item')
    scene.select(whole)
    result['chosen_in_item_mode'] = materials.chosen_polygons([whole])
    third = materials.assign('DwaBaseMaterial')
    everything = tags(whole)
    result['whole'] = {'mask': third.parent.name, 'tags': sorted(set(everything)), 'all_wear_it': set(everything) == {third.parent.channel('ptag').get()}}
    snapshot = host.snapshot()
    import collections
    result['read_back'] = {mesh['name']: dict(collections.Counter(mesh.get('face_materials') or [mesh.get('material')])) for mesh in snapshot['meshes']}
    result['warnings'] = snapshot.get('warnings', [])
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))
