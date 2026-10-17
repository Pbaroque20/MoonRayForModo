# python
"""Isolated GUI test: what Modo's camera stereo and overscan channels are.

For the render camera, each of stereo, stereoEye, stereoComp, ioDist, convDist and overscan is written down with its
type, default value and named values (text hints); then overscan is set and the scene read as for a render, to see
what the camera's film and resolution become."""
import json
import pathlib
import traceback
import lx
import lxu.object
import modo

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/camera-channels'
out.mkdir(parents=True, exist_ok=True)
result = {}

try:
    scene = modo.Scene()
    camera = scene.renderCamera
    item = lxu.object.Item(camera)
    for name in ('stereo', 'stereoEye', 'stereoComp', 'ioDist', 'convDist', 'overscan', 'filmFit', 'apertureX', 'apertureY'):
        entry = {}
        try:
            index = item.ChannelLookup(name)
            entry['type'] = item.ChannelType(index)
            entry['value'] = camera.channel(name).get()
            try:
                hints = item.ChannelHints(index)
                entry['hints'] = [(hints.Name(i), hints.Value(i)) for i in range(64) if hints.Name(i)]
            except Exception as exc:
                entry['hints'] = str(exc)
        except Exception:
            entry['error'] = traceback.format_exc().splitlines()[-1]
        result[name] = entry
    render = scene.renderItem
    result['render'] = {name: render.channel(name).get() for name in ('resX', 'resY') if render.channel(name)}
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
