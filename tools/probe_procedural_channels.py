# python
"""Discover the settings of Modo's cellular, wood, weave and ripples layers: every channel and what it starts at."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\procedural-channels.json')
report = {}
SKIP = ('enable', 'opacity', 'blend', 'invert', 'effect', 'gldisp', 'ignSclGrp', 'render')


def look():
    try:
        scene = modo.Scene()
        for kind in ('cellular', 'wood', 'weave', 'ripples', 'noise', 'checker'):
            try:
                lx.eval('shader.create %s' % kind)
                layer = [item for item in scene.items('textureLayer') if item.type == kind][-1]
                held = {}
                for index in range(layer.ChannelCount()):
                    name = layer.ChannelName(index)
                    if name in SKIP:
                        continue
                    try:
                        value = layer.channel(name).get()
                        if isinstance(value, (str, int, float, bool)):
                            held[name] = value
                    except Exception:
                        pass
                report[kind] = held
            except Exception as exc:
                report[kind] = 'error: %s' % exc
    except Exception:
        report['error'] = traceback.format_exc()
    out.write_text(json.dumps(report, indent=1, default=str))
    lx.eval('!app.quit')


QtCore.QTimer.singleShot(6000, look)
