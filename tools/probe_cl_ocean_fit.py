# python
"""Command line: a scene's Ocean nodes as the kit fits them (ocean.fitted): each node's own settings, the meshes' UV span
in metres, and the size and repeat it is given, with the waves' height for its wind. PROBE_SCENE the .lxo. Writes
test-results/ocean-fit/report.json."""
import json
import os
import pathlib
import traceback
import lx

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\ocean-fit')
out.mkdir(parents=True, exist_ok=True)
report = {}
try:
    lx.eval('!scene.open {%s} normal' % os.environ['PROBE_SCENE'])
    from moonray_modo import host, scene_setup, ocean, face_tags
    scene = host.snapshot()
    scene_setup.configure(scene, scene_setup.values())
    fitted = ocean.fitted(scene)
    for tag, material in (scene.get('materials') or {}).items():
        for row in material.get('material_stack') or [material]:
            for key, node in ((row.get('node_graph') or {}).get('nodes') or {}).items():
                if node.get('type') in ('ocean', 'ocean_foam'):
                    after = None
                    for held in fitted['materials'][tag].get('material_stack') or [fitted['materials'][tag]]:
                        after = ((held.get('node_graph') or {}).get('nodes') or {}).get(key, {}).get('parameters')
                    value = ocean.settings(after or {})
                    report['%s / %s' % (tag, key)] = {'own': node.get('parameters'), 'fitted': after,
                                                      'wave height spread m': value['wave_height'] * 0.21 * value['wind_speed'] ** 2 / 9.81 / 4,
                                                      'reach m': ocean.reach(value)}
    report['meshes'] = [{'name': m.get('name'), 'tags': sorted(face_tags.worn(m)), 'uv metres': ocean.uv_metres(m)} for m in scene.get('meshes', [])]
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
