# python
"""Command-line: the choices Modo's Tension Texture offers for its Type. Writes test-results/tension/types.json."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\tension')
report = {}
try:
    lx.eval('scene.new')
    scene = modo.Scene()
    scene.select(next(i for i in scene.items('advancedMaterial')))
    lx.eval('shader.create tensionTexture')
    layer = next(i for i in scene.items('tensionTexture'))
    channel = layer.channel('type')
    for name in ('possibleValues', 'enumValues'):
        try:
            report[name] = list(getattr(channel, name))
        except Exception as exc:
            report[name] = str(exc)
    try:
        hints = lx.object.Item(layer._item).ChannelEvalType if False else None
        svc = lx.service.Scene()
        kind = svc.ItemTypeLookup('tensionTexture')
        cid = layer._item.ChannelLookup('type')
        hints = layer._item.ChannelHints(cid) if hasattr(layer._item, 'ChannelHints') else None
        report['hints'] = str(hints)
    except Exception as exc:
        report['hints'] = str(exc)
    tried = {}
    for i in range(6):
        try:
            channel.set(i)
            tried[i] = channel.get()
        except Exception as exc:
            tried[i] = str(exc)
    report['by_index'] = tried
except Exception:
    report['error'] = traceback.format_exc()
(out / 'types.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
