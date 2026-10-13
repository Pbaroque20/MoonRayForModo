# python
"""Discover where Modo keeps its colour management: the scene's OCIO configuration, an output's view and the defaults."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\color-management.json')
report = {}


def held(item):
    found = {}
    for index in range(item.ChannelCount()):
        name = item.ChannelName(index)
        if any(word in name.lower() for word in ('ocio', 'color', 'colour', 'gamma', 'lut', 'tone', 'view')):
            try:
                value = item.channel(name).get()
                if isinstance(value, (str, int, float, bool)) or value is None:
                    found[name] = value
            except Exception as exc:
                found[name] = 'error: %s' % exc
    return found


def look():
    try:
        scene = modo.Scene()
        report['scene_item'] = [scene.sceneItem.type, held(scene.sceneItem)]
        report['render_item'] = held(scene.renderItem)
        report['outputs'] = {item.name: held(item) for item in scene.items('renderOutput')}
        for query in ('pref.value colormanagement.ocioConfig ?', 'pref.value colormanagement.default_config ?', 'pref.value application.colormanagement ?',
                      'colormanagement.config ?', 'user.value ocio.config ?'):
            try:
                report.setdefault('queries', {})[query] = lx.eval(query)
            except Exception as exc:
                report.setdefault('queries', {})[query] = 'error: %s' % str(exc)[:80]
        try:
            service = lx.service.ColorMapping()
            report['configs'] = [service.ConfigName(i) for i in range(service.ConfigCount())]
            report['config_paths'] = [service.ConfigFullPath(i) for i in range(service.ConfigCount())]
        except Exception:
            report['service_error'] = traceback.format_exc()[-600:]
        try:
            report['service_methods'] = [name for name in dir(lx.service.ColorMapping()) if not name.startswith('_')]
        except Exception:
            pass
    except Exception:
        report['error'] = traceback.format_exc()
    out.write_text(json.dumps(report, indent=1, default=str))
    lx.eval('!app.quit')


QtCore.QTimer.singleShot(6000, look)
