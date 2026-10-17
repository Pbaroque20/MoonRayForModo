# python
"""Isolated GUI test: a MoonRay mesh full of fog (a volume and no surface) imported, and written back out for MoonRay.

The plan of test-results/rdl-volume/fog.rdla (made outside Modo into plan.json) is applied; the scene is then captured
as for a render and saved as the plugin would give it to MoonRay (imported.rdla, rendering to imported.exr), to be
rendered outside and set beside MoonRay's render of the original."""
import json
import pathlib
import traceback
import lx

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/rdl-volume'
result = {}

try:
    from moonray_modo import host, properties, rdla
    from moonray_modo import rdl_import
    lx.eval('scene.new')
    data = json.loads((out / 'plan.json').read_text())
    result['import'] = rdl_import.apply(data)
    snapshot = host.snapshot()
    result['entities'] = [(e.get('name'), e.get('class'), e.get('identity')) for e in snapshot.get('entities') or []]
    result['materials'] = {tag: {k: v for k, v in held.items() if k in ('name', 'moonray_volume', 'volume_only')}
                           for tag, held in snapshot['materials'].items()}
    snapshot['render_settings'] = properties.scene_settings().get('render', {})
    # As the import set it: Modo's environment kept out of MoonRay's picture.
    snapshot['environments'] = []
    snapshot['scene_variables'] = properties.scene_settings().get('scene_variables', {})
    (out / 'snapshot.json').write_text(json.dumps(snapshot, default=str))
    text = rdla.scene_text(snapshot, 320, 180, 2, 0.0, str(out / 'imported.exr'))
    (out / 'imported.rdla').write_text(text, encoding='utf-8')
    result['volume_lines'] = [line.strip() for line in text.splitlines() if line.startswith('volumes[') or '= nil' in line]
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
