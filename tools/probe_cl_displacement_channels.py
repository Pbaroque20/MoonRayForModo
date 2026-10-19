# python
"""Command-line test: the channels of Modo's material, image layer and render item that have to do with displacement
or stencils, with their values in a new scene."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\displacement-channels')
out.mkdir(parents=True, exist_ok=True)
result = {}


def channels(item, words):
    found = {}
    for index in range(item.ChannelCount()):
        name = item.ChannelName(index)
        if any(w in name.lower() for w in words):
            try:
                found[name] = item.channel(name).get()
            except Exception as exc:
                found[name] = 'unread: %s' % exc
    return found


try:
    scene = modo.Scene()
    material = next(iter(scene.items('advancedMaterial')))
    lx.eval('item.create mesh')
    lx.eval('shader.create imageMap') if False else None
    layer = scene.addItem('imageMap')
    words = ('disp', 'stencil', 'sheen', 'flat', 'film', 'thin', 'tint', 'refl', 'aniso', 'irid', 'brdf', 'spec', 'coat')
    result['material'] = channels(material, words)
    result['imageMap'] = channels(layer, words + ('min', 'max', 'value'))
    result['render'] = channels(scene.renderItem, words)
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
