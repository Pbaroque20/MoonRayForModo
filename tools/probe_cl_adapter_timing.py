# python
"""Command-line test: where the geometry adapter's time goes (MOONRAY_PROBE_SCENE): Modo's render cache evaluation,
listing its surfaces, loading and fetching their segments, and writing them out, as the adapter itself times them;
and the plugin's call around it. Writes test-results/cl-export/prep/adapter.json."""
import json
import os
import pathlib
import time
import traceback
import lx

result = {}
try:
    lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    from moonray_modo import evaluated
    for attempt in range(2):
        began = time.perf_counter()
        data = evaluated.capture(lx.service.Selection().GetTime())
        result['capture_%d_seconds' % attempt] = round(time.perf_counter() - began, 2)
        result['adapter_%d' % attempt] = {'evaluate_list_prototypes': data.get('timing'), 'load_fetch_write': data.get('handing')}
    result['surfaces'] = len(data.get('surfaces', []))
    result['prototypes'] = len(data.get('prototypes', {}))
    result['segments'] = sum(len(p.get('segments', [])) for p in data.get('prototypes', {}).values())
except Exception:
    result['error'] = traceback.format_exc()
pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\cl-export\prep\adapter.json').write_text(json.dumps(result, indent=1))
