# python
"""Command line: every channel of the rebuilt tyre's tread layers (test-results/tyre-group-mask/tyre_group_mask.lxo):
Dirt_for_tread, the tire dirt mask image, Purple, Purple Group and the tread's material group, with each item's graph
links (shadeLoc, imageStack and any other it has). Writes test-results/tyre-group-mask/dirt_channels.json."""
import json
import pathlib
import traceback
import lx
import modo

result = {}
try:
    lx.eval('scene.open {%s} normal' % r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\tyre-group-mask\tyre_group_mask.lxo')
    scene = modo.Scene()
    names = ('Dirt_for_tread (Image)', 'Purple', 'Purple Group', 'Reifen_Laufflaeche (Material)', 'Material (2)')
    items = [i for i in scene.iterItems() if i.name in names or i.name.startswith('tire dirt mask')]
    for item in items:
        held = {}
        for c in item.channels():
            try:
                v = c.get()
                held[c.name] = v if isinstance(v, (int, float, str)) else str(type(v).__name__)
            except Exception as exc:
                held[c.name] = 'error'
        links = {}
        for graph in ('shadeLoc', 'imageStack', 'parent', 'deformers', 'chanLinks', 'txtrLocator'):
            try:
                ahead = [i.name for i in item.itemGraph(graph).forward()]
                behind = [i.name for i in item.itemGraph(graph).reverse()]
                if ahead or behind:
                    links[graph] = {'forward': ahead, 'reverse': behind}
            except Exception:
                pass
        result[item.name] = {'type': item.type, 'id': item.id, 'parent': item.parent.name if item.parent else None,
                             'links': links, 'channels': held}
except Exception:
    result['error'] = traceback.format_exc()
pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\tyre-group-mask\dirt_channels.json').write_text(json.dumps(result, indent=1, default=str))
