# python
"""Validate new Lighting controls in a separate graphical Modo test profile."""
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
        panel.modo_environment.setChecked(True)
        panel.environment_multiplier.setValue(1)
        base=panel._capture()['environments'][0]['intensity']
        panel.environment_multiplier.setValue(2)
        assert panel._capture()['environments'][0]['intensity']==base*2
        panel.modo_environment.setChecked(False)
        assert not panel._capture()['environments']
        panel._save_settings()
        values=properties.scene_settings()
        assert values['modo_environment'] is False and values['environment_multiplier']==2
        panel._load_settings()
        assert not panel.modo_environment.isChecked() and panel.environment_multiplier.value()==2
        report={'passed':True,'native_panel_controls':True,'capture_multiplier':True,'capture_disable':True,'settings_roundtrip':True}
    except Exception:
        report['error']=traceback.format_exc()
    (root/'test-results/environment/panel.json').write_text(json.dumps(report,indent=2))
    QtCore.QTimer.singleShot(100,lambda:lx.eval('!app.quit'))
lx.eval('moonray.dock')
QtCore.QTimer.singleShot(3000,inspect)
