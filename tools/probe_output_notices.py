# python
"""Isolated GUI test: a new scene's render outputs are not reported as layers the plugin cannot translate."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/output-notices'
out.mkdir(parents=True, exist_ok=True)
result = {}
try:
    from moonray_modo import host
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    import modo
    result['outputs'] = [item.name for item in modo.Scene().items('renderOutput')]
    result['warnings'] = host.snapshot().get('warnings', [])
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))
