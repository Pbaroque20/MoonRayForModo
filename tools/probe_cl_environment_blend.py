# python
"""Command line: how long a scene's layered environment takes to be made (environment_layers.texture), with a cache
folder of its own (MOONRAY_PROBE_CACHE, emptied by the caller), profiled. Writes test-results/environment-blend/
(report.json, profile.txt, environment.json: the environments as the kit reads them)."""
import cProfile
import io
import json
import os
import pathlib
import pstats
import time
import traceback
import lx

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\environment-blend')
out.mkdir(parents=True, exist_ok=True)
result = {}
try:
    lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    import modo
    from moonray_modo import cache_folder, environments, environment_layers
    if os.environ.get('MOONRAY_PROBE_CACHE'):
        cache_folder._HELD['root'] = pathlib.Path(os.environ['MOONRAY_PROBE_CACHE'])
    warnings = []
    found = environments.collect(modo.Scene(), warnings)
    (out / 'environment.json').write_text(json.dumps(found, indent=1, default=str))
    result['environments'] = [{'layers': [(l.get('kind'), l.get('effect'), l.get('blend')) for l in e.get('layers', [])]}
                              for e in found]
    for index, environment in enumerate(found):
        if not environment.get('layers'):
            continue
        profile = cProfile.Profile()
        began = time.perf_counter()
        profile.enable()
        made = environment_layers.texture(environment)
        profile.disable()
        result.setdefault('seconds', []).append(round(time.perf_counter() - began, 2))
        result.setdefault('made', []).append(str(made))
        text = io.StringIO()
        pstats.Stats(profile, stream=text).sort_stats('cumulative').print_stats(25)
        (out / ('profile-%d.txt' % index)).write_text(text.getvalue())
    result['warnings'] = warnings
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
