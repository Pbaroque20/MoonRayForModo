# python
"""Command-line: the channels of Modo's Tension Texture and their defaults. Writes test-results/tension/channels.json."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\tension')
out.mkdir(parents=True, exist_ok=True)
report = {}
try:
    lx.eval('scene.new')
    scene = modo.Scene()
    scene.select(next(i for i in scene.items('advancedMaterial')))
    lx.eval('shader.create tensionTexture')
    layer = next(i for i in scene.items('tensionTexture'))
    for channel in layer.channels():
        try:
            report[channel.name] = channel.get()
        except Exception as exc:
            report[channel.name] = 'unread: %s' % exc
except Exception:
    report['error'] = traceback.format_exc()
(out / 'channels.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
