# python
"""Integration probe for startup-loaded native PView in a clean test profile."""
import ctypes
import faulthandler
import hashlib
import json
import os
import shutil
from pathlib import Path
import traceback
import lx
import modo
from PySide2 import QtCore,QtGui
from moonray_modo import native_preview

root=Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
folder=root/'test-results/pview-kit'; folder.mkdir(parents=True,exist_ok=True)
fault_log=(folder/'fault.log').open('w')
faulthandler.enable(fault_log,all_threads=True)
report={'pid':os.getpid(),'app_version':lx.eval('query platformservice appversion ?'),'passed':False}
phase=0
ticks=0

def save():
    (folder/'report.json').write_text(json.dumps(report,indent=2))

def finish(error=None):
    if error: report['error']=str(error)
    save()
    timer.stop()
    lx.eval('select.viewportInWindow PViewWindow')
    lx.eval('pview.pause')
    lx.eval('pview.renderer 0')
    native_preview._controller.close()
    QtCore.QTimer.singleShot(2000,lambda:lx.eval('!app.quit'))

def poll():
    global phase,ticks
    ticks+=1
    try:
        controller=native_preview._controller
        report['errors']=dict(controller.errors)
        controller.bridge.MR_preview_frames.argtypes=[ctypes.c_uint]
        controller.bridge.MR_preview_frames.restype=ctypes.c_uint
        report['frames']={str(i):controller.bridge.MR_preview_frames(i) for i in controller.sessions}
        report['diagnostics']={str(i):(controller.bridge.MR_preview_diagnostic(i) or b'').decode('utf-8',errors='replace') for i in controller.sessions}
        report['logs']={str(i):s['renderer'].log[-1500:] for i,s in controller.sessions.items()}
        save()
        if phase==0 and ticks==1:
            lx.eval('select.viewportInWindow PViewWindow')
        if phase==0 and ticks==2:
            lx.eval('pview.renderer %d' % names.index('moonray.cpu'))
        if phase==0 and ticks==3:
            lx.eval('pview.resume')
        if phase==0 and any(n>=3 for n in report['frames'].values()):
            report['first_frames']=dict(report['frames'])
            lx.eval('pview.pause')
            phase=1
        elif phase==1:
            report['paused']=all(controller.bridge.MR_preview_state(i,None)==0 for i in controller.sessions)
            assert report['paused']
            lx.eval('pview.resume')
            phase=2
        elif phase==2 and any(n>=6 for n in report['frames'].values()):
            lx.eval('pview.saveImage {%s} PNG' % (folder/'pview.png'))
            report['saved_image']=(folder/'pview.png').is_file()
            picture=QtGui.QImage(str(folder/'pview.png'))
            report['nonblack_pixels']=sum(picture.pixelColor(x,y).red()>10
                for y in range(picture.height()) for x in range(picture.width()))
            report['render_cycle_passed']=report['saved_image'] and report['nonblack_pixels']>100 and not report['errors']
            finish()
        if ticks>=(150 if globals().get('manual_activation') else 50):
            finish('PView did not complete startup/render/pause/resume before the test deadline.')
    except Exception: finish(traceback.format_exc())

try:
    assert report['app_version']==1619
    native_preview.start()
    assert native_preview._controller is not None, 'Kit startup did not start native preview controller'
    report['startup_loaded']=True
    original_publish=native_preview._controller.publish
    def preserve_frame(identity,path):
        shutil.copy2(path,folder/'source.exr')
        original_publish(identity,path)
    native_preview._controller.publish=preserve_frame
    path=Path(native_preview._controller.bridge._name)
    report['plugin_path']=str(path)
    report['plugin_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    scene=modo.Scene()
    camera=scene.renderCamera
    camera.position.set((0,0,0)); camera.rotation.set((0,0,0))
    camera.channel('focalLen').set(.035)
    scene.renderItem.channel('resX').set(128)
    scene.renderItem.channel('resY').set(128)
    mesh=scene.addMesh('Native PView fixture')
    geo=mesh.geometry
    for point in ((-1,-1,-3),(1,-1,-3),(0,1,-3)): geo.vertices.new(point)
    geo.polygons.new((0,1,2)); geo.setMeshEdits()
    if globals().get('manual_activation'):
        lx.eval('!scene.saveAs {%s} $LXOB true' % (folder/'MoonRay Preview Test.lxo'))
    from moonray_modo import host
    (folder/'scene.json').write_text(json.dumps(host.snapshot(),indent=2))
    lx.eval('pref.value application.modoIntroShowStartup false')
    lx.eval('pref.value pview.startPaused false')
    lx.eval('layout.Window modoIntro open:false')
    lx.eval('layout.Window PViewWindow open:true')
    service=lx.service.Host()
    names=[lx.object.Factory(service.ServerByIndex('externalrender',i)).Name() for i in range(service.NumServers('externalrender'))]
    report['renderers']=names
    save()
    timer=QtCore.QTimer(QtCore.QCoreApplication.instance())
    timer.timeout.connect(poll); timer.start(2000)
except Exception:
    report['error']=traceback.format_exc(); save()
    QtCore.QTimer.singleShot(100,lambda:lx.eval('!app.quit'))
