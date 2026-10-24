# python
"""Command-line test: every texture layer type Modo 16.1 has (the item types under textureLayer), and for each the
channels a new layer of it carries with their defaults, for translating Modo's procedural textures to MoonRay.
Writes test-results/cl-export/prep/texture_kinds.json."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\cl-export\prep\texture_kinds.json')
result = {'kinds': {}}
COMMON = {'enable', 'opacity', 'blend', 'invert', 'effect', 'gldisp', 'ignSclGrp', 'filter', 'render'}
try:
    lx.eval('scene.new')
    scene = modo.Scene()
    service = lx.service.Scene()
    texture = service.ItemTypeLookup('textureLayer')
    names = []
    for index in range(service.ItemTypeCount()):
        kind = service.ItemTypeByIndex(index)
        try:
            name = service.ItemTypeName(kind)
        except Exception:
            continue
        if kind != texture and service.ItemTypeTest(kind, texture):
            names.append(name)
    result['names'] = sorted(names)
    for name in sorted(names):
        try:
            item = scene.addItem(name)
            values = {}
            for index in range(item.internalItem.ChannelCount()):
                channel = item.internalItem.ChannelName(index)
                if channel in COMMON:
                    continue
                try:
                    value = item.channel(channel).get()
                except Exception:
                    value = None
                values[channel] = value if isinstance(value, (int, float, str, type(None))) else str(value)
            result['kinds'][name] = values
            scene.removeItems(item)
        except Exception as error:
            result['kinds'][name] = 'cannot add: %s' % error
except Exception:
    result['error'] = traceback.format_exc()
out.write_text(json.dumps(result, indent=1, default=str))
