# python
"""Does Modo quit cleanly with a graph editor open? A cube, the graph editor opened on its material, then app.quit.
PROBE_QUIT_STEP narrows it down: 'editor' (the default) opens the editor; 'hidden' opens and hides it; 'closed' opens
and closes it before quitting. Writes test-results/quit-graph-editor/<step>.json; the exit code is the answer."""
import json
import os
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\quit-graph-editor')
out.mkdir(parents=True, exist_ok=True)
step = os.environ.get('PROBE_QUIT_STEP', 'editor')
result = {'step': step}
held = {}
try:
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on'); lx.eval('tool.apply'); lx.eval('tool.set prim.cube off')
    scene = modo.Scene()
    material = next(i for i in scene.items('advancedMaterial'))
    from moonray_modo import node_editor
    held['editor'] = node_editor.open_editor(material)
    result['opened'] = True
except Exception:
    result['error'] = traceback.format_exc()
(out / (step + '.json')).write_text(json.dumps(result, indent=2))


def later():
    try:
        if step == 'hidden':
            held['editor'].hide()
        elif step == 'closed':
            held['editor'].close()
    except Exception:
        result['later_error'] = traceback.format_exc()
        (out / (step + '.json')).write_text(json.dumps(result, indent=2))
    QtCore.QTimer.singleShot(3000, lambda: lx.eval('!app.quit'))


QtCore.QTimer.singleShot(6000, later)
