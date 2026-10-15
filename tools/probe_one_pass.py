# python
"""Isolated GUI test: a MoonRay preview by a MoonRay of its own (not kept loaded), under uniform sampling, is one render.

The MoonRay Widget's scene is rendered at 4 samples a pixel with the kept-loaded MoonRay turned off. Each render
MoonRay is started for is written down by its samples, with the time the picture finished."""
import json
import time
import traceback
from pathlib import Path
import lx
from PySide2 import QtCore

ROOT = Path('C:/Users/Raphael Tobar/MoonRayForModo')
RUNTIME = 'C:/Users/Raphael Tobar/AppData/Roaming/Luxology/Kits/MoonRayForModo/runtime'
out = ROOT / 'test-results/one-pass'
out.mkdir(parents=True, exist_ok=True)
result = {'passes': []}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def done(*args):
    result['finished_s'] = round(time.time() - held['start'], 2)
    result['passes_left'] = list(held['renderer'].passes)
    save()
    QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))


try:
    from moonray_modo import material_preview, options
    from moonray_modo.render import Renderer
    scene = material_preview.snapshot({'color': [.6, .3, .2], 'roughness': .3}, {})
    scene['render_settings'] = options.render_values({'sampling_mode': 0})
    renderer = held['renderer'] = Renderer()
    original = renderer._begin_pass

    def begin(generation):
        result['passes'].append({'remaining_before': list(renderer.passes)})
        return original(generation)
    renderer._begin_pass = begin
    renderer.finished.connect(done)
    renderer.failed.connect(lambda message: (result.__setitem__('failed', message), done()))
    held['start'] = time.time()
    renderer.submit(scene, RUNTIME, 256, 256, 2, .2, 0, persistent_preview=False)
    result['persistent'] = renderer.active.get('persistent') if getattr(renderer, 'active', None) else None
    QtCore.QTimer.singleShot(60000, done)
except Exception:
    result['error'] = traceback.format_exc()
    save()
    lx.eval('!app.quit')
