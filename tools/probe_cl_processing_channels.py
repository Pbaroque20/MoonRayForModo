# python
"""Command-line: the channels (and defaults) of Modo's Variation Texture and Process layers, the choices of
Variation's Type and of a Gradient's input (by index), for the rest of the Processing textures.
Writes test-results/processing-channels/report.json."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\processing-channels')
out.mkdir(parents=True, exist_ok=True)
report = {}


def channels(layer):
    held = {}
    for channel in layer.channels():
        try:
            value = channel.get()
            held[channel.name] = value if isinstance(value, (int, float, str)) else type(value).__name__
        except Exception as exc:
            held[channel.name] = 'unread: %s' % exc
    return held


def choices(channel, count=40):
    found = {}
    for i in range(count):
        try:
            channel.set(i)
            found[i] = channel.get()
        except Exception as exc:
            found[i] = 'error: %s' % exc
    return found


try:
    lx.eval('scene.new')
    scene = modo.Scene()
    material = next(i for i in scene.items('advancedMaterial'))
    for kind in ('variationTexture', 'process', 'gradient'):
        scene.select(material)
        lx.eval('shader.create %s' % kind)
        layer = next(i for i in scene.items(kind))
        report[kind] = {'channels': channels(layer)}
    report['variationTexture']['type'] = choices(next(i for i in scene.items('variationTexture')).channel('type'), 8)
    report['gradient']['param'] = choices(next(i for i in scene.items('gradient')).channel('param'), 40)
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
