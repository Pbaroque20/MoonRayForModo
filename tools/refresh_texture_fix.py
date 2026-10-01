# python
"""Apply the installed texture fix to a running Modo without restarting it."""
import importlib
import json
from pathlib import Path
import modo
from PySide2 import QtWidgets
from moonray_modo import textures, layers, host, panel

importlib.reload(textures)
importlib.reload(layers)
scene = modo.Scene()
selected = [i for i in scene.selected if i.type == 'imageMap']
if len(selected) != 1:
    raise ValueError('Select the image layer to repair in the Shader Tree, then run this script again.')
layer = selected[0]
tag = layers.material_tag(layer)
before = host.snapshot()
material = before['materials'].get(tag, {})
base_id = material.get('base_layer_id')
siblings = list(layer.parent.children()) if layer.parent else []
base = next((i for i in siblings if i.id == base_id), None)
if base is None:
    raise ValueError('The image and its material must be inside the same Shader Tree group.')
old_index = next(n for n,i in enumerate(siblings) if i.id == layer.id)
base_index = next(n for n,i in enumerate(siblings) if i.id == base.id)
moved = old_index > base_index
parent = layer.parent
try:
    if moved:
        layer.setParent(parent, base_index)
    after = host.snapshot()
    effect = textures.EFFECT_ALIASES.get(host.channel(layer, 'effect'), host.channel(layer, 'effect'))
    assert effect in after['materials'][tag].get('textures', {}), 'Selected image is still not exported'
except Exception:
    if moved:
        layer.setParent(parent, old_index)
    raise
folder = Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\current-texture-scene')
folder.mkdir(parents=True, exist_ok=True)
(folder/'fixed-snapshot.json').write_text(json.dumps(after, indent=2), encoding='utf-8')
(folder/'repair.json').write_text(json.dumps({'layer': layer.name, 'effect': effect,
    'moved_above_material': moved, 'warnings': after['warnings']}, indent=2), encoding='utf-8')
app = QtWidgets.QApplication.instance()
if app:
    for widget in app.allWidgets():
        if isinstance(widget, panel.Panel) and not widget.disposed:
            widget.render_once()
print('Texture fix applied; image exported and MoonRay preview refreshed.')
