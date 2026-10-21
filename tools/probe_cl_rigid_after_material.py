# python
"""Command-line test: whether a scene (MOONRAY_PROBE_SCENE) holds still for motion blur (incremental.rigid) before and
after a sphere is added and given a MoonRay material, and if not, what stops it: an item kind not taken to be steady,
a deformer, a projected texture, or a mesh not standing with its item. Writes test-results/cl-export/prep/rigid.json."""
import json
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\cl-export\prep\rigid.json')
result = {}


def why(label):
    from moonray_modo import host, incremental
    from moonray_modo.coordinates import descriptors
    scene = modo.Scene()
    snapshot = host.snapshot(evaluated_geometry=False)
    service = lx.service.Scene()
    kinds = [service.ItemTypeLookup(name) for name in ('light', 'textureLayer')]
    unsteady = sorted({item.type for item in scene.iterItems() if not (item.type in incremental.STEADY or item.type.startswith(('material.', 'moonray.'))
                       or any(item.TestType(each) for each in kinds))})
    result[label] = {'rigid': incremental.rigid(scene, snapshot), 'unsteady_kinds': unsteady, 'deformers': incremental.deformers(scene),
                     'projected': sorted({d.get('projection') for d in descriptors(snapshot.get('materials') or {}).values() if d.get('projection', 'uv') != 'uv'}),
                     'stands': incremental.stands_with_items(scene, snapshot)}
    out.write_text(json.dumps(result, indent=1))


try:
    lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    why('opened')
    lx.eval('layer.new')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.doApply')
    lx.eval('tool.set prim.sphere off')
    why('sphere added')
    lx.eval('select.item {%s} set' % modo.Scene().selected[-1].id)
    lx.eval('@{%s}' % r'C:\Users\Raphael Tobar\MoonRayForModo\tools\probe_assign_material_step.py')
    why('material assigned')
except Exception:
    result['error'] = traceback.format_exc()
out.write_text(json.dumps(result, indent=1))
