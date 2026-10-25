# python
"""Command-line test: every channel of Enhance: Modo's Process textures and of Modo's other val.* textures (Gabor and
Poisson noise, Curvature, Surface Probe, Wireframe), with its type and value on a new layer, for writing them as MoonRay
shaders. Writes test-results/cl-export/prep/process_channels.json."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\cl-export\prep\process_channels.json')
KINDS = ('val.Process_EasyGrad.RJJ', 'val.Process_RegionalHSV.RJJ', 'val.noise.gabor', 'val.noise.poisson', 'val.RTCurvature',
         'val.surfaceprobe', 'val.wireframe')
result = {}
try:
    lx.eval('scene.new')
    scene = modo.Scene()
    for kind in KINDS:
        found = []
        try:
            item = scene.addItem(kind)
            raw = item.internalItem
            for index in range(raw.ChannelCount()):
                name = raw.ChannelName(index)
                entry = {'name': name, 'type': raw.ChannelType(index)}
                try:
                    entry['storage'] = raw.ChannelStorageType(index)
                except Exception:
                    pass
                try:
                    entry['value'] = item.channel(name).get()
                except Exception as exc:
                    entry['value'] = 'unreadable: %s' % exc
                try:
                    hints = raw.ChannelIntHint(index)
                    if hints:
                        entry['hints'] = [list(h) if isinstance(h, (list, tuple)) else str(h) for h in hints]
                except Exception:
                    pass
                found.append(entry)
        except Exception:
            found = traceback.format_exc()
        result[kind] = found
except Exception:
    result['error'] = traceback.format_exc()
out.write_text(json.dumps(result, indent=1, default=str))
