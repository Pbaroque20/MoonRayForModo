# python
"""Headless: the two-proxy scene (proxy2-test.lxo, from probe_proxy_render.py) read by the kit several times in a row:
evaluated.proxies (the adapter's MR_foreign_layers handing each proxy's scene to a Python listener), then whole
snapshots. Each step is written to test-results/references/repeat.json before the next, so that a crash shows how far it
got. Run under the debug heap (scratchpad debug_modo.py --stdin) to see a bad free where it happens."""
import gc
import json
import pathlib
import traceback
import lx

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\references')
result = {'steps': []}


def save():
    (out / 'repeat.json').write_text(json.dumps(result, indent=1, default=str))


def step(text):
    result['steps'].append(text); save()


try:
    lx.eval('!scene.open {%s} normal' % (out / 'proxy2-test.lxo'))
    import modo
    from moonray_modo import evaluated, host
    scene = modo.Scene()
    import os
    for attempt in range(int(os.environ.get('PROXIES', 4))):
        data = evaluated.capture(lx.service.Selection().GetTime())
        warnings = []
        evaluated.proxies(data, scene, lx.service.Selection().GetTime(), warnings)
        step('proxies %d: %d surfaces, scenes %s, shaded %s, warnings %s' % (
            attempt, len(data['surfaces']), [s.scene.Filename() for s in evaluated._FOREIGN],
            [(s['source_item'], s.get('shading_scene')) for s in data['surfaces']], warnings))
        gc.collect()
    for attempt in range(int(os.environ.get('SNAPSHOTS', 3))):
        snap = host.snapshot()
        materials = snap.get('materials', {})
        step('snapshot %d: %s, warnings %s' % (attempt, [(m.get('identity'), (materials.get(m.get('material')) or {}).get('color'))
                                                         for m in snap.get('meshes', [])],
                                                [w for w in snap.get('warnings', []) if 'roxy' in w]))
        gc.collect()
    if __import__('os').environ.get('RELEASE'):
        evaluated.release_proxies()
        gc.collect()
        step('released')
except Exception:
    result['error'] = traceback.format_exc()
save()
