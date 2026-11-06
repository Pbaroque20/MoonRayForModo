# python
"""Command line: the checker locator mismatch (test-results/layer-mask/layer_mask.lxo, made by
tools/probe_cl_layer_mask_scene.py). For each Checker: its texture locator's projection, size, position, rotation and
scale channels, its transforms' items, its world matrix as the kit reads it, and the rows the kit gives MoonRay's
ModoProceduralMap. Writes test-results/checker-locator/report.json."""
import json
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\checker-locator')
out.mkdir(parents=True, exist_ok=True)
report = {}
NAMES = ('projType', 'projAxis', 'size.X', 'size.Y', 'size.Z', 'psize', 'useRealSize', 'center', 'legacyRotation',
         'uvRotation', 'm00', 'm01', 'm02', 'm10', 'm11', 'm12', 'tileU', 'tileV')


def get(item, name):
    try:
        held = item.channel(name)
        return held.get() if held is not None else None
    except Exception as exc:
        return 'error %s' % exc


try:
    lx.eval('scene.open {%s} normal' % (os.environ.get('PROBE_SCENE') or r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\layer-mask\layer_mask.lxo'))
    scene = modo.Scene()
    from moonray_modo.host import world_matrix, channel
    from moonray_modo import procedurals
    for layer in [i for i in scene.iterItems() if i.type == 'checker']:
        row = {'layer': {n: get(layer, n) for n in ('type', 'transWidth', 'bias', 'gain', 'effect')}}
        locator = next((i for i in layer.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator'), None)
        row['locator'] = {n: get(locator, n) for n in NAMES}
        transforms = []
        for item in scene.iterItems():
            if item.type in ('translation', 'rotation', 'scale') and item.parent is None:
                pass
        try:
            for xfrm in locator.transforms:
                transforms.append((xfrm.name, xfrm.type, [xfrm.channel(a).get() for a in ('X', 'Y', 'Z')] if xfrm.channel('X') else None,
                                   get(xfrm, 'order')))
        except Exception as exc:
            transforms.append('error %s' % exc)
        row['transforms'] = transforms
        row['worldMatrix_channel'] = str(get(locator, 'worldMatrix'))
        row['world_matrix'] = list(world_matrix(locator))
        data = procedurals.solid(layer, channel, lambda l, n, d=(0, 0, 0): list(d), True, world_matrix(locator))
        row['solid_rows'] = data['rows'] if data else None
        row['solid_settings'] = data['settings'][:2] if data else None
        report[layer.name] = row
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str), encoding='utf-8')
