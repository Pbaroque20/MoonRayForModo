# python
"""Command-line test: what is left out of a scene is said in Notices, and a group mask set to Normal Multiply stops nothing.
Makes a cube under a group mask with that blend, a material of a kind the plugin does not read, and a Principled material with
sheen; reads it as the preview does, and packs it for MoonLightIPR. Writes test-results/cl-left-out/report.json."""
import json
import pathlib
import traceback
import lx
import modo

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/cl-left-out'
out.mkdir(parents=True, exist_ok=True)
result = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


try:
    from moonray_modo import host, left_out
    scene = modo.Scene()
    mesh = scene.addMesh('Cube')
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.reset')
    lx.eval('tool.doApply')
    lx.eval('tool.set prim.cube off')
    scene.addItem('sunLight')
    render = scene.renderItem
    group = scene.addItem('mask', name='Group')
    group.setParent(render, render.childCount())
    material = scene.addItem('advancedMaterial', name='Velvet')
    material.setParent(group, 0)
    material.channel('brdfType').set('principled')
    material.channel('sheen').set(.5)
    group.channel('blend').set('normalmult')
    result['blend set'] = group.channel('blend').get()
    for kind in ('unrealShader', 'matcapShader', 'material.thinfilm'):
        try:
            held = scene.addItem(kind, name='Unread ' + kind)
            held.setParent(render, 0)
            result.setdefault('made', []).append(held.type)
        except Exception as exc:
            result.setdefault('could not make', {})[kind] = str(exc)
    read = host.snapshot()
    result['evaluated'] = read.get('_evaluated_data') is not None
    result['materials'] = {str(tag): {'sheen': held.get('sheen'), 'groups': [g.get('blend') for g in held.get('material_groups') or []],
                                      'stack groups': [[g.get('blend') for g in row.get('material_groups') or []] for row in held.get('material_stack') or []]}
                           for tag, held in read['materials'].items()}
    result['notices'] = [str(line) for line in read.get('warnings', [])]
    result['moonlightipr notices'] = left_out.moonlightipr(read)
    result['done'] = True
except Exception:
    result['error'] = traceback.format_exc()
save()
