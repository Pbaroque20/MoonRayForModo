# python
import json
from pathlib import Path
import lx
from PySide2 import QtCore
from moonray_modo import native_preview
controller=native_preview.start()
service=lx.service.Host()
report={'path':controller.bridge._name,'before':controller.bridge.MR_preview_ids(None,0),
        'renderers':[lx.object.Factory(service.ServerByIndex('externalrender',i)).Name() for i in range(service.NumServers('externalrender'))]}
factory=lx.object.Factory(service.LookupServer('externalrender','moonray.cpu',1))
server=lx.object.ExternalRender(factory.Spawn())
report['spawned']=controller.bridge.MR_preview_ids(None,0)
server.Start()
Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\controller-identity.json').write_text(json.dumps(report,indent=2))
QtCore.QTimer.singleShot(10000,lambda:lx.eval('!app.quit'))
