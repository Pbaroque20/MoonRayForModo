# python
"""Isolated GUI test: what Modo calls the preview's custom view."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\view-name.json')
result = {}
try:
    host = lx.service.Host()
    factory = host.LookupServer('customview', 'MoonRayForModoPreview', 0)
    result['username'] = lx.object.Factory(factory).InfoTag(lx.symbol.sSRV_USERNAME)
except Exception:
    result['error'] = traceback.format_exc()
try:
    lx.eval('viewport.restore base.MoonRayForModoViewport false customview')
    result['docked'] = True
except Exception:
    result['dock_error'] = traceback.format_exc()
out.write_text(json.dumps(result, indent=2))
QtCore.QTimer.singleShot(4000, lambda: lx.eval('app.quit'))
