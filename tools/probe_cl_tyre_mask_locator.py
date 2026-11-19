# python
"""Command line: in the tyre Group Mask scene (tools/probe_cl_tyre_group_mask.py), the mask layer's texture locator
(projection, UV map, tiling) and every tyre mesh's UV maps; and the Purple Group's own channels. Written to
test-results/tyre-group-mask/locator.json."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\tyre-group-mask')
report = {}
try:
    lx.eval('scene.open {%s} normal' % str(out / 'tyre_group_mask.lxo'))
    scene = modo.Scene()
    image = next(i for i in scene.iterItems() if i.type == 'imageMap' and '_checkHere' in i.name)
    locators = [i for i in scene.iterItems() if i.type == 'txtrLocator' and '_checkHere' in i.name]
    held = {}
    for locator in locators:
        values = {}
        for name in ('projType', 'projAxis', 'uvMap', 'tileU', 'tileV', 'wrapU', 'wrapV', 'm00', 'useUV'):
            try:
                channel = locator.channel(name)
                values[name] = channel.get() if channel is not None else None
            except Exception as exc:
                values[name] = 'error %s' % exc
        held[locator.name] = values
    report['locators'] = held
    group = image.parent
    report['group'] = {name: (group.channel(name).get() if group.channel(name) is not None else None)
                       for name in ('enable', 'opacity', 'blend', 'invert', 'ptag', 'ptyp', 'effect', 'submask', 'alphaType')}
    report['image'] = {name: (image.channel(name).get() if image.channel(name) is not None else None)
                       for name in ('enable', 'opacity', 'blend', 'invert', 'effect', 'alpha', 'rgba', 'swizzling', 'min', 'max')}
    report['meshes'] = {}
    for mesh in scene.items('mesh'):
        try:
            report['meshes'][mesh.name] = [m.name for m in mesh.geometry.vmaps.uvMaps]
        except Exception as exc:
            report['meshes'][mesh.name] = 'error %s' % exc
except Exception:
    report['error'] = traceback.format_exc()
(out / 'locator.json').write_text(json.dumps(report, indent=1, default=str), encoding='utf-8')
