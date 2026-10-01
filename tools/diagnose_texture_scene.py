# python
"""Read the current scene's texture assignments without modifying it."""
import json
from pathlib import Path
import traceback
import modo
from moonray_modo import host, layers, properties

root = Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
folder = root / 'test-results/current-texture-scene'
folder.mkdir(parents=True, exist_ok=True)
scene = modo.Scene()
report = {'items': [], 'selected': [i.id for i in scene.selected]}
keys = ('enable', 'render', 'effect', 'opacity', 'blend', 'ptyp', 'ptag',
        'projType', 'uvMap', 'wrapU', 'wrapV', 'tileU', 'tileV',
        'filename', 'colorspace', 'alpha', 'gamma', 'brightness', 'contrast')
for item in layers.ordered_items(scene.renderItem):
    row = {'id': item.id, 'name': item.name, 'type': item.type,
           'parent': item.parent.id if item.parent else None,
           'channels': {k: host.channel(item, k) for k in keys if item.channel(k) is not None}}
    try:
        row['material_tag'] = layers.material_tag(item)
    except Exception as exc:
        row['tag_error'] = str(exc)
    if item.type == 'advancedMaterial':
        row['moonray'] = properties.read(item)
    if item.type == 'imageMap':
        row['connections'] = [{'id': i.id, 'name': i.name, 'type': i.type,
            'channels': {k: host.channel(i, k) for k in keys if i.channel(k) is not None}}
            for i in item.itemGraph('shadeLoc').forward()]
    report['items'].append(row)
try:
    snapshot = host.snapshot()
    (folder/'snapshot.json').write_text(json.dumps(snapshot, indent=2), encoding='utf-8')
    report['warnings'] = snapshot['warnings']
    report['materials'] = snapshot['materials']
    report['meshes'] = [{'name': m['name'], 'materials': sorted(set(m.get('face_materials', []))),
        'uv_count': len(m.get('uvs', []))} for m in snapshot['meshes']]
except Exception:
    report['snapshot_error'] = traceback.format_exc()
(folder/'diagnostic.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print('MoonRay texture diagnostic written to ' + str(folder))
