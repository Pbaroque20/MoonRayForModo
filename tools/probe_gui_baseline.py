# python
"""Isolate Modo GUI shutdown from actual PView rendering."""
from pathlib import Path
import json
import lx
from PySide2 import QtCore
root=Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
(root/'test-results/gui-baseline.json').write_text(json.dumps({'app_version':lx.eval('query platformservice appversion ?')}))
QtCore.QTimer.singleShot(3000,lambda:lx.eval('!app.quit'))
