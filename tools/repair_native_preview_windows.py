# python
"""Repair only the isolated test's accidental preview-in-welcome layout."""
import json
from pathlib import Path
import traceback
import lx
root=Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
report={'app_version':lx.eval('query platformservice appversion ?'),'commands':[]}
try:
    assert report['app_version']==1619
    for command in ('layout.Window modoIntro open:false',
                    'layout.Window PViewWindow open:true',
                    'select.viewportInWindow PViewWindow',
                    'viewport.restore {} false pview'):
        lx.eval(command)
        report['commands'].append(command)
    host=lx.service.Host()
    servers=[lx.object.Factory(host.ServerByIndex('externalrender',i)).Name()
             for i in range(host.NumServers('externalrender'))]
    lx.eval('pview.renderer %d' % servers.index('moonray.cpu'))
    lx.eval('pview.resume')
    report['renderer']=lx.eval('pview.renderer ?')
    from moonray_modo import native_preview
    if native_preview._controller:
        report['native_instances']=native_preview._controller.bridge.MR_preview_ids(None,0)
except Exception:
    report['error']=traceback.format_exc()
(root/'test-results/native-preview/windows-repair.json').write_text(json.dumps(report,indent=2))
