# python
"""Command-line test: an environment HDRI flipped left to right (its Texture Locator's Horizontal Wrap -1) is captured
as the image mirrored at its full size, not baked with the layered environments. Grass's sky by default (PROBE_SCENE).
Writes test-results/environment-flip/report.json: the environments captured before and after the flip."""
import json
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\environment-flip')
out.mkdir(parents=True, exist_ok=True)
SCENE = os.environ.get('PROBE_SCENE', r'C:\Users\Raphael Tobar\Downloads\Grass\wildGreen_Patches_bundled.lxo')
result = {'scene': SCENE}


def environments():
    from moonray_modo.animation import capture_frame
    snapshot = capture_frame(lx.service.Selection().GetTime(), False, False, float(modo.Scene().fps), preview=True)
    return [{k: v for k, v in e.items() if k in ('kind', 'path', 'scale', 'transformed', 'mirrored_from')}
            | ({'layers': [{k: v for k, v in l.items() if k in ('kind', 'path', 'scale', 'transformed')} for l in e['layers']]} if e.get('layers') else {})
            for e in snapshot.get('environments', [])], [w for w in snapshot.get('warnings', []) if 'nvironment' in w]


try:
    lx.eval('!scene.open {%s} normal' % SCENE)
    result['before'] = environments()
    scene = modo.Scene()
    flipped = []
    for layer in scene.items('imageMap'):
        locator = next((i for i in layer.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator'), None)
        if locator is not None and locator.channel('projType').get() == 'spherical':
            locator.channel('wrapU').set(-1.0)
            flipped.append(layer.name)
    result['flipped'] = flipped
    result['after'] = environments()
except Exception:
    result['error'] = traceback.format_exc()[-2000:]
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
