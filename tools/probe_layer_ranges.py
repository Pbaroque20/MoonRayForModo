# python
"""Discover which texture layers have a Low Value and High Value (channels min and max), in an isolated Modo."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\layer-ranges.json')
report = {}


def look():
    try:
        scene = modo.Scene()
        for kind in ('noise', 'checker', 'grid', 'dots', 'gradient', 'constant', 'cellular', 'wood', 'weave', 'ripples'):
            try:
                lx.eval('shader.create %s' % kind)
                layer = [item for item in scene.items('textureLayer') if item.type == kind][-1]
                held = {}
                for name in ('min', 'max', 'value1', 'value2', 'bias', 'gain', 'invert'):
                    try:
                        held[name] = layer.channel(name).get()
                    except Exception:
                        pass
                report[kind] = [layer.type, held]
            except Exception as exc:
                report[kind] = 'error: %s' % exc
    except Exception:
        report['error'] = traceback.format_exc()
    out.write_text(json.dumps(report, indent=1, default=str))
    lx.eval('!app.quit')


QtCore.QTimer.singleShot(6000, look)
