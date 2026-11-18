# python
"""Command-line test: what the plugin reads of the item-mask scene (tools/probe_cl_item_mask_kinds.py): for each surface,
the layers Modo's render cache lists, the layers the adapter says apply (MR_shader_stacks) and the material it gets.
Writes test-results/item-mask-kinds/stacks.json, and the scene exported as the plugin writes it (reopened.rdla;
python_rule.rdla with PROBE_PYTHON_RULE set, where Python's rule is used in place of the adapter's)."""
import json
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\item-mask-kinds')
result = {}
try:
    lx.eval('scene.open {%s} normal' % (out / 'item_masks.lxo'))
    scene = modo.Scene()
    names = {item.id: '%s (%s)' % (item.name, item.type) for item in scene.items()}
    from moonray_modo import host, evaluated
    # PROBE_PYTHON_RULE set: the adapter is not asked, and Python's own rule (evaluated.assign_materials) decides; the
    # export is then python_rule.rdla.
    python_rule = bool(os.environ.get('PROBE_PYTHON_RULE'))
    if python_rule:
        evaluated.native_stacks = lambda *args, **kwargs: None
    snapshot = host.snapshot()
    data = snapshot.get('_evaluated_data') or {}
    surfaces = data.get('surfaces', [])
    result['evaluated'] = bool(surfaces)
    asked = evaluated.native_stacks(scene, surfaces) if surfaces else None
    result['adapter answered'] = asked is not None
    rows = []
    for index, surface in enumerate(surfaces):
        rows.append({'item': names.get(surface.get('source_item'), surface.get('source_item')),
                     'material tag': surface.get('source_material'),
                     'listed': [names.get(i, i) for i in surface.get('source_layers', [])],
                     'adapter': [names.get(i, i) for i in asked[index]] if asked else None,
                     'kept': [names.get(i, i) for i in surface.get('layers', [])],
                     'material': surface.get('material')})
    result['surfaces'] = rows
    result['warnings'] = snapshot.get('warnings', [])
    from moonray_modo import scene_export
    warnings = []
    scene_export.export({'path': out / ('python_rule.rdla' if python_rule else 'reopened.rdla'), 'format': 'rdla', 'outputs': False, 'collect': False, 'frames': False}, warnings)
    result['export warnings'] = warnings
except Exception:
    result['error'] = traceback.format_exc()
(out / 'stacks.json').write_text(json.dumps(result, indent=1, default=str))
