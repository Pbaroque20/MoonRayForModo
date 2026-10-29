# python
"""Command-line test: the layers that apply to each surface of MOONRAY_PROBE_SCENE (evaluated.assign_materials), worked
out by the adapter (MR_shader_stacks) and by Python's rule, must be the same, surface for surface, and so must the
materials made of them; and how long each takes, and a reading whose Shader Tree is as it was (shading_kept). Writes
MOONRAY_PROBE_OUT/stacks.json."""
import copy
import json
import os
import pathlib
import time
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('MOONRAY_PROBE_OUT', 'test-results/cl-export/stacks'))
out.mkdir(parents=True, exist_ok=True)
result = {}
try:
    lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    from moonray_modo import evaluated
    data = evaluated.capture(lx.service.Selection().GetTime())
    scene = modo.Scene()
    native = evaluated.native_stacks
    readings = {}
    for name, use in (('python', False), ('native', True), ('kept', True)):
        held = copy.deepcopy(data)
        evaluated.native_stacks = native if use else (lambda scene, surfaces: None)
        warnings = []
        began = time.perf_counter()
        materials = evaluated.assign_materials(held, scene, warnings, shading_kept=(name == 'kept'))
        result[name + '_seconds'] = round(time.perf_counter() - began, 3)
        readings[name] = (held, materials, warnings)
    evaluated.native_stacks = native
    result['native_answered'] = native(scene, copy.deepcopy(data)['surfaces'][:1] and [dict(s, source_material=s['material'], source_layers=s['layers']) for s in data['surfaces'][:1]]) is not None
    base_held, base_materials, base_warnings = readings['python']
    for name in ('native', 'kept'):
        held, materials, warnings = readings[name]
        differ = [i for i, (a, b) in enumerate(zip(base_held['surfaces'], held['surfaces']))
                  if a['layers'] != b['layers'] or a['material'] != b['material']]
        result[name] = {'surfaces_differ': len(differ), 'first': [(base_held['surfaces'][i]['layers'], held['surfaces'][i]['layers'],
                        base_held['surfaces'][i]['material'], held['surfaces'][i]['material']) for i in differ[:3]],
                        'materials_same': json.dumps(materials, sort_keys=True, default=str) == json.dumps(base_materials, sort_keys=True, default=str),
                        'warnings_same': warnings == base_warnings}
    result['surfaces'] = len(data['surfaces'])
    result['stacks'] = len(base_materials)
except Exception:
    result['error'] = traceback.format_exc()
(out / 'stacks.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
