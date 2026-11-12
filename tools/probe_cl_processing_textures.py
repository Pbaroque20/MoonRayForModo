# python
"""Command-line: Modo's Processing textures as items: for Constant, Gradient, Occlusion, Process, Tension Texture,
Variation Texture and Vertex Map Texture, the item type Add Layer makes and every channel with its default, and the
choices of each text channel (the Gradient's inputs, the Variation's sources). Writes
test-results/processing-textures/report.json."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\processing-textures')
out.mkdir(parents=True, exist_ok=True)
result = {'made': {}, 'errors': {}}
# Candidate item type names for each, tried in turn.
CANDIDATES = {'Constant': ['constant'], 'Gradient': ['gradient'], 'Occlusion': ['occlusion'], 'Process': ['process'],
              'Tension Texture': ['tensionTexture', 'tension'], 'Variation Texture': ['variationTexture', 'variation'],
              'Vertex Map Texture': ['vmapTexture']}


def channels(item):
    found = {}
    for index in range(item.internalItem.ChannelCount()):
        name = item.internalItem.ChannelName(index)
        try:
            value = item.channel(name).get()
        except Exception as exc:
            value = '<%s>' % type(exc).__name__
        found[name] = value if isinstance(value, (int, float, str, bool)) or value is None else str(value)
    return found


def choices(item, name):
    """The text hints a channel takes (its choices), where it has them."""
    try:
        scene_service = lx.service.Scene()
        index = item.internalItem.ChannelLookup(name)
        hints = item.internalItem.ChannelEncodingHint(index) if hasattr(item.internalItem, 'ChannelEncodingHint') else None
        return [h[0] for h in hints] if hints else None
    except Exception:
        return None


try:
    lx.eval('scene.new')
    scene = modo.Scene()
    render = scene.renderItem
    for label, names in CANDIDATES.items():
        for name in names:
            try:
                item = scene.addItem(name)
                item.setParent(render, len(render.children()))
                found = channels(item)
                result['made'][label] = {'type': item.type, 'channels': found,
                                         'choices': {k: choices(item, k) for k in found if isinstance(found[k], str)}}
                break
            except Exception as exc:
                result['errors'].setdefault(label, []).append('%s: %s' % (name, exc))
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
