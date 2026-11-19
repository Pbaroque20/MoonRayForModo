# python
"""Command line: the tread's material stack as the plugin reads it (host's material_stack) in the tyre scene with its
Group Mask at Normal (test-results/tyre-as-saved-normal/tyre_group_mask.lxo): each row bottom first, its colour,
diffuse amount and layers, and what Modo's Shader Tree holds below the tread's group. Written to
test-results/tyre-as-saved-normal/stack.json.  MOONRAY_PROBE_SCENE: another scene."""
import json
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\tyre-as-saved-normal')
scene_path = os.environ.get('MOONRAY_PROBE_SCENE', str(out / 'tyre_group_mask.lxo'))
report = {}
try:
    lx.eval('scene.open {%s} normal' % scene_path)
    scene = modo.Scene()
    from moonray_modo.layers import ordered
    report['tree_top_first'] = []
    for item in ordered(scene.renderItem):
        row = {'name': item.name, 'type': item.type}
        for name in ('effect', 'ptag', 'ptyp', 'enable', 'diffCol.R', 'diffCol.G', 'diffCol.B', 'diffAmt', 'opacity', 'blend'):
            try:
                channel = item.channel(name)
                if channel is not None:
                    row[name] = channel.get()
            except Exception:
                pass
        parent = item.parent
        row['parent'] = parent.name if parent is not None else None
        report['tree_top_first'].append(row)
    from moonray_modo import host
    data = host.snapshot()
    warnings = data.get('warnings', [])
    if data is not None:
        material = data['materials'].get('Reifen_Laufflaeche')
        stack = material.get('material_stack') if material else None
        report['stack_bottom_first'] = [{'name': row.get('name'), 'color': row.get('raw_color', row.get('color')), 'diffuse_amount': row.get('diffuse_amount'),
                                         'groups': [(g.get('name'), g.get('id')) for g in row.get('material_groups', [])],
                                         'layers': [(l.get('kind'), l.get('effect'), l.get('blend'), l.get('opacity'), [g.get('name') for g in l.get('groups', [])])
                                                    for l in row.get('layers', [])]} for row in (stack or [])]
    report['warnings'] = [str(w) for w in warnings]
except Exception:
    report['error'] = traceback.format_exc()
(out / 'stack.json').write_text(json.dumps(report, indent=1, default=str), encoding='utf-8')
