# python
"""Command line: the car's tyre tread material (the Group Mask report: a white border where Modo blends the masked
material into the one underneath). Opens test-results/rt-car/car_aces.lxo and writes down the Shader Tree around
'tire dirt mask' (each layer's type, effect, blend, opacity, image, its UV map, alpha use, low and high values,
invert), the material the kit reads for that tag (its stack, layers and groups), and the MoonRay scene text written
for it. Writes test-results/tyre-mask/report.json and material.rdla."""
import json
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT') or r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\tyre-mask')
out.mkdir(parents=True, exist_ok=True)
report = {}
CHANNELS = ('effect', 'blend', 'opacity', 'invert', 'enable', 'ptag', 'ptyp', 'min', 'max', 'alphaMode', 'alpha', 'aa',
            'uvMap', 'projType', 'tileU', 'tileV', 'imageStack', 'lowValue', 'highValue', 'gamma', 'diffCol.R', 'diffCol.G',
            'diffCol.B', 'diffAmt', 'color.R', 'color.G', 'color.B', 'value', 'invGreen')


def described(item, depth):
    row = {'depth': depth, 'name': item.name, 'type': item.type, 'id': item.id}
    for name in CHANNELS:
        try:
            held = item.channel(name)
            if held is not None:
                row[name] = held.get()
        except Exception:
            pass
    try:
        row['links'] = [(graph, [i.name for i in item.itemGraph(graph).forward()]) for graph in ('shadeLoc', 'imageStack')
                        if item.itemGraph(graph).forward()]
    except Exception:
        pass
    return row


def walk(item, depth=0, rows=None):
    rows = [] if rows is None else rows
    rows.append(described(item, depth))
    for child in item.children():
        walk(child, depth + 1, rows)
    return rows


try:
    lx.eval('scene.open {%s} normal' % (os.environ.get('PROBE_SCENE') or r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\rt-car\car_aces.lxo'))
    scene = modo.Scene()
    masks = [i for i in scene.iterItems() if 'tire dirt mask' in i.name]
    report['found'] = [(i.name, i.type) for i in masks]
    # The material groups holding the tread's mask, whole.
    groups = []
    for item in masks:
        top = item
        while top.parent is not None and top.parent.type == 'mask' and top.parent.parent is not None and top.parent.parent.type == 'mask':
            top = top.parent
        top = top.parent if top.parent is not None and top.parent.type == 'mask' else top
        if top.id not in [g.id for g in groups]:
            groups.append(top)
    report['trees'] = [walk(group) for group in groups]
    tags = sorted({row.get('ptag') for tree in report['trees'] for row in tree if row.get('ptag')})
    report['tags'] = tags
    from moonray_modo import host, rdla
    snapshot = host.snapshot()
    report['warnings'] = [w for w in snapshot.get('warnings', []) if 'dirt' in w.lower() or 'reifen' in w.lower() or 'mask' in w.lower()]
    materials = snapshot.get('materials', {})
    kept = {}
    for tag in tags:
        if tag in materials:
            kept[tag] = materials[tag]
    report['materials'] = kept
    text = rdla.scene_text(snapshot)
    lines = text.splitlines()
    picked = [line for line in lines if any(tag in line for tag in tags)]
    (out / 'material.rdla').write_text('\n'.join(lines), encoding='utf-8')
    report['material_lines'] = picked[:40]
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str), encoding='utf-8')
