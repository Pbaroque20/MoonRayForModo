# python
"""Command line: how finely MoonRay dices a scene's displaced meshes in a final render and in a realtime preview (fine
and coarse cuts, moonlightipr_detail): each mesh's adaptive_error as rdla writes it. PROBE_SCENE the .lxo (the ocean
demo by default). Writes test-results/realtime-dicing/report.json."""
import json
import os
import pathlib
import re
import traceback
import lx

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\realtime-dicing')
out.mkdir(parents=True, exist_ok=True)
scene_path = os.environ.get('PROBE_SCENE', r'C:\Users\Raphael Tobar\MoonRayForModo\kit\MoonRayForModo\assets\library\scenes\Ocean at sunset.lxo')
report = {}
try:
    lx.eval('!scene.open {%s} normal' % scene_path)
    from moonray_modo import host, scene_setup, rdla
    scene = host.snapshot()
    scene_setup.configure(scene, scene_setup.values())
    for label, extra in (('render', {}), ('realtime fine', {'_geometry_detail': 'fine', '_realtime': True}),
                         ('realtime coarse', {'_geometry_detail': 'coarse', '_realtime': True})):
        text = rdla.scene_text(dict(scene, **extra), 960, 540, 1, 0.0)
        report[label] = re.findall(r'\["adaptive_error"\] = ([0-9.e+-]+)', text)
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
