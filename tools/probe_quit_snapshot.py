# python
"""Does Modo quit cleanly after the kit reads the scene? PROBE_QUIT_STEP: 'snapshot' (host.snapshot), 'evaluated'
(host.snapshot(evaluated_geometry=True)), 'changes' (the preview's scene listener made and closed). The exit code is
the answer (1 clean, 3221225477 the crash in lxPython3's exit)."""
import os
import lx
from PySide2 import QtCore

step = os.environ.get('PROBE_QUIT_STEP', 'snapshot')
lx.eval('item.create mesh')
lx.eval('tool.set prim.cube on'); lx.eval('tool.apply'); lx.eval('tool.set prim.cube off')


def go():
    from moonray_modo import host
    if step == 'snapshot':
        host.snapshot()
    elif step == 'evaluated':
        host.snapshot(evaluated_geometry=True)
    QtCore.QTimer.singleShot(2000, lambda: lx.eval('!app.quit'))


QtCore.QTimer.singleShot(5000, go)
