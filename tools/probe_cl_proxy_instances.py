# python
"""Headless: the two-proxy scene (proxy2-test.lxo) as the kit reads it: each render cache surface (item, ids, instanced,
place) and each mesh of the snapshot with every placement, written to test-results/references/instances.json."""
import json, traceback
import lx
out = {}
try:
    import os
    lx.eval('!scene.open {%s} normal' % os.path.join(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\references',
                                                       os.environ.get('SCENE', 'proxy2-test.lxo')))
    out['proxies'] = [(item.id, item.name, str(item.channel('itemRender').get()), [round(v, 3) for v in item.position.get()])
                      for item in modo.Scene().items('proxy', superType=False)] if False else None
    import modo
    from moonray_modo import evaluated, host
    data = evaluated.capture(lx.service.Selection().GetTime())
    out['captured'] = [{k: s.get(k) for k in ('id', 'source_id', 'source_item', 'instanced', 'source_instanced', 'instance_index', 'shading_scene')}
                       | {'at': [round(v, 3) for v in (s.get('matrix') or [])[12:15]] if len(s.get('matrix') or []) == 16 else s.get('matrix')}
                       for s in data['surfaces']]
    evaluated.proxies(data, modo.Scene(), lx.service.Selection().GetTime(), [])
    out['after_proxies'] = [(s['id'], s['source_item'], s.get('instanced')) for s in data['surfaces']]
    snap = host.snapshot()
    out['meshes'] = [{'identity': m.get('identity'), 'matrix': m.get('matrix'),
                      'instances': m.get('instances')} for m in snap.get('meshes', [])]
except Exception:
    out['error'] = traceback.format_exc()
open(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\references\instances.json', 'w').write(json.dumps(out, indent=1, default=str))
