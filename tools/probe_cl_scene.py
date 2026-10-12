# python
"""Command-line test: what the plugin reads out of a scene, with no window.

Opens the scene in MOONRAY_PROBE_SCENE (else makes a cube and a light), reads it as the preview would, and writes
down what came of it: how long it took, the meshes, lights and environments, and each mesh's visibility. Then, if
MOONRAY_PROBE_EYES is set, switches a light's and an environment's eye off and reads again."""
import json
import os
import pathlib
import time
import traceback
import lx
import modo

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/cl-scene'
out.mkdir(parents=True, exist_ok=True)
result = {'readings': []}


def read(name):
    from moonray_modo import host
    t = time.perf_counter()
    scene = host.snapshot()
    result['readings'].append({'reading': name, 'seconds': round(time.perf_counter() - t, 3), 'meshes': len(scene.get('meshes', [])),
                               'lights': [str(l.get('name') or l.get('identity')) for l in scene.get('lights', [])],
                               'environments': [str(e.get('name') or e.get('identity')) for e in scene.get('environments', [])],
                               'evaluated': scene.get('_evaluated_data') is not None,
                               'visibility': sorted({str(m.get('visibility')) for m in scene.get('meshes', [])}), 'size': [scene.get('width'), scene.get('height')]})
    return scene


try:
    if os.environ.get('MOONRAY_PROBE_SCENE'):
        lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    else:
        lx.eval('item.create mesh')
        lx.eval('tool.set prim.cube on')
        lx.eval('tool.apply')
        lx.eval('tool.set prim.cube off')
    result['headless'] = True
    read('first')
    read('again')
    if os.environ.get('MOONRAY_PROBE_EYES'):
        document = modo.Scene()
        lights = [item for item in document.items('light', superType=True)]
        environments = document.items('environment', superType=False)
        result['items'] = {'lights': [l.name for l in lights], 'environments': [e.name for e in environments]}
        for item in lights[:1] + environments[:1]:
            item.channel('visible').set('off')
        read('a light and an environment with their eye off')
        for item in lights[:1] + environments[:1]:
            item.channel('render').set('on')
        read('the same, set to Render: Yes')
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
