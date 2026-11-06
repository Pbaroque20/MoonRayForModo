# python
"""Command line: why Modo draws no purple on the rebuilt tyre (tools/probe_cl_tyre_group_mask.py). Writes down the
purple group's and material's channels, every Shader Tree group whose polygon tag names the tread or that is empty,
with its place in the tree, and the tyre's own tags. Writes test-results/tyre-group-mask/channels.json."""
import json
import pathlib
import traceback
import lx
import modo

result = {}
try:
    lx.eval('scene.open {%s} normal' % r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\tyre-group-mask\tyre_group_mask.lxo')
    scene = modo.Scene()

    def channels(item):
        held = {}
        for channel in item.channels():
            try:
                value = channel.get()
                if isinstance(value, (int, float, str)):
                    held[channel.name] = value
            except Exception:
                pass
        return held
    group = next(i for i in scene.iterItems() if i.name == 'Purple Group')
    purple = next(i for i in scene.iterItems() if i.name == 'Purple')
    result['group'] = {k: v for k, v in channels(group).items() if k in ('ptag', 'ptyp', 'enable', 'opacity', 'blend', 'invert', 'submask', 'style', 'instance', 'item', 'effect')}
    result['purple'] = {k: v for k, v in channels(purple).items() if k.startswith('diff') or k in ('enable', 'opacity', 'blend', 'effect')}
    rows = []

    def walk(item, depth):
        for child in reversed(list(item.children())):
            if child.type == 'mask':
                rows.append((depth, child.name, child.channel('ptyp').get(), child.channel('ptag').get(), child.channel('enable').get()))
            walk(child, depth + 1)
    walk(scene.renderItem, 0)
    result['groups_top_first'] = [r for r in rows if 'reifen' in str(r[3]).lower() or 'laufflaeche' in str(r[3]).lower() or not r[3]]
    tyre = next(m for m in scene.items('mesh') if m.name.lower().startswith('reifen'))
    result['tyre'] = tyre.name
    tags = set()
    for polygon in tyre.geometry.polygons:
        tags.add(polygon.materialTag)
    result['tyre_tags'] = sorted(tags)
except Exception:
    result['error'] = traceback.format_exc()
pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\tyre-group-mask\channels.json').write_text(json.dumps(result, indent=1, default=str))
