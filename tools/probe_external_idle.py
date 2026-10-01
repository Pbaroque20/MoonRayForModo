# python
"""Isolate C++ external-render lifecycle without Python polling or image writes."""
import lx
from PySide2 import QtCore
lx.eval('layout.Window modoIntro open:false')
lx.eval('layout.Window PViewWindow open:true')
lx.eval('select.viewportInWindow PViewWindow')
lx.eval('viewport.restore {} false pview')
service=lx.service.Host()
names=[lx.object.Factory(service.ServerByIndex('externalrender',i)).Name() for i in range(service.NumServers('externalrender'))]
lx.eval('pview.renderer %d' % names.index('moonray.cpu'))
lx.eval('pview.resume')
QtCore.QTimer.singleShot(5000,lambda:lx.eval('!app.quit'))
