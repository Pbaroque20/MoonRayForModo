# python
"""The Hyundai's tire mask: the Shader Tree layer whose name ends in "_checkHere", the group it sits in, and every
layer beside and under it, with what decides how they mix (effect, blend, opacity, invert, the image and its UVs).
Writes test-results/tire-mask/tree.json.  MOONRAY_PROBE_SCENE: the scene."""
import json
import os
import pathlib

import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\tire-mask')
out.mkdir(parents=True, exist_ok=True)
scene_path = os.environ.get('MOONRAY_PROBE_SCENE', r'C:\Users\Raphael Tobar\Downloads\Hyundai N Vision 74\Hyundai N Vision 74_Studio_MoonRay.lxo')
lx.eval('scene.open {%s} normal' % scene_path)
scene = modo.Scene()
CHANNELS = ('enable', 'opacity', 'blend', 'effect', 'invert', 'ptag', 'ptyp', 'textureLayer.gradient', 'minLevel', 'maxLevel',
            'lowValue', 'highValue', 'swizzling', 'rgba', 'alphaMode', 'aa', 'pixBlend')


def channels(item):
    held = {}
    for name in CHANNELS:
        try:
            value = item.channel(name).get() if item.channel(name) is not None else None
        except Exception:
            value = None
        if value is not None:
            held[name] = value
    return held


def describe(item, depth=0):
    entry = {'name': item.name, 'id': item.id, 'type': item.type, 'channels': channels(item)}
    if item.type == 'imageMap':
        try:
            clip = [c for c in item.itemGraph('shadeLoc').forward()] if hasattr(item, 'itemGraph') else []
        except Exception:
            clip = []
        entry['locators'] = [c.name for c in clip]
        try:
            entry['clip'] = lx.eval('texture.setIMap ?') if False else None
        except Exception:
            pass
    children = []
    try:
        children = list(item.children())
    except Exception:
        pass
    if children and depth < 4:
        entry['children'] = [describe(child, depth + 1) for child in children]
    return entry


found = [item for item in scene.items() if item.name.endswith('_checkHere') or '_checkHere' in item.name]
report = {'scene': scene_path, 'found': []}
for item in found:
    parents = []
    walk = item.parent
    while walk is not None:
        parents.append('%s (%s)' % (walk.name, walk.type))
        walk = walk.parent
    group = item.parent
    report['found'].append({'item': describe(item), 'parents': parents,
                            'siblings_top_to_bottom': [describe(child) for child in (group.children() if group is not None else [])]})
(out / 'tree.json').write_text(json.dumps(report, indent=1, default=str), encoding='utf-8')
print('found', len(found))
