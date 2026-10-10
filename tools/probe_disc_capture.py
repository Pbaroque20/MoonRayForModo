# python
"""Isolated GUI test: the plugin's capture of a physically based sky gives the sun's disc the colour Modo's own
renderer gives it, for the Disc In-Scatter the sky is set to.

No picture is made. The sky is set up as tools/probe_modo_disc.py sets it, the scene is captured as for a render, and
what the capture says of the disc is written down beside the settings, to hold against the table."""
import json
import math
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/disc-capture'
out.mkdir(parents=True, exist_ok=True)
result = {'cases': []}
try:
    from moonray_modo import host
    scene = modo.Scene()
    environment = next(iter(scene.items('environment')))
    layer = next(i for i in environment.children() if i.type == 'envMaterial')
    sun = next(iter(scene.items('sunLight')))
    layer.channel('type').set('physical')
    sun.channel('sunPos').set(False)
    for elevation, haze, amount, disc, normalize in ((30, 2.0, 0.0, 1.0, 0), (30, 2.0, 0.5, 1.0, 0), (30, 2.0, 1.0, 4.0, 0), (10, 4.0, 0.5, 1.0, 0), (30, 2.0, 1.0, 1.0, 1)):
        sun.channel('haze').set(haze)
        sun.rotation.set((-math.radians(elevation), 0, 0), degrees=False)
        layer.channel('disc').set(disc)
        layer.channel('inscatter').set(amount)
        layer.channel('normalize').set(normalize)
        snapshot = host.snapshot()
        light = next(l for l in snapshot['lights'] if l.get('identity') == sun.id)
        result['cases'].append({'elevation': elevation, 'haze': haze, 'inscatter': amount, 'disc_size': disc, 'clamp': normalize,
                                'seen': light.get('disc'), 'camera_visible': light.get('camera_visible'), 'angle': light.get('angle'),
                                'warnings': snapshot.get('warnings', [])[:3]})
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))
