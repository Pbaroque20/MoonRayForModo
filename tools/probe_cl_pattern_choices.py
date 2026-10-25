# python
"""Command-line test: the named options of each choice setting of Modo's procedural textures, built in and Enhance: Modo's (a Noise's
type, a Grid's, an fBm's Noise Type and so on), for writing them as MoonRay map shaders. Writes test-results/cl-export/prep/pattern_choices.json."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\cl-export\prep\pattern_choices.json')
result = {}
try:
    lx.eval('scene.new')
    scene = modo.Scene()
    service = lx.service.Scene()
    texture = service.ItemTypeLookup('textureLayer')
    kinds = [service.ItemTypeName(service.ItemTypeByIndex(i)) for i in range(service.ItemTypeCount())]
    kinds = ['noise', 'cellular', 'checker', 'grid', 'dots', 'wood', 'weave', 'ripples'] + sorted(k for k in kinds if k.startswith('val.'))
    for kind in kinds:
        item = scene.addItem(kind)
        raw = item.internalItem
        found = {}
        for index in range(raw.ChannelCount()):
            try:
                hints = raw.ChannelIntHint(index)
            except Exception:
                continue
            if hints:
                found[raw.ChannelName(index)] = [list(h) if isinstance(h, (list, tuple)) else str(h) for h in hints]
        result[kind] = found
except Exception:
    result['error'] = traceback.format_exc()
out.write_text(json.dumps(result, indent=1, default=str))
