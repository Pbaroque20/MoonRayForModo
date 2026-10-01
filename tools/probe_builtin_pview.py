# python
"""Control experiment: native Modo PView with no MoonRay binary or controller."""
import lx
from PySide2 import QtCore
lx.eval('layout.Window modoIntro open:false')
lx.eval('layout.Window PViewWindow open:true')
lx.eval('select.viewportInWindow PViewWindow')
lx.eval('viewport.restore {} false pview')
lx.eval('pview.renderer 0')
QtCore.QTimer.singleShot(4000,lambda:lx.eval('!app.quit'))
