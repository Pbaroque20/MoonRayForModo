# python
"""Command line: a copy of MOONRAY_PROBE_SCENE whose OCIO configuration is one Modo ships (MOONRAY_PROBE_OCIO, aces by
default), for a test Modo that has not the scene's own: opened in the window, Modo asked about the missing one and
the scene never finished loading. Saved beside the scene's images' folder as PROBE_COPY; report in
test-results/ocio-copy.json. The scene itself is not touched."""
import json
import os
import pathlib
import traceback
import lx
import modo

result = {}
try:
    lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    scene = modo.Scene()
    item = scene.sceneItem
    result['before'] = {name: item.channel(name).get() for name in ('ocioConfig',) if item.channel(name) is not None}
    item.channel('ocioConfig').set(os.environ.get('MOONRAY_PROBE_OCIO', 'aces'))
    result['after'] = item.channel('ocioConfig').get()
    lx.eval('!scene.saveAs {%s} $LXOB false' % os.environ['PROBE_COPY'])
    result['saved'] = os.environ['PROBE_COPY']
except Exception:
    result['error'] = traceback.format_exc()
pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\ocio-copy.json').write_text(json.dumps(result, indent=1, default=str))
