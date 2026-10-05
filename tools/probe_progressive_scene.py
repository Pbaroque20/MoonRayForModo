# python
"""Capture the user's artifact-reproduction scene in an isolated Modo profile."""
from pathlib import Path
import json,traceback
import lx
from PySide2 import QtCore
ROOT=Path('C:/Users/Raphael Tobar/MoonRayForModo')
OUT=ROOT/'test-results/progressive-artifacts';OUT.mkdir(parents=True,exist_ok=True)
try:
    lx.eval('scene.open {%s}'%(OUT/'test-copy.lxo'))
    from moonray_modo.panel import Panel
    panel=Panel()
    scene=panel._capture()
    (OUT/'snapshot.json').write_text(json.dumps(scene),encoding='utf-8')
    (OUT/'settings.json').write_text(json.dumps(panel._settings_values(),indent=2),encoding='utf-8')
    (OUT/'capture.json').write_text(json.dumps({'ok':True,'warnings':scene.get('warnings',[]),'meshes':len(scene.get('meshes',[]))},indent=2),encoding='utf-8')
    try:
        panel.dispose()
    except Exception:
        (OUT/"cleanup-error.txt").write_text(traceback.format_exc(),encoding="utf-8")
except BaseException:
    (OUT/'capture.json').write_text(json.dumps({'ok':False,'error':traceback.format_exc()},indent=2),encoding='utf-8')
QtCore.QTimer.singleShot(100,lambda:lx.eval('!app.quit'))
