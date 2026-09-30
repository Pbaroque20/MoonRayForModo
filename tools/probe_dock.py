# python
"""Verify the preview inside a native viewport in a disposable graphical profile."""
import json
from pathlib import Path
import traceback
import lx
from PySide2 import QtCore,QtWidgets
root=Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
result={}
def inspect():
    try:
        from moonray_modo.panel import Panel
        panels=[w for w in QtWidgets.QApplication.allWidgets() if isinstance(w,Panel) and w.isVisible()]
        result['panels']=[{'size':[p.width(),p.height()],'native_parent':p.parent() is not None,
                           'floating':p.isWindow()} for p in panels]
        result['viewport_type']=lx.eval('viewport.type ?')
        assert panels and not panels[0].isWindow(), 'No embedded preview'
        panels[0].settings_toggle.setChecked(False)
        QtWidgets.QApplication.processEvents()
        assert not panels[0].tabs.isVisible()
        panels[0].window().grab().save(str(root/'test-results/docked-preview.png'))
        result['passed']=True
    except Exception:
        result['error']=traceback.format_exc()
    (root/'test-results/dock.json').write_text(json.dumps(result,indent=2))
    QtCore.QTimer.singleShot(1000,lambda:lx.eval('!app.quit'))
try:
    result['before']=lx.eval('viewport.type ?')
    lx.eval('moonray.dock')
    QtCore.QTimer.singleShot(3000,inspect)
except Exception:
    result['error']=traceback.format_exc()
    (root/'test-results/dock.json').write_text(json.dumps(result,indent=2))
