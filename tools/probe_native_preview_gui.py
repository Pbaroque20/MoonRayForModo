# python
"""Inspect native preview commands and server discovery in the isolated GUI."""
import json
import os
from pathlib import Path
import traceback
import lx
from PySide2 import QtCore
import ctypes
root=Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
attempts=0
keep_open=globals().get('keep_open',False)
def inspect():
    report={'pid':os.getpid()}
    folder=root/'test-results/native-preview'; folder.mkdir(parents=True,exist_ok=True)
    def checkpoint(stage):
        report['stage']=stage
        (folder/'gui.json').write_text(json.dumps(report,indent=2))
    try:
        checkpoint('starting')
        report['app_version']=lx.eval('query platformservice appversion ?')
        assert report['app_version']==1619, report['app_version']
        lx.eval('layout.Window modoIntro open:false')
        lx.eval('pref.value application.modoIntroShowStartup false')
        from moonray_modo import native_preview
        report['server']=lx.object.Factory(lx.service.Host().LookupServer('externalrender','moonray.cpu',1)).Name()
        controller=native_preview.start(root/'build/modo-bridge/MoonRayPreview.lx')
        commands=lx.service.Command(); found=[]
        for index in range(commands.CommandCount()):
            try:
                command=lx.object.Command(commands.CommandByIndex(index)); name=command.Name()
                if any(word in name.lower() for word in ('preview','pview','renderer')): found.append(name)
            except Exception: pass
        report['commands']=found
        checkpoint('commands listed')
        for name in ('pview.renderer','pview.saveImage'):
            command=lx.service.Command().Spawn(0,name)
            attrs=lx.object.Attributes(command)
            report[name]=[(attrs.Name(i),attrs.TypeName(i)) for i in range(attrs.Count())]
            checkpoint(name+' arguments inspected')
        checkpoint('opening viewport')
        lx.eval('layout.Window PViewWindow open:true')
        lx.eval('select.viewportInWindow PViewWindow')
        lx.eval('viewport.restore {} false pview')
        checkpoint('selecting renderer')
        report['renderers']=[lx.object.Factory(lx.service.Host().ServerByIndex('externalrender',i)).Name()
                             for i in range(lx.service.Host().NumServers('externalrender'))]
        index=report['renderers'].index('moonray.cpu')
        lx.eval('pview.renderer %d' % index)
        report['renderer_query']=lx.eval('pview.renderer ?')
        checkpoint('resuming')
        lx.eval('pview.resume')
        report['instance_count']=controller.bridge.MR_preview_ids(None,0)
        report['preview_opened']=True
    except Exception: report['error']=traceback.format_exc()
    folder=root/'test-results/native-preview'; folder.mkdir(parents=True,exist_ok=True)
    (folder/'gui.json').write_text(json.dumps(report,indent=2))
    QtCore.QTimer.singleShot(5000,finish)
def finish():
    global attempts
    attempts+=1
    from moonray_modo import native_preview
    controller=native_preview._controller
    report={'pid':os.getpid(),'errors':controller.errors if controller else {}}
    if controller:
        count=controller.bridge.MR_preview_ids(None,0)
        ids=(ctypes.c_uint*max(1,count))()
        controller.bridge.MR_preview_ids(ids,count)
        report['states']={str(i):controller.bridge.MR_preview_state(i,None) for i in ids[:count]}
        controller.bridge.MR_preview_frames.argtypes=[ctypes.c_uint]
        controller.bridge.MR_preview_frames.restype=ctypes.c_uint
        report['frames']={str(i):controller.bridge.MR_preview_frames(i) for i in controller.sessions}
        report['logs']={str(i):s['renderer'].log[-2000:] for i,s in controller.sessions.items()}
    (root/'test-results/native-preview/frames.json').write_text(json.dumps(report,indent=2))
    if keep_open or (attempts<24 and not any(report.get('frames',{}).values()) and not report['errors']):
        QtCore.QTimer.singleShot(5000,finish)
    else:
        QtCore.QTimer.singleShot(5000,lambda:lx.eval('!app.quit'))
# Opening/selecting viewports must execute in Modo's command context. Doing it
# from a Qt timer can leave commands targeting the old welcome viewport.
inspect()
