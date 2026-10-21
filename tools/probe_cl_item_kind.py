# python
"""Command-line test: what an item of MOONRAY_PROBE_SCENE named MOONRAY_PROBE_ITEM is: its name and type, its
polygons by type and size, and the Shader Tree's fur layers. Writes test-results/cl-export/prep/item_kind.json."""
import json
import os
import pathlib
import traceback
import lx
import modo

result = {}
try:
    lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    scene = modo.Scene()
    item = scene.item(os.environ['MOONRAY_PROBE_ITEM'])
    result['name'], result['type'] = item.name, item.type
    mesh = modo.Mesh(item)
    kinds = {}
    for polygon in mesh.geometry.polygons:
        key = str(len(polygon.vertices))
        kinds[key] = kinds.get(key, 0) + 1
    result['points'] = mesh.geometry.vertices.__len__()
    result['polygons'] = kinds
    result['fur'] = [(i.name, i.type) for i in scene.items() if 'fur' in i.type.lower()]
    result['items'] = sorted((i.name, i.type) for i in scene.items('mesh'))
except Exception:
    result['error'] = traceback.format_exc()
pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\cl-export\prep\item_kind.json').write_text(json.dumps(result, indent=1))
