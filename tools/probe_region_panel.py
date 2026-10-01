# python
"""Check region controls and scene-owned settings in an isolated Modo GUI."""
import json
from pathlib import Path
import traceback
import lx
from PySide2 import QtCore,QtWidgets
root=Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
def inspect():
    report={}
    try:
        from moonray_modo.panel import Panel
        from moonray_modo import properties
        panel=next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w,Panel) and w.isVisible())
        assert 'region' not in panel._capture()
        panel.region_enabled.setChecked(True)
        for control,value in zip(panel.region_controls,[10,20,70,80]): control.setValue(value)
        assert panel._capture()['region']==[.1,.2,.7,.8]
        panel._save_settings()
        assert properties.scene_settings()['region']==[.1,.2,.7,.8]
        panel.region_enabled.setChecked(False)
        panel._load_settings()
        assert panel.region_enabled.isChecked()
        assert panel._capture()['region']==[.1,.2,.7,.8]
        report={'passed':True,'capture':True,'settings_roundtrip':True}
    except Exception:
        report['error']=traceback.format_exc()
    folder=root/'test-results/regions'; folder.mkdir(parents=True,exist_ok=True)
    (folder/'panel.json').write_text(json.dumps(report,indent=2))
    QtCore.QTimer.singleShot(100,lambda:lx.eval('!app.quit'))
lx.eval('moonray.dock')
QtCore.QTimer.singleShot(3000,inspect)
