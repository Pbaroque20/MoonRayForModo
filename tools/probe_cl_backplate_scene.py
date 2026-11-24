# python
"""Command line: a scene with a Backplate item (PROBE_SCENE) read as a MoonRay render reads it (host.snapshot), and what
the Backplate made of it written to PROBE_OUT (json): the item's settings, the environments with the rays each is seen
by, the Backplate's meshes and materials (catcher settings, emission), and the notices. With PROBE_RDLA set, the scene
as MoonRay is given it is written there too."""
import json
import os
import pathlib
import traceback
import lx

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\backplate-scene.json'))
out.parent.mkdir(parents=True, exist_ok=True)
report = {}
try:
    lx.eval('!scene.open {%s} normal' % os.environ['PROBE_SCENE'])
    from moonray_modo import host, entities, native
    report['switches'] = {'backplate': native.backplate(), 'catcher_runtime': native.shadow_catcher_runtime(), 'glass_alpha': native.glass_alpha()}
    import modo
    scene = modo.Scene()
    items = []
    for item in scene.items(entities.item_type('BackplateEnvironment')):
        items.append({'name': item.name, 'values': {key: str(item.channel(channel).get()) for key, channel, *_ in entities.channels('BackplateEnvironment')}})
    report['items'] = items
    snap = host.snapshot()
    report['environments'] = [{k: e.get(k) for k in ('name', 'kind', 'path', 'intensity', 'camera', 'indirect', 'reflection', 'refraction', 'backplate')}
                              for e in snap.get('environments') or []]
    report['backplate_meshes'] = [{k: m.get(k) for k in ('name', 'material', 'visibility')} | {'faces': len(m.get('faces') or [])}
                                  for m in snap.get('meshes') or [] if m.get('_backplate') or m.get('_catcher_done')]
    report['backplate_materials'] = {tag: {'shadow_catcher': m.get('shadow_catcher'),
                                           'inputs': (m.get('node_graph') or {}).get('nodes', {}).get('surface', {}).get('inputs'),
                                           'parameters': (m.get('node_graph') or {}).get('nodes', {}).get('surface', {}).get('parameters')}
                                     for tag, m in (snap.get('materials') or {}).items() if tag.startswith('|backplate|')}
    report['warnings'] = list(snap.get('warnings') or [])
    if os.environ.get('PROBE_RDLA'):
        from moonray_modo import rdla
        pathlib.Path(os.environ['PROBE_RDLA']).write_text(rdla.scene_text(snap, output_file=os.environ['PROBE_RDLA'].replace('.rdla', '.exr')),
                                                          encoding='utf-8')
except Exception:
    report['error'] = traceback.format_exc()
out.write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
