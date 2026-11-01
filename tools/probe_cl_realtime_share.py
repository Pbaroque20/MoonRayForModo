# python
"""Headless test: Realtime Sample % in a new scene, changed by its command, and after the scene is saved, closed and opened again.
Writes test-results/realtime-share/report.json."""
import json
import pathlib
import traceback
import lx

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/realtime-share'
out.mkdir(parents=True, exist_ok=True)
result = {}


def share():
    return int(lx.eval('moonray.render.xpu2_realtime ?'))


try:
    result['new scene'] = share()
    lx.eval('moonray.render.xpu2_realtime 55')
    result['changed'] = share()
    path = out / 'saved.lxo'
    lx.eval('!scene.saveAs {%s} $LXOB false' % path)
    lx.eval('!scene.close')
    lx.eval('scene.new')
    result['another new scene'] = share()
    lx.eval('!scene.open {%s} normal' % path)
    result['opened again'] = share()
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1))
