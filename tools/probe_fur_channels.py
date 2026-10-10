# python
"""Isolated GUI test: what a Modo Fur material is made of.

A sphere is given a material with a Fur material beside it, as Modo's own Add Layer does it. The Fur item's type, its
place in the Shader Tree and every channel it has, with its value, are written down."""
import json
import pathlib
import traceback
import lx
import modo

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/fur-channels'
out.mkdir(parents=True, exist_ok=True)
result = {}
try:
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    scene = modo.Scene()
    mesh = scene.selected[0]
    mask = scene.addItem('mask', name='Pelt')
    mask.setParent(scene.renderItem, 0)
    mask.channel('ptyp').set('Material')
    mask.channel('ptag').set('Default')
    tried = []
    for kind in ('furMaterial', 'material.fur', 'fur'):
        try:
            fur = scene.addItem(kind, name='Fur')
            fur.setParent(mask, 0)
            tried.append(kind + ': ok')
            break
        except Exception as exc:
            tried.append('%s: %s' % (kind, exc))
    result['tried'] = tried
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
    found = [item for item in scene.iterItems() if 'fur' in item.type.lower()]
    result['fur_items'] = [[item.type, item.name, item.parent.name if item.parent else None, item.parent.type if item.parent else None] for item in found]
    if found:
        fur = found[0]
        held = {}
        for name in fur.channelNames:
            try:
                value = fur.channel(name).get()
            except Exception as exc:
                value = 'unreadable: %s' % exc
            held[name] = value
        result['channels'] = held
        result['mask'] = {name: mask.channel(name).get() for name in ('ptyp', 'ptag')}
        result['children_of_mask'] = [[child.type, child.name] for child in fur.parent.children()] if fur.parent else []
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
